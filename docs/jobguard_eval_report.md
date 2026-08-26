# JobGuard Eval Benchmark v1

## Scope

The fixed benchmark contains 500 unique job descriptions with deterministic seed `20260825` and a 350/75/75
train/validation/test split. The combined `benchmark.jsonl` is the fixed 500-row input for agent ablation.

## Provenance and label quality

- Gold: the existing JobGuard seed records, normalized without changing their human-authored fields.
- Silver: public `ryang2/linkedin-job-scrape` rows. Company, position, location and salary are source fields;
  skills, experience and education are deterministic regex/dictionary annotations and require human review before
  they are suitable as training gold labels.
- Duplicate JD text is removed by SHA-256. No model outputs are presented as manually verified ground truth.

## Metrics

`run_eval.py` reports JSON success rate, exact non-empty field accuracy, skill precision/recall/F1, coverage,
mean latency and total tokens. Exact matching is deliberately strict; semantic judge metrics can be added as a
separate metric without changing v1.

## Reproduction

```bash
cd backend
python scripts/build_eval_dataset.py --total 500 --seed 20260825
python scripts/run_eval.py --predictions path/to/predictions.jsonl
```

## Completed model comparison on fixed 75-row test split

| Model / prompt | JSON success | Field accuracy | Skill F1 |
|---|---:|---:|---:|
| Base Qwen2.5-7B / job_extract.v2 | 0.9733 | 0.2009 | 0.0557 |
| Base Qwen2.5-7B / v3 candidate | 0.9733 | 0.1842 | 0.1349 |
| LoRA SFT r=16 | **1.0000** | **0.3884** | 0.4990 |
| LoRA SFT r=32 | **1.0000** | 0.3662 | **0.5170** |
| DPO v2 on SFT r=32 | **1.0000** | 0.3729 | 0.5141 |

SFT provides the material task improvement: r=16 nearly doubles exact field accuracy over the Base v2 prompt,
while r=32 has the best skill F1. General-preference DPO is domain-neutral: it slightly improves scalar fields over
its r=32 starting point and slightly reduces skill F1. Because 439/500 benchmark labels are deterministic silver
labels and model prompts are not byte-identical across all training families, absolute numbers should be treated as
engineering comparison metrics, not a publication-grade estimate of human extraction accuracy.
