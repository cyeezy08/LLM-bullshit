#!/usr/bin/env python3
"""Measure response latency for OpenAI-compatible chat-completion models."""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import math
import os
import random
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_PROMPT = "Reply with exactly: benchmark-ok."
DEFAULT_BASE_URL = "https://crowllm.com/v1"
REVIEW_CASES = {
    "vulnerable": {
        "expected_finding": True,
        "context": (
            "The caller controls filename. The root directory and its contents are "
            "trusted and are not modified during this function call."
        ),
        "code": """from pathlib import Path

def read_report(root: Path, filename: str) -> str:
    return (root / filename).read_text(encoding="utf-8")
""",
    },
    "safe_control": {
        "expected_finding": False,
        "context": (
            "The caller controls filename. The root directory and its contents are "
            "trusted and are not modified during this function call. Concurrent "
            "local filesystem mutation is outside this sample's threat model."
        ),
        "code": """from pathlib import Path

def read_report(root: Path, filename: str) -> str:
    base = root.resolve()
    candidate = (base / filename).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError("report path is outside the configured directory")
    return candidate.read_text(encoding="utf-8")
""",
    },
}


def review_prompt(code: str, context: str = "") -> str:
    return (
        "Review this small, synthetic Python code sample as a defensive code-review "
        "exercise. Decide whether it contains a security-relevant bug under the "
        "stated threat model. Do not report issues outside that model. Do not provide "
        "an exploit, payload, proof of concept, or instructions for testing a real "
        "system. Return only JSON with boolean `finding`, a short `category`, and a "
        "one-sentence `reason`. Be concise.\n\n"
        f"Threat model: {context}\n\n"
        f"```python\n{code}```"
    )


def parse_json_object(answer: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(answer)
    except json.JSONDecodeError:
        start = answer.find("{")
        end = answer.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(answer[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def parse_review_answer(answer: str) -> dict[str, Any] | None:
    parsed = parse_json_object(answer)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("finding"), bool):
        return None
    return parsed


def build_diff(original: str, replacement: str) -> str:
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            replacement.splitlines(keepends=True),
            fromfile="a/sample.py",
            tofile="b/sample.py",
        )
    )


def pipeline_prompt(
    stage: str,
    code: str,
    context: str,
    prior: dict[str, Any] | None = None,
) -> str:
    if stage == "analyze":
        return (
            "You are stage 1 of a defensive review of a synthetic code sample. "
            "Use the stated threat model; do not report out-of-scope issues. "
            "Identify whether there is a security-relevant bug. Do not give exploit "
            "steps, path examples, or hidden reasoning. Return concise JSON only: "
            "finding (boolean) and category (string).\n\n"
            f"Threat model: {context}\n\n"
            f"```python\n{code}```"
        )
    if stage == "plan":
        return (
            "You are stage 2 of a defensive review. Convert the prior finding into a "
            "minimal remediation plan for the synthetic code below. Do not add "
            "exploit steps or speculate beyond the evidence. Return concise JSON "
            "only: action (string), constraints (array of strings), and expected "
            "behavior (string).\n\n"
            f"Prior finding:\n{json.dumps(prior, sort_keys=True)}\n\n"
            f"Threat model: {context}\n\n"
            f"Code:\n```python\n{code}```"
        )
    if stage == "implement":
        return (
            "You are stage 3 of a defensive review. Return the corrected synthetic "
            "code as a complete Python source string in `fixed_code`, plus a one-"
            "sentence `explanation`. Do not execute code or provide an exploit. "
            "Return concise JSON only. If the finding says there is no bug, return "
            "the original code unchanged.\n\n"
            f"Finding:\n{json.dumps(prior['finding'], sort_keys=True)}\n\n"
            f"Remediation plan:\n{json.dumps(prior['plan'], sort_keys=True)}\n\n"
            f"Threat model: {context}\n\n"
            f"Code:\n```python\n{code}```"
        )
    raise ValueError(f"Unknown pipeline stage: {stage}")


def parse_sse_response(
    response: Any, on_chunk: Callable[[str], None] | None = None
) -> tuple[str, dict[str, Any], str | None]:
    content_parts: list[str] = []
    usage: dict[str, Any] = {}
    finish_reason = None
    data_lines: list[str] = []

    def consume_event() -> None:
        nonlocal finish_reason, usage
        if not data_lines:
            return
        data = "\n".join(data_lines)
        data_lines.clear()
        if data == "[DONE]":
            return
        event = json.loads(data)
        if not isinstance(event, dict):
            raise ValueError("SSE event is not a JSON object")
        event_usage = event.get("usage")
        if isinstance(event_usage, dict):
            usage = event_usage
        for choice in event.get("choices", []):
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            text = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(text, str):
                content_parts.append(text)
                if on_chunk:
                    on_chunk(text)
            if choice.get("finish_reason") is not None:
                finish_reason = str(choice["finish_reason"])

    for raw_line in response:
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if not line:
            consume_event()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    consume_event()
    return "".join(content_parts), usage, finish_reason


def summarize_reviews(samples: list[dict[str, Any]], models: list[str]) -> dict[str, Any]:
    samples_by_model = {model: [] for model in models}
    for sample in samples:
        if sample["model"] in samples_by_model:
            samples_by_model[sample["model"]].append(sample)

    summaries: dict[str, Any] = {}
    for model, all_model_samples in samples_by_model.items():
        model_samples = [
            sample
            for sample in all_model_samples
            if sample["ok"] and sample["review"] is not None
        ]
        counts = {
            "true_positive": 0,
            "false_negative": 0,
            "true_negative": 0,
            "false_positive": 0,
        }
        for sample in model_samples:
            predicted = sample["review"]["finding"]
            expected = sample["expected_finding"]
            if expected and predicted:
                counts["true_positive"] += 1
            elif expected:
                counts["false_negative"] += 1
            elif predicted:
                counts["false_positive"] += 1
            else:
                counts["true_negative"] += 1
        total = len(model_samples)
        summaries[model] = {
            **counts,
            "scored_cases": total,
            "unscored_or_failed": len(all_model_samples) - total,
            "accuracy": round(
                (counts["true_positive"] + counts["true_negative"]) / total, 3
            )
            if total
            else None,
            "precision": round(
                counts["true_positive"]
                / (counts["true_positive"] + counts["false_positive"]),
                3,
            )
            if counts["true_positive"] + counts["false_positive"]
            else None,
            "recall": round(
                counts["true_positive"]
                / (counts["true_positive"] + counts["false_negative"]),
                3,
            )
            if counts["true_positive"] + counts["false_negative"]
            else None,
        }
    return summaries


def run_pipeline_case(
    case_name: str,
    case: dict[str, Any],
    models: list[str],
    endpoint: str,
    api_key: str,
    timeout: float,
    max_tokens: int = 4096,
    on_stage_start: Callable[[int, str, str], None] | None = None,
    on_chunk: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    stage_names = ("analyze", "plan", "implement")
    stage_results: list[dict[str, Any]] = []
    prior: dict[str, Any] | None = None

    for index, (model, stage) in enumerate(zip(models, stage_names), start=1):
        if stage == "plan" and prior is None:
            break
        if stage == "implement" and (
            prior is None or not isinstance(prior.get("plan"), dict)
        ):
            break

        prompt = pipeline_prompt(stage, case["code"], case["context"], prior)
        if on_stage_start:
            on_stage_start(index, stage, model)

        streamed_characters = 0

        def count_chunk(text: str) -> None:
            nonlocal streamed_characters
            streamed_characters += len(text)
            if on_chunk:
                on_chunk(text)

        request_attempts = 0
        request_latency_ms = 0.0
        while True:
            request_attempts += 1
            result = request_completion(
                model=model,
                prompt=prompt,
                endpoint=endpoint,
                api_key=api_key,
                timeout=timeout,
                max_tokens=max_tokens,
                stream=True,
                json_mode=True,
                on_chunk=count_chunk,
            )
            request_latency_ms += result["latency_ms"]
            if (
                result["ok"]
                or result.get("error")
                != "invalid API response: SSE response contained no completion text"
                or request_attempts == 2
            ):
                break
        parsed = parse_json_object(result["answer"]) if result["ok"] else None
        valid_output = parsed is not None
        if result.get("finish_reason") == "length":
            valid_output = False
        if stage == "analyze":
            valid_output = valid_output and isinstance(parsed.get("finding"), bool)
        elif stage == "plan":
            valid_output = valid_output and isinstance(parsed.get("action"), str)
        else:
            valid_output = valid_output and isinstance(parsed.get("fixed_code"), str)
            if valid_output:
                fixed_code = parsed["fixed_code"]
                try:
                    ast.parse(fixed_code)
                    parsed["syntax_valid"] = True
                except SyntaxError:
                    parsed["syntax_valid"] = False
                    valid_output = False
                parsed["patch"] = build_diff(case["code"], fixed_code)
        stage_result = {
            "stage": stage,
            "model": model,
            "ok": result["ok"] and valid_output,
            "request_attempts": request_attempts,
            "latency_ms": round(request_latency_ms, 2),
            "completion_tokens": result.get("completion_tokens"),
            "streamed_characters": streamed_characters,
            "finish_reason": result.get("finish_reason"),
            "output": (
                {
                    "finding": parsed["finding"],
                    "category": parsed.get("category", ""),
                }
                if stage == "analyze" and parsed is not None
                else parsed
            ),
        }
        if not result["ok"]:
            stage_result["error"] = result["error"]
        elif not valid_output:
            if result.get("finish_reason") == "length":
                stage_result["error"] = "model response was truncated"
            elif stage == "implement" and parsed and not parsed.get("syntax_valid", True):
                stage_result["error"] = "generated Python source has a syntax error"
            else:
                stage_result["error"] = f"model returned invalid {stage} JSON"
        stage_results.append(stage_result)

        if stage == "analyze":
            prior = (
                {
                    "finding": {
                        "finding": parsed["finding"],
                        "category": parsed.get("category", ""),
                    }
                }
                if parsed and isinstance(parsed.get("finding"), bool)
                else None
            )
        elif stage == "plan":
            prior = {"finding": prior["finding"], "plan": parsed} if parsed else None
        else:
            prior = {
                "finding": prior["finding"],
                "plan": prior["plan"],
                "implementation": parsed,
            } if parsed else None
        if not stage_result["ok"]:
            break

    for stage, model in zip(stage_names[len(stage_results) :], models[len(stage_results) :]):
        stage_results.append(
            {
                "stage": stage,
                "model": model,
                "ok": False,
                "skipped": True,
                "error": "previous pipeline stage failed",
            }
        )

    finding = next(
        (
            stage["output"].get("finding")
            for stage in stage_results
            if stage["stage"] == "analyze" and stage.get("output")
        ),
        None,
    )
    return {
        "case": case_name,
        "expected_finding": case["expected_finding"],
        "finding_correct": finding == case["expected_finding"]
        if isinstance(finding, bool)
        else None,
        "stages": stage_results,
        "complete": len(stage_results) == 3
        and all(stage["ok"] for stage in stage_results),
    }


def load_api_key(env_file: Path = Path(".env")) -> str:
    api_key = os.environ.get("CROWLLM_API_KEY")
    if api_key:
        return api_key
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "CROWLLM_API_KEY":
                api_key = value.strip().strip("\"'")
                if api_key:
                    return api_key
    raise SystemExit(
        "Set CROWLLM_API_KEY in the environment or add it to the ignored .env file."
    )


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil((percentile_value / 100) * len(ordered)) - 1)
    return ordered[min(index, len(ordered) - 1)]


def summarize(samples: list[dict[str, Any]], models: list[str]) -> dict[str, Any]:
    samples_by_model = {model: [] for model in models}
    for sample in samples:
        if sample["model"] in samples_by_model:
            samples_by_model[sample["model"]].append(sample)

    summaries: dict[str, Any] = {}
    for model, model_samples in samples_by_model.items():
        successes = [sample for sample in model_samples if sample["ok"]]
        latencies = [sample["latency_ms"] for sample in successes]
        p95_latency = percentile(latencies, 95)
        rates = [
            sample["completion_tokens_per_second_e2e"]
            for sample in successes
            if sample["completion_tokens_per_second_e2e"] is not None
        ]
        summaries[model] = {
            "attempts": len(model_samples),
            "successes": len(successes),
            "failures": len(model_samples) - len(successes),
            "latency_ms": {
                "median": round(statistics.median(latencies), 2) if latencies else None,
                "p95": round(p95_latency, 2) if p95_latency is not None else None,
            },
            "completion_tokens_per_second_e2e_median": round(statistics.median(rates), 2)
            if rates
            else None,
        }
    return summaries


def request_completion(
    model: str,
    prompt: str,
    endpoint: str,
    api_key: str,
    timeout: float,
    max_tokens: int = 32,
    stream: bool = False,
    json_mode: bool = False,
    on_chunk: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    payload_data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if json_mode:
        payload_data["response_format"] = {"type": "json_object"}
    payload = json.dumps(payload_data).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": "Bear" + "er " + api_key,
            "Content-Type": "application/json",
            "User-Agent": "LLM-bullshit-benchmark/0.1",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if stream:
                answer, usage, finish_reason = parse_sse_response(response, on_chunk)
                body = {}
                choice = {"finish_reason": finish_reason}
            else:
                response_body = response.read()
                body = json.loads(response_body)
        latency_ms = (time.perf_counter() - started) * 1000
        if stream:
            if not answer:
                raise ValueError("SSE response contained no completion text")
        else:
            if not isinstance(body, dict) or not body.get("choices"):
                raise ValueError("missing chat completion choices")
            choice = body["choices"][0]
            message = choice.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ValueError("missing chat completion content")
            answer = message["content"]
            usage = body.get("usage") or {}
        completion_tokens = usage.get("completion_tokens")
        tokens_per_second = (
            completion_tokens / (latency_ms / 1000)
            if isinstance(completion_tokens, (int, float)) and latency_ms > 0
            else None
        )
        return {
            "ok": True,
            "latency_ms": round(latency_ms, 2),
            "completion_tokens": completion_tokens,
            "completion_tokens_per_second_e2e": round(tokens_per_second, 2)
            if tokens_per_second is not None
            else None,
            "answer": answer,
            "finish_reason": choice.get("finish_reason"),
        }
    except urllib.error.HTTPError as error:
        detail = (
            error.read()
            .decode("utf-8", errors="replace")
            .replace(api_key, "[redacted]")
        )
        detail = " ".join(detail.split())[:300]
        return {
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": f"HTTP {error.code}" + (f": {detail}" if detail else ""),
        }
    except (urllib.error.URLError, TimeoutError) as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else "timeout"
        return {
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": f"connection error: {reason}",
        }
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        AttributeError,
        TypeError,
        ValueError,
        KeyError,
        IndexError,
    ) as error:
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        return {
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": f"invalid API response: {detail}",
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark selected chat models on speed or a synthetic code-review task."
    )
    parser.add_argument("models", nargs="+", help="Model IDs to compare")
    parser.add_argument(
        "--task",
        choices=("speed", "synthetic-review", "pipeline"),
        default="speed",
        help="Benchmark speed, review, or run the 3-model SSE pipeline (default: speed)",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Identical prompt sent to every model",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="Requests per model (default: 3)",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="Seconds between requests (default: 1)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-request timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed used to shuffle assignments (default: random; recorded in results)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Maximum response tokens per request (default: 4096)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmark-results.json"),
        help="JSON results path (default: benchmark-results.json)",
    )
    args = parser.parse_args()
    if args.task == "pipeline" and (
        len(args.models) != 3 or len(set(args.models)) != 3
    ):
        parser.error("--task pipeline requires exactly three distinct model IDs")
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if args.pause < 0:
        parser.error("--pause cannot be negative")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.max_tokens < 1:
        parser.error("--max-tokens must be at least 1")
    if not args.models or any(not model.strip() for model in args.models):
        parser.error("provide one or more non-empty model IDs")
    return args


def main() -> int:
    args = parse_args()
    api_key = load_api_key()

    models = list(dict.fromkeys(args.models))
    endpoint = f"{args.base_url.rstrip('/')}/chat/completions"
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**63)
    rng = random.Random(seed)

    if args.task == "pipeline":
        pipeline_runs = []
        total_runs = args.repetitions * len(REVIEW_CASES)
        run_number = 0

        def announce_stage(index: int, stage: str, model: str) -> None:
            print(
                f"\n[{run_number}/{total_runs} | stage {index}/3: {stage} | {model}]"
            )

        for round_number in range(1, args.repetitions + 1):
            round_cases = list(REVIEW_CASES.items())
            rng.shuffle(round_cases)
            for case_name, case in round_cases:
                run_number += 1
                run = run_pipeline_case(
                    case_name=case_name,
                    case=case,
                    models=models,
                    endpoint=endpoint,
                    api_key=api_key,
                    timeout=args.timeout,
                    max_tokens=args.max_tokens,
                    on_stage_start=announce_stage,
                )
                run["round"] = round_number
                pipeline_runs.append(run)
                print()
                for stage in run["stages"]:
                    if not stage.get("skipped"):
                        state = "ok" if stage["ok"] else "failed"
                        print(
                            f"  {stage['stage']} ({stage['model']}): {state}, "
                            f"{stage.get('request_attempts', 1)} request(s), "
                            f"{stage['streamed_characters']} streamed chars, "
                            f"{stage['latency_ms']:.0f} ms"
                        )
                state = "complete" if run["complete"] else "incomplete"
                correctness = run["finding_correct"]
                print(
                    f"Case {case_name}: {state}; "
                    f"first-stage finding correct={correctness}"
                )
                if run_number < total_runs and args.pause:
                    time.sleep(args.pause)

        role_summary = {}
        for stage_name in ("analyze", "plan", "implement"):
            stage_results = [
                stage
                for run in pipeline_runs
                for stage in run["stages"]
                if stage["stage"] == stage_name and not stage.get("skipped")
            ]
            successful = [stage for stage in stage_results if stage["ok"]]
            latencies = [stage["latency_ms"] for stage in successful]
            role_summary[stage_name] = {
                "model": models[("analyze", "plan", "implement").index(stage_name)],
                "attempts": len(stage_results),
                "requests": sum(stage.get("request_attempts", 1) for stage in stage_results),
                "successes": len(successful),
                "failures": len(stage_results) - len(successful),
                "median_latency_ms": round(statistics.median(latencies), 2)
                if latencies
                else None,
                "completion_tokens": sum(
                    stage["completion_tokens"] or 0
                    for stage in successful
                    if isinstance(stage.get("completion_tokens"), (int, float))
                ),
            }
        report = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "base_url": args.base_url,
            "task": args.task,
            "task_version": 1,
            "streaming": "SSE",
            "repetitions": args.repetitions,
            "pause_seconds": args.pause,
            "seed": seed,
            "max_tokens": args.max_tokens,
            "reasoning_effort": None,
            "response_format": "json_object",
            "models": models,
            "roles": role_summary,
            "summary": {
                "cases": len(pipeline_runs),
                "complete_runs": sum(run["complete"] for run in pipeline_runs),
                "correct_first_stage_findings": sum(
                    run["finding_correct"] is True for run in pipeline_runs
                ),
                "incorrect_first_stage_findings": sum(
                    run["finding_correct"] is False for run in pipeline_runs
                ),
                "unscored_first_stage_findings": sum(
                    run["finding_correct"] is None for run in pipeline_runs
                ),
            },
            "runs": pipeline_runs,
        }
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote clean pipeline results to {args.output}")
        return 0

    samples: list[dict[str, Any]] = []
    request_number = 0
    assignments = (
        [(case_name, case) for case_name, case in REVIEW_CASES.items()]
        if args.task == "synthetic-review"
        else [("speed", {"expected_finding": None, "code": args.prompt})]
    )

    for round_number in range(1, args.repetitions + 1):
        round_assignments = assignments.copy()
        rng.shuffle(round_assignments)
        for case_name, case in round_assignments:
            round_models = models.copy()
            rng.shuffle(round_models)
            for model in round_models:
                request_number += 1
                prompt = (
                    review_prompt(case["code"], case["context"])
                    if args.task == "synthetic-review"
                    else args.prompt
                )
                result = request_completion(
                    model=model,
                    prompt=prompt,
                    endpoint=endpoint,
                    api_key=api_key,
                    timeout=args.timeout,
                    max_tokens=args.max_tokens,
                    json_mode=args.task == "synthetic-review",
                )
                review = (
                    parse_review_answer(result["answer"])
                    if args.task == "synthetic-review" and result["ok"]
                    else None
                )
                sample = {
                    "round": round_number,
                    "case": case_name,
                    "model": model,
                    "expected_finding": case["expected_finding"],
                    "review": review,
                    **result,
                }
                samples.append(sample)
                status = (
                    f"{sample['latency_ms']:.0f} ms"
                    if sample["ok"]
                    else sample["error"]
                )
                if args.task == "synthetic-review" and result["ok"]:
                    status += (
                        " (scored)"
                        if review is not None
                        else f" (unscored; finish_reason={result.get('finish_reason')})"
                    )
                total = len(models) * args.repetitions * len(assignments)
                print(f"[{request_number}/{total}] {model} [{case_name}]: {status}")
                if request_number < total and args.pause:
                    time.sleep(args.pause)

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "task": args.task,
        "task_version": 1 if args.task == "synthetic-review" else None,
        "prompt": args.prompt if args.task == "speed" else None,
        "repetitions": args.repetitions,
        "pause_seconds": args.pause,
        "seed": seed,
        "max_tokens": args.max_tokens,
        "reasoning_effort": None,
        "response_format": "json_object"
        if args.task == "synthetic-review"
        else "text",
        "models": models,
        "summary": summarize(samples, models)
        if args.task == "speed"
        else summarize_reviews(samples, models),
        "performance": summarize(samples, models),
        "samples": samples,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote results to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
