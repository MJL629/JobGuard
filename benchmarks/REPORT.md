# JobGuard AI Infra Optimization Report

生成日期：2026-08-19
基线提交：`b79ca6ca76f75809514ef0b3de5c27cb4c636fcd`
Python：3.11.9 / Windows

## 1. 结论与证据边界

本阶段完成的是 **vLLM / OpenAI-compatible 接入准备、稳定 Prompt 前缀、受控并发和轻量 LLM 观测**，没有安装 vLLM、下载模型或连接 GPU。

本报告中的耗时来自固定的 50ms 确定性 Mock LLM，只用于验证调度、并发上限和失败隔离；它不是任何真实模型的吞吐或时延。Prompt token 使用 `tiktoken/cl100k_base` 作为结构代理，只能说明前缀更稳定，不能证明 vLLM Prefix Cache 已命中。真实 TTFT、tokens/s、KV cache 命中率和 GPU 利用率留待下一阶段在同一套接口上测量。

原始结果：

- `benchmarks/results/before/`
- `benchmarks/results/after/`

## 2. A. 修改文件

### 生产代码

| 文件 | 修改原因 |
|---|---|
| `backend/app/config.py` | 新增可选 vLLM 配置与 `JOB_MATCH_LLM_CONCURRENCY`（默认 4，范围 1-64）。 |
| `backend/.env.example` | 记录安全的 vLLM 示例配置；不包含真实服务器地址或密钥。 |
| `backend/app/llm/gateway.py` | 增加 `vllm_local` OpenAI-compatible Provider；增加 request_id、caller、E2E、TTFT、usage、成功/错误观测。 |
| `backend/app/monitoring.py` | 扩展脱敏 LLM 调用记录，同时兼容旧 `tokens/duration_ms` 调用方式。 |
| `backend/app/agents/orchestrator.py` | 意图固定规则放 system，用户消息和会话类型放 user。 |
| `backend/app/agents/profile_agent.py` | 简历解析、画像对话、画像增量抽取、经历抽取拆分固定规则与动态资料。 |
| `backend/app/agents/job_parser.py` | 岗位结构化抽取和分类拆分固定 Schema 与动态 JD。 |
| `backend/app/agents/background_check.py` | 风险评估、报告生成拆分固定规则与动态证据/画像。 |
| `backend/app/agents/job_matcher.py` | 匹配规则固定化；写死并发 5 改为配置化默认 4；单项异常显式降级并保留岗位映射。 |
| `backend/app/agents/resume_generator.py` | 项目选择/改写、自评、组装、事实核查、修正等实际 LLM Prompt 拆分。 |

### 测试与基准

| 文件/目录 | 用途 |
|---|---|
| `backend/tests/test_llm_gateway.py` | vLLM 可选配置、usage、错误、流式 TTFT、指标故障隔离。 |
| `backend/tests/test_job_matcher_agent.py` | 并发上限、结果数量/映射、失败降级。 |
| `backend/tests/test_prompt_prefix_structure.py` | 六个核心 Agent 的固定 system prompt 不含动态占位符。 |
| `benchmarks/*.py` | 可复现的 JobMatcher、Prompt 前缀和生产 LangGraph 路由基准。 |
| `benchmarks/results/before/` | 修改前原始 JSON。 |
| `benchmarks/results/after/` | 修改后原始 JSON及 1/2/4/8 并发矩阵。 |

## 3. B. 架构变化

```text
LangGraph Agent
      │  messages + optional metadata(agent_name)
      ▼
  LLMGateway
      │  Provider Abstraction + privacy-safe metrics
 ┌────┼──────────┬──────────────┐
 ▼    ▼          ▼              ▼
Zhipu DeepSeek SiliconFlow  vLLM Local
                            (OpenAI-compatible,
                             optional/disabled by default)
```

切换本地模型只需配置：

```text
VLLM_BASE_URL=http://127.0.0.1:8000/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=<served-model-name>
```

`VLLM_MODEL` 为空时 `vllm_local` 不创建客户端，也不改变智谱、DeepSeek 或 SiliconFlow 的现有行为。

每次 chat 调用可记录：`request_id`、可选 `agent`、provider/model、stream、E2E、可可靠获得时的 TTFT、Provider usage、成功状态和错误类型。不会记录完整 Prompt、简历、画像、API Key 或 metadata 正文；记录失败也不会影响模型调用。

## 4. C. Prefix Cache Ready

### 调整前

多个 Prompt 将固定角色、规则、输出 Schema 与动态画像/JD/RAG 内容共同 format 到 user prompt。即使已有短 system message，跨请求可复用的公共前缀仍很短。

### 调整后

| Agent（代表 Prompt） | Before 公共前缀 token | After 公共前缀 token | 变化 |
|---|---:|---:|---:|
| orchestrator | 468 | 500 | 固定规则进入 system；动态输入缩至 user 尾部 |
| profile_agent | 74 | 489 | 简历 Schema/规则固定，简历正文动态 |
| job_parser | 74 | 574 | 岗位 Schema/分类规则固定，JD 动态 |
| background_check | 77 | 922 | 风险维度/JSON Schema 固定，证据和画像动态 |
| job_matcher | 43 | 266 | 五维评分和输出 Schema 固定，候选人/岗位动态 |
| resume_generator | 37 | 200 | 改写规则/Schema 固定，项目和岗位动态 |

六组 system prompt 在三个动态样本中 token 数完全一致，消息角色均为 `system → user`。

### 有意未调整

- `background_check.JD_ANALYSIS_PROMPT`：当前生产 `_analyze_jd` 走可复现本地规则，该 Prompt 没有实际 LLM 调用，未为缓存而改业务路径。
- `resume_generator.GREETING_PROMPT`：当前问候语使用真实资料的本地生成路径，不是实际 LLM 调用。
- 没有把所有 Agent 或所有 Tool 合成一个超大 Prompt；Agent 边界、Schema 和业务判断保持不变。

### 仍待真实 vLLM 验证

公共前缀增长只说明 **prefix-cache-ready**。真正的 cache hit、KV block 复用、显存占用变化必须在安装 vLLM 并指定实际 tokenizer/model 后通过服务端指标验证。

## 5. D. 并发优化

真实修改前并不是完全串行，而是代码内写死：

```text
Job1 ─┐
Job2 ─┤
Job3 ─┼─ hard-coded max concurrency = 5
Job4 ─┤
Job5 ─┘
```

修改后：

```text
jobs → asyncio.gather → Semaphore(JOB_MATCH_LLM_CONCURRENCY) → match_single
                                default = 4
```

- 默认最大并发：4（对云 API 更保守）。
- 支持实验值：1 / 2 / 4 / 8。
- 仍按 `overall_score` 降序返回；每条结果保留 `job.id`，可恢复原岗位对应关系。
- 单任务出现未捕获异常时，生成 `degraded=true`、score=0 的对应结果，批次不会崩溃也不会丢条目。

### Mock 并发结果

| 岗位数 | 并发 | 观测最大并发 | E2E ms |
|---:|---:|---:|---:|
| 5 | 1 | 1 | 283.698 |
| 5 | 2 | 2 | 181.033 |
| 5 | 4 | 4 | 116.308 |
| 5 | 8 | 5（任务仅 5 个） | 52.615 |
| 10 | 1 | 1 | 562.546 |
| 10 | 2 | 2 | 269.528 |
| 10 | 4 | 4 | 167.419 |
| 10 | 8 | 8 | 116.398 |

默认 Before/After 对比：

| 场景 | Before | After | 解释 |
|---|---:|---:|---|
| 5 岗位 E2E | 51.552ms（并发 5） | 107.189ms（并发 4） | 默认限流更保守，纯 Mock 下多一个调度波次 |
| 10 岗位 E2E | 109.311ms（并发 5） | 167.766ms（并发 4） | 同上；不是性能回退缺陷，而是默认安全策略变化 |
| 注入 1 个失败 | 返回 4/5 | 返回 5/5 | After 保留失败岗位并显式降级 |

After 失败场景的降级项按 score=0 排在末尾，因此完整返回 ID 为 `[1,2,4,5,3]`。基准中的 `successful_result_order_correct=false` 是旧断言将“完整结果列表”等同于“仅成功列表”造成的标志；岗位映射有效且成功项顺序仍正确。

## 6. Workflow 基准

固定场景：`请推荐适合我的岗位`，会话类型 `profile_building`，20 次。

| 指标 | Before | After |
|---|---:|---:|
| 成功/失败 | 20/0 | 20/0 |
| 每次图节点数 | 3 | 3 |
| 图轨迹 | classify → plan → evidence gate | 相同 |
| LLM / Tool 调用 | 0 / 0 | 0 / 0 |
| 平均 E2E | 5.214ms | 4.503ms |

该意图由现有确定性规则命中，因此不应调用 LLM。两次微小时延差异属于本机抖动，不作为优化收益。

## 7. E. 测试结果

实际执行：

```text
专项测试：10 passed
完整 backend pytest：133 passed, 0 failed（23.79s）
compileall：通过
```

覆盖范围包括 LLMGateway、配置、Agent、生产 LangGraph、JobMatcher、Prompt 结构、流式 TTFT 和原有全量回归。没有删除或弱化原有测试。

## 8. 下一阶段真实 Serving Benchmark

在实验室 GPU 可用后保持本阶段代码不变，按以下顺序验证：

1. 启动 vLLM OpenAI-compatible server，设置真实 `VLLM_MODEL`。
2. 固定模型、tokenizer、sampling 参数、输入数据、并发和预热次数。
3. 分别关闭/开启 Automatic Prefix Caching，采集 TTFT、E2E、tokens/s、cache hit 与 GPU 指标。
4. 用并发 1/2/4/8 重跑 JobMatcher，比较吞吐、P50/P95/P99、错误率和限流行为。
5. 按 `agent` 和 `request_id` 将 LangGraph 节点耗时归因到具体 LLM 调用。
6. 真实实验数据与本报告 Mock 数据分栏保存，避免将调度代理结果误写成模型性能。
