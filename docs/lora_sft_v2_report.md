# LoRA SFT v2 report

The data builder creates three faithful prompt views per training record (1,050 train) and one view for each
validation/test record (75/75). This is 1,200 examples but 500 unique JDs; both counts are reported.

## Completed equal-budget training run

| r | Trainable params | Final train loss | Validation loss | Duration (s) | Peak GPU MB |
|---:|---:|---:|---:|---:|---:|
| 4 | 1,261,568 | 1.107932 | 0.811057 | 29.99 | 18,376.87 |
| 8 | 2,523,136 | 0.991573 | 0.721283 | 30.73 | 18,396.56 |
| 16 | 5,046,272 | 0.870747 | 0.559714 | 29.54 | 18,435.93 |
| 32 | 10,092,544 | 0.783868 | **0.483496** | 30.73 | 18,514.68 |

All runs used 40 optimizer steps, gradient accumulation 4 and max length 512 on one RTX 4090. r=32 is best by
validation loss under this short equal-step budget. It is not yet declared best for production: fixed-test JSON,
field and skill metrics determine the production choice. The invalid pre-fix NaN run is documented separately and excluded.

## Fixed 75-JD generation test

| r | JSON success | Field accuracy | Skill precision | Skill recall | Skill F1 |
|---:|---:|---:|---:|---:|---:|
| 4 | 1.0000 | 0.3216 | 0.5396 | 0.5403 | 0.4366 |
| 8 | 0.9867 | 0.3180 | 0.4230 | 0.6141 | 0.3720 |
| 16 | 1.0000 | **0.3884** | 0.4742 | **0.7821** | 0.4990 |
| 32 | 1.0000 | 0.3662 | **0.5573** | 0.7242 | **0.5170** |

The loss winner is not the universal task winner. r=16 has the best exact field accuracy and skill recall; r=32
has the best skill F1 and precision. For JobGuard's structured extraction path, r=16 is the conservative default
if exact scalar fields have priority; r=32 is preferable when balanced skill extraction is primary.
