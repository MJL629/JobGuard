# JobGuard AI experiment architecture

```text
JD / user request
      |
FastAPI + LangGraph ------ Trace recorder (node / LLM / tool / token / latency)
      |                                      |
Job agents -------- LLM Gateway -------- experiments/results registry
      |                 |
RAG / tools       route + cache + context
                        |
            +-----------+-----------+
            |                       |
     local Qwen/vLLM          DeepSeek / Zhipu
            |
   Base -> LoRA SFT -> DPO     PPO is independent
            |
 fixed 500-row Eval + agent/prompt/routing ablation
```

## Evaluation contract

All comparable runs share immutable benchmark IDs and write raw predictions before aggregate metrics. The v1
contract covers JSON success, exact field accuracy, skill precision/recall/F1, latency and tokens. Cost must come
from provider usage/billing, not an invented constant. Gold and silver labels are reported separately.

## Experiment lifecycle

Every experiment owns README, config, metrics and log artifacts. The append-only registry references historical
artifacts without moving or deleting them. Status distinguishes planned, running, completed and blocked runs.
Failed attempts are retained with root cause and are excluded from winner selection.

## Current engineering boundary

The repository has production-shaped Agent classes, Gateway, Trace and a LangGraph topology. Inspection on
2026-08-25 found several graph nodes that only change `current_stage` and do not invoke their corresponding Agent.
The 2026-08-25 ablation therefore used a separately executable extractor+reviewer candidate instead of placeholder
graph state. On 2026-08-26, `job_parse` and `job_match` were wired to their real Agent boundaries with async tests;
background check, resume generation and recommendation nodes remain explicit integration work rather than being
described as complete.
