# LLM routing report

The current routing policy sends short deterministic tasks to local vLLM and complex reasoning/risk assessment
to DeepSeek. `experiments/llm_routing/run_routing.py` compares DeepSeek-all with local routing on all 500 identical
extraction IDs. It checkpoints every 50 rows, so a provider interruption does not discard completed paid calls.

The remote baseline uses `deepseek-v4-flash` in non-thinking JSON mode. The model name was updated from the legacy
`deepseek-chat` alias after checking the current official API documentation. The quality gate permits at most a
0.01 field-accuracy regression. A failed gate is reported honestly; cost savings alone do not promote the route.

Cost is calculated from API-returned usage using the dated experiment snapshot (USD per one million tokens):
cache-hit input 0.0028, cache-miss input 0.14 and output 0.28. This is an estimate, not an invoice. Local provider API
cost is zero, but the report explicitly excludes GPU rental because it must be joined from the infrastructure bill.

Status on 2026-08-26: runner and local vLLM are validated; the server is waiting for a user-managed
`DEEPSEEK_API_KEY` in `backend/.env`. No key is committed and no mock baseline is substituted.
