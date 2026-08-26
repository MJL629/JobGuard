# DPO v2 report

The upgraded experiment uses public UltraFeedback preference pairs for general alignment and retains a separate
JobGuard-domain evaluation. Required metrics are preference accuracy, reward margin, win rate and KL to the SFT
reference.

## Completed run

The real run used 1,000 UltraFeedback train pairs and 200 held-out test pairs, initialized from JobGuard LoRA
r=32. It ran 40 steps with beta 0.1 and learning rate 1e-5 on one RTX 4090.

| Metric | Result |
|---|---:|
| SFT preference accuracy | 0.580 |
| DPO preference accuracy | **0.590** |
| Mean chosen-minus-rejected log-prob margin | 0.4020 |
| Pairs whose margin improved vs SFT | 0.575 |
| Mean absolute held-out log-prob shift (KL proxy) | 0.0463 |
| Final DPO loss | 0.6672 |
| Duration | 54.46 s |
| Peak GPU memory | 15,505.77 MB |

DPO produced a modest +1 percentage-point held-out preference-accuracy gain. `kl_to_sft_estimate` is explicitly
a response log-prob shift proxy, not an exact token-distribution KL; the name is retained to match the planned
dashboard while the limitation prevents overclaiming. UltraFeedback is general assistant preference data, so a
separate JobGuard extraction generation test is required before deployment; that check is reported below.

## JobGuard fixed-test regression check

| Model | JSON success | Field accuracy | Skill F1 |
|---|---:|---:|---:|
| SFT r=32 | 1.0000 | 0.3662 | **0.5170** |
| DPO v2 | 1.0000 | **0.3729** | 0.5141 |

DPO slightly improved exact field accuracy (+0.0067) while slightly reducing skill F1 (-0.0029). This is a
near-neutral domain result rather than a broad extraction improvement. The general-preference gain did not cause
a material JobGuard regression, but it also does not justify replacing the task-specific SFT checkpoint alone.
