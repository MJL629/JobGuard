# Prompt A/B report

Prompt metadata is versioned under `backend/prompts/version/`; production entries remain immutable and candidates
have explicit evaluation status.

## job_extract A/B (75 fixed test JDs, Base Qwen2.5-7B)

| Version | JSON success | Field accuracy | Skill F1 | Mean latency ms | Tokens |
|---|---:|---:|---:|---:|---:|
| v2 | 0.9733 | **0.2009** | 0.0557 | 5104.39 | 69,678 |
| v3 candidate | 0.9733 | 0.1842 | **0.1349** | **4519.04** | **69,053** |

v3 held JSON validity constant, more than doubled skill F1 and reduced mean latency 11.5%, but exact scalar field
accuracy fell 0.0167. It is therefore not promoted globally. A task-weighted variant can prefer v3 for skill-heavy
extraction, while v2 remains the scalar-field baseline.

## job_classify A/B (61 fixed curated seed labels, Base Qwen2.5-7B)

| Version | Category accuracy | Subcategory accuracy | Exact accuracy | Mean latency ms | Tokens |
|---|---:|---:|---:|---:|---:|
| v1 | 0.6393 | 0.5902 | 0.4590 | 690.04 | 15,332 |
| v2 candidate | **0.8361** | **0.6557** | **0.6393** | **493.15** | 17,927 |

v2 improved category accuracy by 19.68 percentage points and exact accuracy by 18.03 points while reducing mean
latency by 28.5%. It passed the promotion gate and is now the runtime classification prompt (`job_classify.v2`).
The benchmark preserves all 61 curated rows and normalizes their existing Chinese categories into the production
enum; no model output was used to create the gold labels.

## job_match A/B (100 fixed deterministic-silver pairs, Base Qwen2.5-7B)

| Version | JSON success | Score MAE | Recommendation accuracy | NDCG@5 | Mean latency ms | Tokens |
|---|---:|---:|---:|---:|---:|---:|
| v1 | 1.0000 | 30.2018 | 0.2300 | **0.9372** | 6413.94 | **67,448** |
| v2 candidate | 1.0000 | **18.4228** | **0.4800** | 0.9308 | **5743.07** | 69,054 |

The fixed silver score is intentionally transparent: 55% explicit skill coverage, 25% preferred-role family and
20% preferred location. v2 is much better calibrated and doubles recommendation-bucket accuracy, but NDCG@5
regressed by 0.0064. It remains a shadow candidate until a human-labeled relevance set confirms the ranking result.
Silver metrics must not be presented as human preference accuracy.
