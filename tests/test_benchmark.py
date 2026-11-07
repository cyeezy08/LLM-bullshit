import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from benchmark import (
    REVIEW_CASES,
    build_diff,
    load_api_key,
    parse_review_answer,
    parse_sse_response,
    percentile,
    request_completion,
    review_prompt,
    run_pipeline_case,
    summarize,
    summarize_reviews,
)


class BenchmarkSummaryTests(unittest.TestCase):
    def test_loads_key_from_env_file(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text('OTHER=value\nCROWLLM_API_KEY="test-key"\n')
            self.assertEqual(load_api_key(env_file), "test-key")

    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(percentile([30, 10, 20, 40], 95), 40)
        self.assertIsNone(percentile([], 95))

    def test_synthetic_prompt_forbids_exploits_and_has_safe_control(self):
        prompt = review_prompt(
            REVIEW_CASES["vulnerable"]["code"],
            REVIEW_CASES["vulnerable"]["context"],
        )
        self.assertIn("Do not provide an exploit", prompt)
        self.assertIn("trusted and are not modified", prompt)
        self.assertFalse(REVIEW_CASES["safe_control"]["expected_finding"])

    def test_parse_review_answer_and_score_control_cases(self):
        answer = parse_review_answer(
            '```json\n{"finding": true, "category": "path traversal"}\n```'
        )
        self.assertEqual(answer["finding"], True)
        self.assertIsNone(parse_review_answer("not valid json"))

        samples = [
            {
                "model": "model-a",
                "ok": True,
                "review": {"finding": True},
                "expected_finding": True,
            },
            {
                "model": "model-a",
                "ok": True,
                "review": {"finding": False},
                "expected_finding": False,
            },
        ]
        result = summarize_reviews(samples, ["model-a"])["model-a"]
        self.assertEqual(result["true_positive"], 1)
        self.assertEqual(result["true_negative"], 1)
        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)

    def test_build_diff_omits_newline_only_changes(self):
        source = "def read():\n    return 1\n"
        self.assertEqual(build_diff(source, source.rstrip("\n")), "")

    def test_summary_separates_successes_and_failures(self):
        summary = summarize(
            [
                {
                    "model": "model-a",
                    "ok": True,
                    "latency_ms": 100,
                    "completion_tokens_per_second_e2e": 10,
                },
                {
                    "model": "model-a",
                    "ok": True,
                    "latency_ms": 200,
                    "completion_tokens_per_second_e2e": 20,
                },
                {"model": "model-a", "ok": False, "latency_ms": 5},
            ],
            ["model-a"],
        )

        self.assertEqual(summary["model-a"]["attempts"], 3)
        self.assertEqual(summary["model-a"]["successes"], 2)
        self.assertEqual(summary["model-a"]["failures"], 1)
        self.assertEqual(summary["model-a"]["latency_ms"]["median"], 150)
        self.assertEqual(
            summary["model-a"]["completion_tokens_per_second_e2e_median"], 15
        )

    def test_request_uses_bearer_auth_and_reads_token_usage(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def read(self):
                return (
                    b'{"choices":[{"message":{"content":"benchmark-ok"},'
                    b'"finish_reason":"stop"}],'
                    b'"usage":{"completion_tokens":2}}'
                )

        with patch(
            "benchmark.urllib.request.urlopen", return_value=FakeResponse()
        ) as call:
            result = request_completion(
                model="model-a",
                prompt="benchmark",
                endpoint="https://example.invalid/v1/chat/completions",
                api_key="test-key",
                timeout=1,
                max_tokens=4096,
            )

        self.assertEqual(
            call.call_args.args[0].get_header("Authorization"), "Bear" + "er test-key"
        )
        self.assertEqual(
            call.call_args.args[0].get_header("User-agent"),
            "LLM-bullshit-benchmark/0.1",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["completion_tokens"], 2)
        self.assertEqual(result["finish_reason"], "stop")

    def test_sse_stream_collects_delta_content_and_usage(self):
        class FakeResponse:
            def __iter__(self):
                return iter(
                    [
                        b'data: {"choices":[{"delta":{"content":"hello "},'
                        b'"finish_reason":null}]}\r\n',
                        b"\r\n",
                        b'data: {"choices":[{"delta":{"content":"world"},'
                        b'"finish_reason":null}]}\n',
                        b"\n",
                        b'data: {"choices":[{"delta":{}, "finish_reason":"stop"}],'
                        b'"usage":{"completion_tokens":2}}\n',
                        b"\n",
                        b"data: [DONE]\n",
                        b"\n",
                    ]
                )

        streamed = []
        answer, usage, finish_reason = parse_sse_response(
            FakeResponse(), streamed.append
        )
        self.assertEqual(answer, "hello world")
        self.assertEqual("".join(streamed), answer)
        self.assertEqual(usage["completion_tokens"], 2)
        self.assertEqual(finish_reason, "stop")

    def test_request_completion_sets_stream_and_reassembles_sse(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def __iter__(self):
                return iter(
                    [
                        b'data: {"choices":[{"delta":{"content":"{}"},'
                        b'"finish_reason":null}]}\n',
                        b"\n",
                        b'data: {"choices":[{"delta":{}, "finish_reason":"stop"}],'
                        b'"usage":{"completion_tokens":2}}\n',
                        b"\n",
                        b"data: [DONE]\n",
                        b"\n",
                    ]
                )

        with patch(
            "benchmark.urllib.request.urlopen", return_value=FakeResponse()
        ) as call:
            result = request_completion(
                model="model-a",
                prompt="benchmark",
                endpoint="https://example.invalid/v1/chat/completions",
                api_key="test-key",
                timeout=1,
                stream=True,
                max_tokens=4096,
                json_mode=True,
            )

        payload = json.loads(call.call_args.args[0].data)
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("reasoning_effort", payload)
        self.assertTrue(result["ok"])
        self.assertEqual(result["answer"], "{}")
        self.assertEqual(result["completion_tokens"], 2)

    def test_pipeline_runs_three_roles_sequentially(self):
        outputs = [
            {"finding": True, "category": "path traversal", "summary": "Unsafe path join."},
            {"action": "resolve and contain", "constraints": [], "expected_behavior": "Reject outside paths."},
            {
                "fixed_code": "from pathlib import Path\n\ndef read_report(root: Path, filename: str) -> str:\n    candidate = (root / filename).resolve()\n    if not candidate.is_relative_to(root.resolve()):\n        raise ValueError('outside root')\n    return candidate.read_text(encoding='utf-8')\n",
                "explanation": "Validate resolved paths.",
            },
        ]

        def fake_request(**kwargs):
            self.assertTrue(kwargs["stream"])
            return {
                "ok": True,
                "answer": json.dumps(outputs.pop(0)),
                "latency_ms": 10,
                "completion_tokens": 5,
                "finish_reason": "stop",
            }

        with patch("benchmark.request_completion", side_effect=fake_request):
            result = run_pipeline_case(
                case_name="vulnerable",
                case=REVIEW_CASES["vulnerable"],
                models=["model-a", "model-b", "model-c"],
                endpoint="https://example.invalid/v1/chat/completions",
                api_key="test-key",
                timeout=1,
                max_tokens=4096,
            )

        self.assertTrue(result["complete"])
        self.assertTrue(result["finding_correct"])
        self.assertEqual(
            [stage["stage"] for stage in result["stages"]],
            ["analyze", "plan", "implement"],
        )
        self.assertIn(
            "--- a/sample.py",
            result["stages"][2]["output"]["patch"],
        )
        self.assertTrue(result["stages"][2]["output"]["syntax_valid"])

    def test_pipeline_skips_later_roles_after_invalid_analysis(self):
        with patch(
            "benchmark.request_completion",
            return_value={
                "ok": True,
                "answer": "not json",
                "latency_ms": 10,
                "completion_tokens": 2,
                "finish_reason": "stop",
            },
        ) as request:
            result = run_pipeline_case(
                case_name="vulnerable",
                case=REVIEW_CASES["vulnerable"],
                models=["model-a", "model-b", "model-c"],
                endpoint="https://example.invalid/v1/chat/completions",
                api_key="test-key",
                timeout=1,
            )

        self.assertEqual(request.call_count, 1)
        self.assertFalse(result["complete"])
        self.assertTrue(result["stages"][1]["skipped"])
        self.assertTrue(result["stages"][2]["skipped"])

    def test_http_error_includes_diagnostic_without_leaking_key(self):
        error = HTTPError(
            "https://example.invalid",
            503,
            "Service Unavailable",
            {},
            BytesIO(b'{"message":"upstream unavailable"}'),
        )
        with patch("benchmark.urllib.request.urlopen", side_effect=error):
            result = request_completion(
                model="model-a",
                prompt="benchmark",
                endpoint="https://example.invalid/v1/chat/completions",
                api_key="test-key",
                timeout=1,
            )

        self.assertIn("HTTP 503", result["error"])
        self.assertIn("upstream unavailable", result["error"])
        self.assertNotIn("test-key", result["error"])


if __name__ == "__main__":
    unittest.main()
