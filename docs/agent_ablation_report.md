# Agent ablation report

The experiment completed 500/500 predictions for both modes on local Qwen2.5-7B. Single Agent is one schema-bound
extraction call. The executable Multi-Agent candidate adds an independent reviewer/corrector call.

| Mode | JSON success | Field accuracy | Skill F1 | Mean latency ms | Tokens |
|---|---:|---:|---:|---:|---:|
| Single Agent | **0.9640** | **0.2232** | **0.1324** | **4,955.63** | **495,190** |
| Extractor + reviewer | 0.9060 | 0.1842 | 0.1098 | 10,687.86 | 1,085,509 |

The reviewer candidate is rejected: it reduced every quality metric, increased mean latency 2.16x and increased
tokens 2.19x. Local serving has no per-token API bill, so `cost_usd=0` means no external bill, not zero compute cost.

Repository inspection also found that the current LangGraph `job_parse`, `background_check` and `job_match` nodes
only update stage strings. They do not invoke the corresponding Agent classes, so placeholder graph output was not
misrepresented as a Multi-Agent baseline. The next architecture change should wire real nodes and add a selective
review gate triggered only by low confidence, rather than reviewing every request.
