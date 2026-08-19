# JobGuard AI-Infra Benchmark

该目录用于在不访问真实用户数据、不依赖真实云模型的情况下，对 JobGuard 的
Prompt 结构、岗位批量匹配调度和 LangGraph 外层耗时做可重复对比。

## 运行方式

在项目根目录执行：

```powershell
backend\.venv\Scripts\python.exe benchmarks\run_benchmarks.py --phase before
backend\.venv\Scripts\python.exe benchmarks\run_benchmarks.py --phase after
```

结果分别写入 `benchmarks/results/before` 和 `benchmarks/results/after`。

## 边界

- `benchmark_mode` 固定为 `mock`，不会调用云模型，也不会读取或保存 API Key。
- Mock 延迟只用于比较调度方式，不能解释为真实模型延迟。
- Prompt token 使用 `tiktoken/cl100k_base` 做稳定的结构性估算，不等同于智谱、
  DeepSeek 或未来 vLLM 模型的精确 tokenizer。
- Prompt Benchmark 只衡量 common prefix 结构，不声称测得 Prefix Cache Hit Rate。
- Workflow Benchmark 使用固定的规则命中场景，记录外层 E2E 与真实 graph trace；
  不伪造当前不存在的 node-level Before timing。
