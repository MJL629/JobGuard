# vLLM deep optimization report

The prior six-configuration matrix is preserved at `backend/data/eval/vllm_matrix_v2.json`. A new resumable OFAT
run completed 13 measured rows on Qwen2.5-7B-Instruct / RTX 4090. Raw JSON, CSV and logs are under
`experiments/vllm/`.

## Acceptance criteria

- All requested model-length, concurrency, max-sequence and prefix-cache levels are measured.
- Identical prompts, warm-up, request count and generation length are used per comparable sweep.
- TTFT, TPOT, throughput, P50/P95 latency, memory and failures are retained with raw logs.

## Concurrency sweep (8192 context, max_num_seqs=256, prefix on)

| Concurrency | Request/s | Output token/s | TTFT P95 ms | TPOT P95 ms | E2E P95 ms |
|---:|---:|---:|---:|---:|---:|
| 1 | 1.018 | 57.669 | 86.63 | 16.97 | 1093.87 |
| 4 | 3.500 | 204.758 | 61.82 | 18.59 | 1182.90 |
| 8 | 6.662 | 378.482 | 71.23 | 19.47 | 1271.12 |
| 16 | 12.600 | 716.615 | 101.66 | 21.21 | 1340.76 |
| 32 | **21.897** | **1256.656** | 197.14 | 23.61 | 1578.60 |

Concurrency 32 maximized throughput, while concurrency 16 is the more balanced operating point when tail latency
matters. From 16 to 32, request throughput rose 73.8%, while TTFT P95 rose 93.9%.

## Context length sweep (concurrency 16)

| max_model_len | Request/s | Output token/s | TTFT P95 ms | E2E P95 ms | GPU MB |
|---:|---:|---:|---:|---:|---:|
| 2048 | 12.521 | 732.860 | 179.10 | 1408.91 | 20,900 |
| 4096 | **12.876** | **778.572** | 134.97 | **1336.74** | 20,900 |
| 8192 | 12.600 | 716.615 | **101.66** | 1340.76 | 20,844 |
| 16384 | 12.547 | 734.370 | 175.51 | 1401.66 | 20,116 |

4096 had the best throughput in this short-output workload; 8192 had the lowest TTFT P95. Memory readings are
process allocations after startup and should not be interpreted as total KV capacity consumed by this tiny load.

## max_num_seqs sweep (8192 context, concurrency 16)

| max_num_seqs | Request/s | TTFT P95 ms | E2E P95 ms |
|---:|---:|---:|---:|
| 8 | 6.630 | 1302.23 | 2454.17 |
| 32 | 12.480 | 187.15 | 1421.62 |
| 64 | 12.540 | 176.55 | 1404.87 |
| 128 | 12.523 | 176.48 | 1405.35 |
| 256 | 12.600 | **101.66** | **1340.76** |

`max_num_seqs=8` throttled a concurrency-16 workload; 32 and above recovered throughput. The unusually favorable
baseline tail latency should be confirmed with more repetitions before treating 256 as categorically superior.

## Prefix cache

At concurrency 16, prefix cache on/off produced 716.615/728.209 output token/s and 101.66/169.23 ms TTFT P95.
Throughput was effectively similar with this small run, while cache-on showed lower tail TTFT. Because all requests
share a short prompt and each configuration was measured once, a dedicated long-prefix repeated-trial benchmark is
still needed for a causal cache conclusion.

## Dedicated long-prefix repeated trial

The follow-up used a 3,360-character shared prefix, concurrency 16, one warm-up, and three measured trials per
configuration.

| Prefix cache | Request/s | Output token/s | TTFT P95 ms | TPOT P95 ms | E2E P95 ms |
|---|---:|---:|---:|---:|---:|
| Off | 4.394 | 172.261 | 2704.133 | 102.330 | 4926.150 |
| On | **17.374** | **681.516** | **129.207** | **21.880** | **1008.113** |

With a genuinely repeated long prefix, caching delivered 3.96x request/output throughput and reduced TTFT P95 by
95.2%. This resolves the ambiguity in the short-prompt check: prefix caching should remain enabled for JobGuard
workloads with stable system instructions or repeated JD-analysis context.
