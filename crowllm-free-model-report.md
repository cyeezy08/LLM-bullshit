# CrowLLM Free Model Catalog Report

Snapshot: 2026-11-05. The live pricing endpoint reported build `main-20261105-b0d563v`.

## Summary

The public catalog marks 178 model IDs as enabled for the `free` group: 82 general OpenAI-style chat/completion entries and 96 task-specific entries (7 embedding, 5 reranking, 22 speech-to-text, and 62 text-to-speech). Separately, keyless `GET /v1/models` returned 221 IDs total. These are catalog counts, not a confirmation of the allowlist on your specific key.

CrowLLM describes its key as optionally scoped by model list, IP allowlist, spend cap, and expiry. The actual set a key can call therefore cannot be inferred from the public catalog. Do not send the key here. To inspect what the gateway returns for your key, run locally with the key already stored in an environment variable:

```sh
curl -sS https://crowllm.com/v1/models \
  -H "Authorization: Bearer $CROWLLM_API_KEY" | jq -r '.data[].id'
```

If the key is model-scoped, check its settings in your CrowLLM account as well. A model being listed publicly does not override a key-level restriction. The docs say the free shelf remains usable at a zero wallet balance; request-rate limits still depend on the account/plan.

## Suggested Task Routing

These are starting points based on the catalog names and endpoint types, not benchmark rankings. Test tool calls, structured output, context size, latency, and modality on your own prompts before assigning production work.

| Task | Starting selection | Notes |
| --- | --- | --- |
| General assistant | `crow/auto:free` | The catalog describes this as automatic routing to the best free model by latency and success rate. |
| Coding | `crow-code-limitless:free`, `north-mini-code:free`, `deepseek-v4.1-flash:free`, `qwen-3.8-27b:free` | The first two are explicitly code-named; treat the others as candidates and compare on your repo tasks. |
| Reasoning | `deepseek-r1-distill-qwen-32b:free`, `deepseek-v4-flash-0731-thinking:free`, `glm-4.7-thinking:free`, `glm-5.3-flash-thinking:free` | Thinking/reasoning-named candidates; useful as a separate task route, but verify latency and tool support. |
| Vision or multimodal | `gemma-4-31b-it:free`, `aya-vision-32b:free`, `command-a-vision:free`, `glm-4.6v-flash:free`, `nvidia/nemotron-3.5-super-vl-120b-a12b:free`, `openbmb/MiniCPM-V-4.7-35B-A3B:free`, `qwen3-8-omni-flash:free` | Names suggest visual/audio capabilities; confirm the individual model page and API behavior before relying on them. The pricing endpoint's generic `openai` flag alone does not establish modality support. |
| RAG embeddings | `embed-v5.0-fast:free`, `embed-v5.0-pro:free`, `embed-multilingual-v3.0:free` | Use the embedding endpoint, not chat completions. Match language coverage and dimensions to the index. |
| RAG reranking | `rerank-v4.0-fast:free`, `rerank-v4.0-pro:free`, `rerank-multilingual-v3.0:free` | Use the rerank endpoint after retrieval; validate ranking quality against representative queries. |
| Transcription | `stt-general`, `stt-general-multi`, `stt-precise` | Domain-specific IDs such as `stt-medical`, `stt-finance`, and `stt-meeting` are also in the free group. |
| Speech generation | Select a `tts-*` ID matching the needed voice/language | The catalog includes English, Spanish, French, German, Dutch, and Japanese names. |

For multiple task queues, keep a separate model ID per task and use `crow/auto:free` only where automatic routing is acceptable. The exact model ID matters: several free audio/embedding IDs do not carry a `:free` suffix.

## Integration Findings

The docs index lists 24 integration guides, grouped as coding agents (Codex CLI, OpenCode, Aider), editor agents (Cline, Roo Code, Kilo Code, Continue), chat clients (Open WebUI, LibreChat, LobeChat, AnythingLLM, Cherry Studio, Chatbox, NextChat), roleplay (SillyTavern), SDKs (OpenAI, Anthropic, LangChain, Vercel AI, OpenAI Agents, Google Gen AI), and automation/evals (Dify, n8n, Promptfoo).

The documented endpoint shape is:

- OpenAI-compatible clients: `https://crowllm.com/v1`
- Anthropic-shaped clients: `https://crowllm.com` (bare origin; the client appends `/v1/messages`)
- Gemini-native clients: `https://crowllm.com/v1beta`

Most integration guides configure a provider/base URL, API key, and model ID; some clients can populate the model picker from the gateway. Roo Code documents per-mode models, making it a natural fit for separate task routes. The model catalog is shared across integrations, but individual models may not support every API feature or endpoint.

**Documentation coverage note:** I reviewed the documentation index, the entries for all 24 integration guides, and the auth/catalog/API-reference descriptions. The site serves these pages as a client-rendered app; direct HTTP fetches returned the shell rather than the full guide prose, so I could not verify every guide's full setup steps from this environment.

## Complete Free Catalog

### General Chat and Completion (82)

`agnes-2.5-flash:free`, `agnes-3.0-flash:free`, `aya-expanse-32b:free`, `aya-vision-32b:free`, `beam-1-0:free`, `command-a-plus:free`, `command-a-translate:free`, `command-a-vision:free`, `command-r-plus:free`, `crow-code-limitless:free`, `crow-limitless:free`, `crow-uncensored:free`, `crow/auto:free`, `deepseek-r1-distill-qwen-32b:free`, `deepseek-v4-flash-0731-thinking:free`, `deepseek-v4-flash-0731:free`, `deepseek-v4-flash:free`, `deepseek-v4.1-flash:free`, `dots-3-note-preview:free`, `flint-v1.0:free`, `gemma-4-31b-it:free`, `gemma-sea-lion-v4-27b-it:free`, `glm-4-7-flash:free`, `glm-4.6-thinking:free`, `glm-4.6:free`, `glm-4.6v-flash-think:free`, `glm-4.6v-flash:free`, `glm-4.7-flash:free`, `glm-4.7-think-search:free`, `glm-4.7-think:free`, `glm-4.7-thinking:free`, `glm-4.7:free`, `glm-4v-think:free`, `glm-4v:free`, `glm-5.3-flash-thinking:free`, `glm-5.3-flash:free`, `glm-zero-preview:free`, `gpt-oss-120b:free`, `gpt-oss-20b:free`, `grok-4.7-fast:free`, `grok-4.7:free`, `jais-3-mova-36b-a4b:free`, `k2-horizon-375b-a23b:free`, `laguna-s-2-1:free`, `laguna-xs-2-1:free`, `ling-3.1-flash:free`, `liquid/lfm-2.5-2.6b-thinking:free`, `liquid/lfm-2.5-2.6b:free`, `llama-3.3-70b-instruct:free`, `longcat-2.5:free`, `MiniCPM-V-4.7-1B:free`, `MiniCPM5-2B:free`, `mimo-v2.6-flash:free`, `nemotron-3-5-super-vl:free`, `nemotron-3-super-120b-a12b:free`, `nemotron-3-ultra-550b-a55b:free`, `north-mini-code:free`, `nvidia/laguna-xs-2.1:free`, `nvidia/llama-3.2-11b-vision-instruct:free`, `nvidia/minimax-m3.1-flash:free`, `nvidia/mistral-large-4-1t-a52b:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3.5-bolt-e4b:free`, `nvidia/nemotron-3.5-super-vl-120b-a12b:free`, `openai/gpt-oss-20b:free`, `openai/gpt-oss-safeguard-20b:free`, `openbmb/MiniCPM-V-4.7-35B-A3B-thinking:free`, `openbmb/MiniCPM-V-4.7-35B-A3B:free`, `ornith-1.5-122b:free`, `qwen-3.5-397b-a17b:free`, `qwen-3.6-27b:free`, `qwen-3.8-27b:free`, `qwen3-30b-a3b-fp8:free`, `qwen3-8-omni-flash:free`, `qwen3.8-27b-uncensored:free`, `solar-mini4:free`, `tiny-aya-earth:free`, `tiny-aya-fire:free`, `tiny-aya-global:free`, `tiny-aya-water:free`, `typhoon-v2.5-30b-a3b-instruct`, `xing4.0-29b-a4b:free`.

### Embeddings (7)

`embed-english-light-v3.0:free`, `embed-english-v3.0:free`, `embed-multilingual-light-v3.0:free`, `embed-multilingual-v3.0:free`, `embed-v4.0:free`, `embed-v5.0-fast:free`, `embed-v5.0-pro:free`.

### Reranking (5)

`rerank-english-v3.0:free`, `rerank-multilingual-v3.0:free`, `rerank-v3.5:free`, `rerank-v4.0-fast:free`, `rerank-v4.0-pro:free`.

### Speech to Text (22)

`stt-atc`, `stt-automotive`, `stt-classic`, `stt-drivethru`, `stt-finance`, `stt-general`, `stt-general-lite`, `stt-general-multi`, `stt-general-multi-lite`, `stt-live`, `stt-live-multi`, `stt-medical`, `stt-medical-lite`, `stt-meeting`, `stt-open`, `stt-open-fast`, `stt-open-lite`, `stt-pharma`, `stt-phone`, `stt-precise`, `stt-video`, `stt-voicemail`.

### Text to Speech (62)

`tts-alexis-en`, `tts-bree-en`, `tts-brittany-en`, `tts-brooke-en`, `tts-bruce-en`, `tts-cliff-en`, `tts-cole-en`, `tts-conor-en`, `tts-donovan-en`, `tts-drew-en`, `tts-elise-en`, `tts-gemma-en`, `tts-haley-en`, `tts-hannah-en`, `tts-heather-en`, `tts-jack-en`, `tts-kai-en`, `tts-kelsey-en`, `tts-kit-en`, `tts-lite-agathe-fr`, `tts-lite-agustina-es`, `tts-lite-amalthea-en`, `tts-lite-andromeda-en`, `tts-lite-angus-en`, `tts-lite-antonia-es`, `tts-lite-apollo-en`, `tts-lite-aquila-es`, `tts-lite-arcas-en`, `tts-lite-aries-en`, `tts-lite-asteria-en`, `tts-lite-athena-en`, `tts-lite-atlas-en`, `tts-lite-aurelia-de`, `tts-lite-aurora-en`, `tts-lite-helios-en`, `tts-lite-minerva-en`, `tts-lite-neptune-en`, `tts-lite-nestor-es`, `tts-lite-odysseus-en`, `tts-lite-olivia-es`, `tts-lite-ophelia-en`, `tts-lite-orion-en`, `tts-lite-orpheus-en`, `tts-lite-pandora-en`, `tts-lite-perseus-en`, `tts-lite-phoebe-en`, `tts-lite-pluto-en`, `tts-lite-rhea-nl`, `tts-lite-sirio-es`, `tts-lite-stella-en`, `tts-lite-thalia-en`, `tts-lite-theia-en`, `tts-lite-uzume-ja`, `tts-lite-valentina-es`, `tts-lite-valerio-es`, `tts-lite-vesta-en`, `tts-lite-viktoria-de`, `tts-lite-zeus-en`, `tts-sienna-en`, `tts-tanner-en`, `tts-wade-en`, `tts-wes-en`.

## Sources

- [Integrations index](https://crowllm.com/docs/integrations)
- [Machine-readable docs index](https://crowllm.com/llms.txt)
- [Authentication docs](https://crowllm.com/docs/authentication)
- [API reference](https://crowllm.com/docs/api-reference)
- [Live model pricing and group catalog](https://crowllm.com/api/pricing)
- [Keyless model discovery](https://crowllm.com/v1/models)
- [Model catalog](https://crowllm.com/models)
- [Pricing and plan details](https://crowllm.com/pricing)