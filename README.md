# 0day-LLM-bullshit

# GPT 6 SOL is shit btw

![LLM-bullshit project banner](https://substackcdn.com/image/fetch/$s_!zkGu!,f_auto,q_auto:good,fl_progressive:steep/https%3A%2F%2Fsubstack-post-media.s3.amazonaws.com%2Fpublic%2Fimages%2Fcebf6769-091f-44df-95bb-f6397dbd9a04_666x375.jpeg)

**Give multiple LLMs randomized security-research assignments. Verify the results.**

The name is the joke; the measurements should be real. LLM-bullshit is an
open-source benchmark for the big claims about AI agents finding security
issues. Different models get comparable, randomized assignments against
in-scope software. We check whether their findings are real, useful, and
handled responsibly instead of treating a confident claim or a big number as
proof.

## The idea

Build a scoped set of software targets and assign them to models through a
repeatable harness. Candidate sets might include deprecated or end-of-life
software, npm packages, and products with public security advisories. A target
is not permission: live testing only happens when the owner or a clear security
program explicitly authorizes it. Otherwise, use source code, synthetic
challenges, or isolated local labs.

For a suspected new issue, independently validate it, send a concise report
through the vendor's security contact, and track the response. The intended
disclosure goal is 90 days after notification, coordinated with the vendor and
adjusted when safety or circumstances require it; 90 days is a project target,
not a claim that every vendor follows the same policy.

## What we're trying to learn

- Which model and harness combinations produce independently verified findings?
- How often are results valid, in scope, reproducible, and novel rather than
  false positives or rediscoveries of known issues?
- Do reports give maintainers enough clear information to assess and fix an
  issue?
- How do models compare on time, cost, failures, and safe handling?
- How much of the hype survives independent verification?

## Current status

The harness has three modes:

- `speed` measures response latency for the same harmless prompt.
- `synthetic-review` gives each selected model the same two fixed, local code
  samples: one with a known path-validation bug and one safe control. It scores
  true/false positives, precision, recall, and accuracy. This is a toy
  code-review benchmark—not a live-repository scanner, exploit/PoC validator,
  or submission bot.
- `pipeline` streams three model roles over SSE in order: model 1 analyzes the
  synthetic sample, model 2 proposes a remediation plan from that finding, and
  model 3 returns corrected source. The harness turns that source into a
  normalized diff. It repeats the chain for both known-answer cases and writes
  a clean JSON report; failed or truncated stages stop that chain.

The repository also contains a snapshot of CrowLLM's free model catalog and
integration documentation: [CrowLLM free model report](./crowllm-free-model-report.md).

The catalog report is a point-in-time reference, not a guarantee of current
availability, model capability, or access for any particular API key.

## Running the model speed benchmark

Requires Python 3.10+ and uses only the standard library. For the easy local
setup, create a `.env` file in the repo root with your key:

```text
CROWLLM_API_KEY=your-temporary-key
```

`.env` is ignored by Git. Keep the key there locally; do not paste it into
`benchmark.py` or commit it. Then run:

```sh
python benchmark.py agnes-2.5-flash:free agnes-3.0-flash:free gemini-3-flash:free \
  --repetitions 3 \
  --pause 1 \
  --output benchmark-results.json
```

By default, the harness sends `Reply with exactly: benchmark-ok.` to
`https://crowllm.com/v1/chat/completions`. Choose model IDs available to your
key; its `GET /v1/models` list may differ from the public catalog. Results
include per-request latency and success or failure status.
Completion-token throughput is completion tokens divided by total request
latency, not pure generation speed, and is included only when the API reports
usage. The summary includes median and p95 latency. Sequential requests and the
pause reduce load; set `--pause` to match the provider's limits. Results vary
with network conditions, queueing, and provider load, so run multiple rounds
and compare the same settings.

Requests default to the CrowLLM Playground settings shown in the screenshot:
4096 maximum response tokens, no reasoning-effort override, and JSON-object
response format for review and pipeline tasks. Speed mode leaves response
format as text. Model/case ordering is randomized by default; the shuffle seed
is saved in results. Pass `--seed NUMBER` to reproduce an ordering or
`--max-tokens NUMBER` to change the response cap.

Run the built-in known-answer review benchmark with:

```sh
python benchmark.py agnes-2.5-flash:free agnes-3.0-flash:free gemini-3-flash:free \
  --task synthetic-review \
  --repetitions 3 \
  --pause 1 \
  --output synthetic-review-results.json
```

Each answer must be JSON with a boolean `finding`; malformed answers and API
failures are counted as unscored. The report includes the model's answer,
confusion-matrix metrics, and latency/token-throughput measurements for human
inspection. The cases are deliberately synthetic, fixed, and local; this does
not validate a real vulnerability or authorize testing a real product. The
output files are local benchmark data and must be reviewed before sharing.

Run the three-model streaming handoff with exactly three model IDs:

```sh
python benchmark.py MODEL_1 MODEL_2 MODEL_3 \
  --task pipeline \
  --repetitions 1 \
  --pause 1 \
  --output pipeline-results.json
```

The terminal shows each stage's live progress and streamed character count; the
JSON output stores clean parsed stage results, latency, tokens, completion
status, and whether stage 1 found the known issue.
`--repetitions 1` runs two pipelines (vulnerable case and safe control). The
safe-control label assumes the explicit threat model shown in the prompt; it is
not a claim that the snippet resists concurrent filesystem modification. An
empty SSE response is retried once.
The generated diff is only a suggested fix for the synthetic snippet. The harness
checks generated Python syntax but does not check undefined names or behavior,
apply patches, execute code, test real targets, or submit reports.

Check your account's model pricing and usage before running multiple rounds.
The `:free` suffix or public model catalog does not guarantee that calls are
free for your particular key.

All modes write JSON with the model IDs and measurements, but never the API
key. The default `benchmark-results.json` is ignored by Git; choose a different
output path to keep a report intentionally.

## Reading the result JSON

Reports are UTF-8 JSON, indented for readability, with one trailing newline.
Their top-level shape depends on `task`: `speed` and `synthetic-review` contain
`samples`; `pipeline` contains `runs`. All include the run settings, model IDs,
and a summary. `created_at` is UTC, `seed` records the assignment shuffle, and
`reasoning_effort` is `null` because the harness does not set that provider
option.

| Field | Meaning |
| --- | --- |
| `task` | `speed`, `synthetic-review`, or `pipeline`. |
| `task_version` | Version of the fixed benchmark definition; `null` for `speed`. |
| `summary` | For `speed`, per-model request counts and latency/token-rate stats. For `synthetic-review`, per-model confusion-matrix counts and scores. For `pipeline`, aggregate run and finding counts. |
| `performance` | Per-model latency and token-rate statistics for `speed` and `synthetic-review`; absent from `pipeline`. |
| `samples` | One request result per model, case, and round in the non-pipeline tasks. |
| `roles` | For `pipeline`, one aggregate record for each assigned stage/model. |
| `runs` | For `pipeline`, one record per case and repetition, including each stage result. |

### Complete report examples

The examples below show the full report layout with abbreviated, illustrative
measurements. Actual `samples` and `runs` arrays contain one entry per request
or case/repetition, respectively. Speed samples set `expected_finding` and
`review` to `null`; review samples populate them from the known-answer case and
the model's parsed answer. Malformed review JSON can still have `ok: true`, but
has `review: null` and is counted as unscored.

#### Speed

```json
{
  "created_at": "2026-11-07T19:44:35.322815+00:00",
  "base_url": "https://crowllm.com/v1",
  "task": "speed",
  "task_version": null,
  "prompt": "Reply with exactly: benchmark-ok.",
  "repetitions": 1,
  "pause_seconds": 1.0,
  "seed": 6875356658125196391,
  "max_tokens": 4096,
  "reasoning_effort": null,
  "response_format": "text",
  "models": ["example-model"],
  "summary": {
    "example-model": {
      "attempts": 1,
      "successes": 1,
      "failures": 0,
      "latency_ms": {"median": 928.19, "p95": 928.19},
      "completion_tokens_per_second_e2e_median": 20.47
    }
  },
  "performance": {
    "example-model": {
      "attempts": 1,
      "successes": 1,
      "failures": 0,
      "latency_ms": {"median": 928.19, "p95": 928.19},
      "completion_tokens_per_second_e2e_median": 20.47
    }
  },
  "samples": [
    {
      "round": 1,
      "case": "speed",
      "model": "example-model",
      "expected_finding": null,
      "review": null,
      "ok": true,
      "latency_ms": 928.19,
      "completion_tokens": 19,
      "completion_tokens_per_second_e2e": 20.47,
      "answer": "benchmark-ok.",
      "finish_reason": "stop"
    }
  ]
}
```

#### Synthetic review

```json
{
  "created_at": "2026-11-07T19:44:35.322815+00:00",
  "base_url": "https://crowllm.com/v1",
  "task": "synthetic-review",
  "task_version": 1,
  "prompt": null,
  "repetitions": 1,
  "pause_seconds": 1.0,
  "seed": 6875356658125196391,
  "max_tokens": 4096,
  "reasoning_effort": null,
  "response_format": "json_object",
  "models": ["example-model"],
  "summary": {
    "example-model": {
      "true_positive": 1,
      "false_negative": 0,
      "true_negative": 1,
      "false_positive": 0,
      "scored_cases": 2,
      "unscored_or_failed": 0,
      "accuracy": 1.0,
      "precision": 1.0,
      "recall": 1.0
    }
  },
  "performance": {
    "example-model": {
      "attempts": 2,
      "successes": 2,
      "failures": 0,
      "latency_ms": {"median": 928.19, "p95": 1000.0},
      "completion_tokens_per_second_e2e_median": 20.47
    }
  },
  "samples": [
    {
      "round": 1,
      "case": "vulnerable",
      "model": "example-model",
      "expected_finding": true,
      "review": {
        "finding": true,
        "category": "path_traversal",
        "reason": "The path is not restricted to the configured directory."
      },
      "ok": true,
      "latency_ms": 928.19,
      "completion_tokens": 19,
      "completion_tokens_per_second_e2e": 20.47,
      "answer": "{\"finding\": true, \"category\": \"path_traversal\"}",
      "finish_reason": "stop"
    },
    {
      "round": 1,
      "case": "safe_control",
      "model": "example-model",
      "expected_finding": false,
      "review": {
        "finding": false,
        "category": "",
        "reason": "The resolved path is checked against the configured directory."
      },
      "ok": true,
      "latency_ms": 1000.0,
      "completion_tokens": 20,
      "completion_tokens_per_second_e2e": 20.0,
      "answer": "{\"finding\": false, \"category\": \"\"}",
      "finish_reason": "stop"
    }
  ]
}
```

#### Pipeline

```json
{
  "created_at": "2026-11-07T19:44:35.322815+00:00",
  "base_url": "https://crowllm.com/v1",
  "task": "pipeline",
  "task_version": 1,
  "streaming": "SSE",
  "repetitions": 1,
  "pause_seconds": 1.0,
  "seed": 6875356658125196391,
  "max_tokens": 4096,
  "reasoning_effort": null,
  "response_format": "json_object",
  "models": ["example-analyzer", "example-planner", "example-implementer"],
  "roles": {
    "analyze": {
      "model": "example-analyzer",
      "attempts": 2,
      "requests": 2,
      "successes": 2,
      "failures": 0,
      "median_latency_ms": 900.0,
      "completion_tokens": 30
    },
    "plan": {
      "model": "example-planner",
      "attempts": 2,
      "requests": 2,
      "successes": 2,
      "failures": 0,
      "median_latency_ms": 800.0,
      "completion_tokens": 40
    },
    "implement": {
      "model": "example-implementer",
      "attempts": 2,
      "requests": 2,
      "successes": 2,
      "failures": 0,
      "median_latency_ms": 1000.0,
      "completion_tokens": 50
    }
  },
  "summary": {
    "cases": 2,
    "complete_runs": 2,
    "correct_first_stage_findings": 2,
    "incorrect_first_stage_findings": 0,
    "unscored_first_stage_findings": 0
  },
  "runs": [
    {
      "case": "vulnerable",
      "expected_finding": true,
      "finding_correct": true,
      "stages": [
        {
          "stage": "analyze",
          "model": "example-analyzer",
          "ok": true,
          "request_attempts": 1,
          "latency_ms": 900.0,
          "completion_tokens": 15,
          "streamed_characters": 45,
          "finish_reason": "stop",
          "output": {"finding": true, "category": "path_traversal"}
        },
        {
          "stage": "plan",
          "model": "example-planner",
          "ok": true,
          "request_attempts": 1,
          "latency_ms": 800.0,
          "completion_tokens": 20,
          "streamed_characters": 100,
          "finish_reason": "stop",
          "output": {
            "action": "Validate the resolved path",
            "constraints": ["Reject paths outside the root"],
            "expected_behavior": "Only read files within the root."
          }
        },
        {
          "stage": "implement",
          "model": "example-implementer",
          "ok": true,
          "request_attempts": 1,
          "latency_ms": 1000.0,
          "completion_tokens": 25,
          "streamed_characters": 200,
          "finish_reason": "stop",
          "output": {
            "fixed_code": "def read_report(root, filename):\n    ...\n",
            "explanation": "Check the resolved path stays within the root.",
            "syntax_valid": true,
            "patch": "--- a/sample.py\n+++ b/sample.py\n"
          }
        }
      ],
      "complete": true,
      "round": 1
    },
    {
      "case": "safe_control",
      "expected_finding": false,
      "finding_correct": true,
      "stages": [
        {
          "stage": "analyze",
          "model": "example-analyzer",
          "ok": true,
          "request_attempts": 1,
          "latency_ms": 900.0,
          "completion_tokens": 15,
          "streamed_characters": 45,
          "finish_reason": "stop",
          "output": {"finding": false, "category": ""}
        },
        {
          "stage": "plan",
          "model": "example-planner",
          "ok": true,
          "request_attempts": 1,
          "latency_ms": 800.0,
          "completion_tokens": 20,
          "streamed_characters": 50,
          "finish_reason": "stop",
          "output": {
            "action": "No remediation required",
            "constraints": [],
            "expected_behavior": "Keep the existing path validation."
          }
        },
        {
          "stage": "implement",
          "model": "example-implementer",
          "ok": true,
          "request_attempts": 1,
          "latency_ms": 1000.0,
          "completion_tokens": 25,
          "streamed_characters": 100,
          "finish_reason": "stop",
          "output": {
            "fixed_code": "def read_report(root, filename):\n    ...\n",
            "explanation": "The existing validation is sufficient for this case.",
            "syntax_valid": true,
            "patch": ""
          }
        }
      ],
      "complete": true,
      "round": 1
    }
  ]
}
```

In the speed summary, request counts describe API calls, and latency statistics
use successful requests only. `completion_tokens_per_second_e2e` divides
reported completion tokens by full request latency; it is not pure generation
speed. In review summaries, scores use successfully parsed answers only;
`null` precision or recall means its denominator is zero. Pipeline role
`attempts` count non-skipped stages, while `requests` include retries.
`summary.complete_runs` counts runs where all stages succeeded. Finding
correctness is scored independently, so a run can have a correct stage-1
finding and still be incomplete. Pipeline `fixed_code` and `patch` are model
suggestions; the code is only syntax-checked, not applied or behavior-tested.

## Roadmap

1. Add more small, known-answer local review cases, including safe controls.
2. Benchmark answer quality and cost alongside speed, keeping model order and
   task assignment reproducible.
3. Keep any future real-target work explicitly authorized and human-reviewed;
   never auto-test arbitrary repositories or automatically submit unverified
   findings.
4. Establish a responsible reporting and disclosure-tracking process, with a
   90-day target and a way to coordinate exceptions.
5. Publish reproducible benchmark results without exposing unpatched
   vulnerabilities or confidential vendor communications.

## Ground rules

- Use only models and endpoints you are authorized to access; follow their
  terms and rate limits.
- Test live systems only with explicit authorization and within its scope.
  Never point experiments at arbitrary public targets.
- Do not publish credentials, private data, or actionable details about an
  unpatched vulnerability.
- Independently verify findings and report them responsibly; a model's claim is
  not evidence by itself.
- Record model, harness, prompt, target scope, and verification method so the
  benchmark is reproducible.

## Contributing

Good contributions include scoped targets with a documented authorization
basis, reproducible benchmark tasks, transparent scoring criteria, responsible
disclosure process improvements, and safe local exercises. Never submit
unpatched vulnerability details or private reports as public benchmark data.

## License
No one lol
