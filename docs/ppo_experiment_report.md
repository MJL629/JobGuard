# PPO experiment report

The independent PPO design, reward formula and 1.5B-to-3B progression are specified in `experiments/rlhf_ppo/`.

## Compatibility failure retained

The first launch used TRL 0.12, whose installed PPO API required policy/reference/reward/value models and did not
support the planned explicit JobGuard reward step. It failed before training. The experiment switched to TRL
0.11.4's auditable `step(queries, responses, rewards)` API; `tyro` was added as its missing runtime dependency.

## Completed 64-episode smoke run

| Metric | Result |
|---|---:|
| Model | Qwen2.5-1.5B-Instruct + LoRA r=8 |
| Episodes / batches | 64 / 8 |
| Mean batch reward | 0.0874 |
| Reward range | 0.0080–0.1938 |
| Mean JSON success | 0.1406 |
| Last batch KL estimate | 0.2367 |
| Maximum absolute batch KL | 0.2787 |
| Duration | 247.72 s |
| Peak GPU memory | 10,794.74 MB |

The PPO infrastructure works end to end with TRL, PEFT and Accelerate, but the promotion gate failed. Reward and
JSON validity are unstable, responses often continue JD prose, and KL exceeded the 0.1 target. The 128-token
response cap also truncated some otherwise JSON-shaped outputs. The correct next iteration is SFT warm-start,
256-token responses, stronger format reward and held-out pre/post evaluation—not immediately scaling to 3B.
