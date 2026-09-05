# JobGuard Agent Runtime 工程化升级说明

本轮改造目标不是增加页面功能，而是把 JobGuard 现有的 Agent 能力从“分散服务调用”升级为可解释、可检查、可测试的 Agent Runtime。核心对应面试中常被追问的几个点：Agent 链路如何设计、子 Agent 如何分工、上下文如何管理、工具如何治理、如何降低幻觉、如何避免 Agent 死循环。

## 1. 显式 Agent 主链路

新增 `backend/app/agents/runtime.py`，把 JobGuard 的运行时链路显式建模为：

```text
Supervisor
  → Planner
  → Context Builder
  → Domain Nodes / Tool Executor
  → Evidence Gate
  → Writer
  → Persistence
```

不同任务会展开为不同 DAG：

- 岗位推荐：`context_builder → parallel_retrievers → match_scorer → writer`
- 岗位分析：`context_builder → jd_parser / profile_reader / evidence_agent → evidence_gate → writer`
- 简历生成：`context_builder → profile_reader / target_job_reader → project_retriever → resume_writer`
- 画像构建：`context_builder → profile_agent → persistence`
- 学习建议：`context_builder → gap_inspector → resource_retriever → writer`

其中 `parallel_group` 字段明确哪些节点可以并行执行。例如岗位分析中的 JD 解析、画像读取、企业证据查询可以在依赖满足后并行执行；匹配评分和报告生成必须等待必要结果完成。

## 2. State Ownership：避免多 Agent 打架

新增统一 `STATE_OWNERS`：

| State 字段 | 所属节点 |
| --- | --- |
| `intent` | `supervisor` |
| `execution_plan` | `planner` |
| `user_profile` / `user_projects` | `profile_reader` |
| `job_info` | `jd_parser` |
| `retrieval_results` | `retriever` |
| `recommended_jobs` / `recommendation_breakdown` | `match_scorer` |
| `company_report` | `evidence_agent` |
| `generated_resume` / `generated_greeting` | `resume_writer` |

设计原则：

1. 每个节点只写自己拥有的字段。
2. API/service 层负责最终数据库副作用。
3. 写入画像、简历、历史记录等操作必须经过业务层确认。
4. 跨用户数据不允许进入当前运行态上下文。

这可以回答“子 Agent 如何管理上下文、如何防止互相覆盖”：JobGuard 不让每个 Agent 自己保存一份上下文，而是统一 State + 字段所有权 + service 层持久化。

## 3. Prompt Assembly：任务态提示词动态装配

新增 `AgentRuntime.build_prompt(task_type, context)`，根据任务类型动态组装：

- 基础系统规则
- 当前任务规则
- 可用工具范围
- 证据门禁策略
- 输出 Schema
- 被选中的上下文字段

例如 `analyze_job` 会自动启用证据策略：

```json
{
  "require_source_links": true,
  "allow_unverified_numbers": false,
  "on_missing_evidence": "unknown/no_evidence"
}
```

`generate_resume` 会注入“只能重组和改写已有经历，不新增不存在的项目、奖项或技能”的规则。这样可以避免所有任务共用一大段固定 Prompt，也方便面试中说明 system prompt 动态写入的实现方式。

## 4. Context Engineering：Write / Select / Compress / Isolate

本轮将上下文工程显式为四个动作：

### Write

节点中间结果结构化写入 State，例如：

- `jd_parser → job_info`
- `evidence_agent → company_report`
- `match_scorer → recommended_jobs`
- `resume_writer → generated_resume`

### Select

不同任务只选择必要上下文：

- 岗位推荐：画像摘要、技能、目标方向、期望城市、薪资范围
- 岗位分析：岗位文本、公司名、画像摘要、上一轮岗位上下文
- 简历生成：目标岗位、画像摘要、项目摘要、简历风格

无关历史、原始简历全文、其他任务日志不会默认进入 Prompt。

### Compress

长字符串限制为 1200 字符，列表最多保留 8 项，防止长上下文污染工具调用和模型输出。后续可以继续扩展为摘要模型或规则摘要。

### Isolate

上下文选择结果会声明：

- `user_scope_required = true`
- `cross_user_access_allowed = false`
- `raw_resume_text_allowed = false`
- `tool_scope = 当前任务允许工具`

这对应用户数据隔离和节点级工具隔离。

## 5. Agent Middleware Chain

新增运行时中间件说明：

| Middleware | 阶段 | 作用 |
| --- | --- | --- |
| `AuthContextMiddleware` | before | 注入当前 `user_id`，阻止无登录态访问用户数据 |
| `ContextSelectorMiddleware` | before | 选择最小必要上下文 |
| `ToolScopeMiddleware` | before | 节点级工具隔离 |
| `TimeoutAndStepGuardMiddleware` | around | 最大步数和工具超时 |
| `TraceMiddleware` | around | 记录节点、工具、耗时、来源数量、异常类型 |
| `EvidenceGateMiddleware` | after | 无来源风险字段返回 `unknown/no_evidence` |
| `PersistenceMiddleware` | after | 将确认后的结果落库 |

已有 `Planner/Executor` 已支持最大步数、工具超时和依赖拓扑并行执行；本轮新增的是统一 Runtime 蓝图和可检查策略。

## 6. 新增接口

新增：

```http
POST /api/agent/runtime/blueprint
```

请求：

```json
{
  "task_type": "analyze_job",
  "context": {
    "user_id": 1,
    "job_text": "广州 AI Agent 工程师，要求 Python、RAG、LangGraph。",
    "company_name": "广州文基智能科技有限公司"
  }
}
```

返回包含：

- `workflow`：DAG 节点、读写字段、依赖、工具、并行组
- `state_owners`：State 字段所有权
- `context_engineering`：Write/Select/Compress/Isolate
- `prompt_assembly`：动态 Prompt 规则、输出 Schema、证据策略
- `middleware_chain`：Agent 中间件链
- `tool_scope`：当前任务允许工具及执行策略

同时，生产 LangGraph 的 `classify_message` 返回结果新增 `runtime_blueprint` 和 `prompt_assembly`，证明图执行和 Runtime 策略已经打通。

## 7. 面试表达建议

可以这样总结：

> 我把 JobGuard 从普通 Agent 功能升级成一个可检查的 Agent Runtime：用 LangGraph 控制 Supervisor → Planner → Context Builder → Tool Executor → Evidence Gate → Writer 的确定性主链；用 State Ownership 防止多 Agent 互相覆盖；用 Prompt Assembly 动态注入任务规则、工具范围和输出 Schema；用 Context Engineering 实现 Write/Select/Compress/Isolate；再通过 Middleware Chain 统一处理用户态注入、工具隔离、超时、Trace、证据门禁和持久化。

这比单纯说“我用了 LangGraph / RAG / MCP”更能体现工程设计能力。
