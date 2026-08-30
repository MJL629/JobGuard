# JobGuard LangGraph 与 MCP 工具接入说明

## 当前生产结构

```mermaid
flowchart TD
    U[用户消息 + 会话类型] --> G[LangGraph: classify_intent]
    G --> PL[build_execution_plan]
    PL --> EG[apply_evidence_gate]
    EG -->|build_profile| P[画像对话流程]
    EG -->|analyze_job| J[岗位解析与风险分析]
    EG -->|recommend_jobs| R[数据库岗位画像匹配]
    EG -->|generate_resume| C[定向简历生成]
    J --> T[search_company_info]
    T --> E[(MySQL 企业证据与来源)]
    P --> M[(MySQL 画像/多简历/真实经历)]
    R --> M
    C --> M
    C --> F[事实保护与模板渲染]
```

生产 LangGraph 真实执行 `classify_intent → build_execution_plan → apply_evidence_gate` 三节点确定性主链。它在进程内惰性编译一次，不存在重复构图、空节点或声明后未调用的节点。分类器读取 `session_type`；计划节点为五类意图生成不同业务步骤；门禁节点禁止无来源数字，并声明画像约束和简历写入所需的人机确认。具体业务由 `app/api/chat.py` 显式执行，以控制数据库事务、SSE 事件持久化和失败回滚。

可通过登录后的 `GET /api/agent/graph` 查看运行时真实节点和边；该接口不会展示伪造的“理想图”。

## MCP 工具

项目已提供官方 Python MCP SDK 实现的 stdio 服务：

```powershell
cd E:\jobguard\jobguard\backend
.\.venv\Scripts\python.exe -m app.mcp_server
```

当前工具注册中心覆盖 13+ 个工具，其中部分安全工具通过 MCP 暴露：

- `search_company_info`：读取已落库企业证据、核验状态和来源链接。
- `search_job_database`：检索 MySQL 中有效岗位并保留来源。
- `analyze_job_requirements`：对数据库岗位做结构化要求分析。
- `get_user_profile_context`：读取当前登录用户结构化画像，不返回简历原文。
- `recommend_jobs_for_profile`：基于用户画像对岗位库做规则、关键词、语义融合推荐。
- `save_user_memory`：把用户明确确认的偏好、约束或目标写入长期记忆，执行前需要确认。
- `generate_targeted_resume`：根据画像与目标岗位生成定向简历并持久化，执行前需要确认。
- `recommend_learning_resources`：返回按技能筛选的可核验学习资源。
- `search_job_knowledge_base`：从 Chroma 岗位向量库召回语义相关 chunk。
- `sync_job_kb_from_database`：将 MySQL 岗位按语义切块同步到 Chroma，执行前需要确认。
- `build_company_verification_plan`：生成官方入口和人工核验步骤。
- `query_real_company_registry`：调用已配置的真实企业工商/风险数据接口，支持企查查开放平台和阿里云市场企业数据 API。
- `sync_beijing_official_jobs`：调用北京市公共数据开放平台岗位接口，返回真实岗位预览与计算机岗位过滤统计。
- `get_jobguard_tool_status`：返回适配器状态与真实性保护策略。

应用内 Agent 与 MCP 服务复用同一套工具函数，因此不是 Codex 临时替用户查一次，也不是把浏览器登录态塞入代码。缺少来源时必须返回 `unknown/no_evidence`，不能用模型记忆补充社保人数、仲裁数量或公司口碑。

登录后的 `POST /api/agent/plan-execute` 提供统一 Plan-and-Execute 调试入口：Planner 生成工具计划，Executor 统一通过 ToolRegistry 执行，执行过程写入 `agent_runs` 和 `tool_call_traces`。这个接口适合调试“用户目标 → 工具计划 → 每步执行结果”的完整链路。

## 真实外部接口 Adapter

项目新增真实外部数据适配层，所有 Adapter 都遵循同一个原则：配置了合法 API Key 才发起真实请求；未配置时返回 `not_configured`；上游失败时返回 `upstream_error`；不会用 mock 数据冒充真实查询结果。

环境变量：

- `QICHACHA_APP_KEY` / `QICHACHA_SECRET_KEY` / `QICHACHA_BASE_URL`：企查查开放平台接口配置，默认基地址为 `https://api.qichacha.com`。
- `ALIYUN_COMPANY_APPCODE` / `ALIYUN_COMPANY_QUERY_URL`：阿里云市场企业工商或风险类 API 配置，不同商品的 URL 不一致，因此由环境变量指定。
- `EXTERNAL_API_TIMEOUT_SECONDS`：外部接口超时保护。

企业核验链路中，`search_company_info` 会合并 MySQL 已落库证据、公开来源线索和已配置的真实外部 API 结果。第三方商业 API 返回的数据会按“第三方报告/可追溯来源”入库，不会冒充政府官方核验；只有白名单政府域名来源才标记为 official verified。

## Agent 执行保护

Planner-Executor 链路新增 `AGENT_MAX_STEPS` 和 `AGENT_TOOL_TIMEOUT_SECONDS` 配置。执行计划超过最大步数会被截断，单个工具调用超过超时时间会失败并进入 Agent 运行记录。这样可以回答“Agent 循环执行如何避免死循环”：系统不允许开放式无限 ReAct，而是采用 Plan-and-Execute 主流程，并用有限步数、工具超时、失败状态和 Trace 做工程约束。

## 两个政府平台的边界

- 北京市公共数据开放平台：岗位数据通过正式下载/导入流程进入 MySQL，来源 URL 与数据集标识保留；不在后台保存 userKey、Cookie 或验证码。
- 国家企业信用信息公示系统：当前为人工核验入口。其登录、验证码和访问控制不适合作为无人值守 Agent 工具；项目不会绕过验证码或复用个人浏览器 Cookie。

后续若接入新的合法公开数据源，应实现独立适配器，输出统一的 `facts + sources + missing_dimensions` 结构，再注册为 MCP 工具。
