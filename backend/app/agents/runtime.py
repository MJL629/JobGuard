"""Agent Runtime primitives for interview-grade, production-facing orchestration.

This module does not replace the existing domain services.  It makes the
implicit engineering design explicit: runtime DAGs, prompt assembly, context
selection, middleware policies and state ownership can be inspected, tested and
documented from one place.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.agents.tool_registry import ToolRegistry, tool_registry

TaskType = Literal[
    "build_profile",
    "recommend_jobs",
    "analyze_job",
    "generate_resume",
    "career_advice",
]


STATE_OWNERS: dict[str, str] = {
    "intent": "supervisor",
    "execution_plan": "planner",
    "evidence_policy": "evidence_gate",
    "user_profile": "profile_reader",
    "user_projects": "profile_reader",
    "job_info": "jd_parser",
    "retrieval_results": "retriever",
    "recommended_jobs": "match_scorer",
    "recommendation_breakdown": "match_scorer",
    "company_report": "evidence_agent",
    "match_score": "match_scorer",
    "generated_resume": "resume_writer",
    "generated_greeting": "resume_writer",
}


@dataclass(frozen=True)
class RuntimeNode:
    """A visible Agent runtime node and its safety contract."""

    name: str
    role: str
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    parallel_group: str | None = None
    prompt_template: str | None = None
    evidence_required: bool = False


@dataclass(frozen=True)
class PromptAssembly:
    """Prompt pieces selected for a task."""

    task_type: TaskType
    system_rules: list[str]
    context_keys: list[str]
    allowed_tools: list[str]
    output_schema: dict[str, Any]
    evidence_policy: dict[str, Any]
    prompt_preview: str


@dataclass(frozen=True)
class ContextSelection:
    """Context selected for one task before calling a model."""

    task_type: TaskType
    selected: dict[str, Any]
    omitted_keys: list[str]
    compression: dict[str, Any]
    isolation: dict[str, Any]
    fingerprint: str


@dataclass(frozen=True)
class MiddlewarePolicy:
    """One middleware in the Agent runtime chain."""

    name: str
    stage: Literal["before", "around", "after"]
    responsibility: str
    failure_mode: str


class AgentRuntime:
    """Central runtime description, context selector and prompt builder."""

    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or tool_registry
        self.middlewares: tuple[MiddlewarePolicy, ...] = (
            MiddlewarePolicy(
                name="AuthContextMiddleware",
                stage="before",
                responsibility="为工具调用注入当前 user_id，并阻止无登录态访问用户画像、简历和历史记录。",
                failure_mode="missing_user_context",
            ),
            MiddlewarePolicy(
                name="ContextSelectorMiddleware",
                stage="before",
                responsibility="按任务选择最小必要上下文，避免把无关历史、原始简历或其他用户数据塞入 Prompt。",
                failure_mode="context_not_available",
            ),
            MiddlewarePolicy(
                name="ToolScopeMiddleware",
                stage="before",
                responsibility="节点级工具隔离：每个节点只暴露本任务允许的工具，降低长上下文下工具误调用。",
                failure_mode="tool_not_allowed",
            ),
            MiddlewarePolicy(
                name="TimeoutAndStepGuardMiddleware",
                stage="around",
                responsibility="统一执行最大步数和工具超时，避免开放式 Agent 循环或外部接口卡死。",
                failure_mode="timeout_or_step_limit",
            ),
            MiddlewarePolicy(
                name="TraceMiddleware",
                stage="around",
                responsibility="记录节点、工具、耗时、来源数量、异常类型和脱敏参数摘要。",
                failure_mode="trace_write_failed_non_blocking",
            ),
            MiddlewarePolicy(
                name="EvidenceGateMiddleware",
                stage="after",
                responsibility="企业风险等事实字段必须绑定来源；无来源字段强制 unknown/no_evidence。",
                failure_mode="evidence_missing_mark_unknown",
            ),
            MiddlewarePolicy(
                name="PersistenceMiddleware",
                stage="after",
                responsibility="把会话、画像、岗位分析和简历生成结果写入数据库，写操作由业务层确认。",
                failure_mode="db_write_failed",
            ),
        )

    def workflow(self, task_type: TaskType) -> list[RuntimeNode]:
        """Return the visible DAG for a JobGuard task."""
        common_start = [
            RuntimeNode(
                name="supervisor",
                role="识别用户意图并选择业务子图",
                reads=("messages", "session_type"),
                writes=("intent",),
                prompt_template="supervisor_intent",
            ),
            RuntimeNode(
                name="planner",
                role="把意图转成确定性执行计划",
                reads=("intent",),
                writes=("execution_plan",),
                depends_on=("supervisor",),
                prompt_template="planner",
            ),
            RuntimeNode(
                name="context_builder",
                role="按任务装配画像、岗位、历史摘要和 RAG 片段",
                reads=("user_id", "session_id", "intent"),
                writes=("runtime_context",),
                depends_on=("planner",),
            ),
        ]

        branches: dict[TaskType, list[RuntimeNode]] = {
            "build_profile": [
                RuntimeNode(
                    name="profile_agent",
                    role="从对话或简历中抽取画像证据，并输出待确认约束",
                    reads=("messages", "runtime_context"),
                    writes=("user_profile", "user_projects"),
                    tools=("get_user_profile_context", "save_user_memory"),
                    depends_on=("context_builder",),
                    prompt_template="profile_update",
                ),
                RuntimeNode(
                    name="persistence",
                    role="保存确认后的画像与长期记忆",
                    reads=("user_profile",),
                    writes=("profile_records",),
                    tools=("save_user_memory",),
                    depends_on=("profile_agent",),
                ),
            ],
            "recommend_jobs": [
                RuntimeNode(
                    name="parallel_retrievers",
                    role="并行执行规则召回、关键词召回和语义召回",
                    reads=("user_profile", "runtime_context"),
                    writes=("retrieval_results",),
                    tools=("recommend_jobs_for_profile", "search_job_database", "search_job_knowledge_base"),
                    depends_on=("context_builder",),
                    parallel_group="retrieval",
                    prompt_template="job_recommendation",
                ),
                RuntimeNode(
                    name="match_scorer",
                    role="融合规则/关键词/语义分并生成可解释排序",
                    reads=("retrieval_results", "user_profile"),
                    writes=("recommended_jobs", "recommendation_breakdown"),
                    depends_on=("parallel_retrievers",),
                ),
                RuntimeNode(
                    name="writer",
                    role="输出中文推荐理由和风险提示",
                    reads=("recommended_jobs", "recommendation_breakdown"),
                    writes=("messages",),
                    depends_on=("match_scorer",),
                    prompt_template="recommendation_writer",
                ),
            ],
            "analyze_job": [
                RuntimeNode(
                    name="jd_parser",
                    role="解析岗位职责、要求、薪资、地点和风险关键词",
                    reads=("job_raw_input", "runtime_context"),
                    writes=("job_info",),
                    tools=("analyze_job_requirements",),
                    depends_on=("context_builder",),
                    parallel_group="analysis_prefetch",
                    prompt_template="jd_parse",
                ),
                RuntimeNode(
                    name="profile_reader",
                    role="读取当前用户画像和硬约束",
                    reads=("user_id",),
                    writes=("user_profile", "user_projects"),
                    tools=("get_user_profile_context",),
                    depends_on=("context_builder",),
                    parallel_group="analysis_prefetch",
                ),
                RuntimeNode(
                    name="evidence_agent",
                    role="查询企业证据并标记来源/缺失字段",
                    reads=("job_info", "runtime_context"),
                    writes=("company_report",),
                    tools=("search_company_info", "query_real_company_registry", "build_company_verification_plan"),
                    depends_on=("context_builder",),
                    parallel_group="analysis_prefetch",
                    evidence_required=True,
                ),
                RuntimeNode(
                    name="evidence_gate",
                    role="阻止无来源事实进入最终结论",
                    reads=("company_report",),
                    writes=("evidence_policy",),
                    depends_on=("jd_parser", "evidence_agent"),
                    evidence_required=True,
                ),
                RuntimeNode(
                    name="writer",
                    role="生成岗位分析报告并保存历史",
                    reads=("job_info", "user_profile", "company_report", "evidence_policy"),
                    writes=("messages", "job_analysis_record"),
                    depends_on=("profile_reader", "evidence_gate"),
                    prompt_template="analysis_writer",
                ),
            ],
            "generate_resume": [
                RuntimeNode(
                    name="profile_reader",
                    role="读取用户画像、项目和原始简历摘要",
                    reads=("user_id",),
                    writes=("user_profile", "user_projects"),
                    tools=("get_user_profile_context",),
                    depends_on=("context_builder",),
                    parallel_group="resume_prefetch",
                ),
                RuntimeNode(
                    name="target_job_reader",
                    role="读取目标岗位结构化 JD",
                    reads=("job_info",),
                    writes=("target_job",),
                    tools=("analyze_job_requirements",),
                    depends_on=("context_builder",),
                    parallel_group="resume_prefetch",
                ),
                RuntimeNode(
                    name="project_retriever",
                    role="召回与目标岗位最相关的项目经历",
                    reads=("user_profile", "target_job"),
                    writes=("retrieval_results",),
                    tools=("search_job_knowledge_base",),
                    depends_on=("profile_reader", "target_job_reader"),
                    prompt_template="resume_project_select",
                ),
                RuntimeNode(
                    name="resume_writer",
                    role="只基于已有画像和召回项目生成定向简历",
                    reads=("user_profile", "target_job", "retrieval_results"),
                    writes=("generated_resume", "generated_greeting"),
                    tools=("generate_targeted_resume",),
                    depends_on=("project_retriever",),
                    prompt_template="resume_writer",
                ),
            ],
            "career_advice": [
                RuntimeNode(
                    name="gap_inspector",
                    role="检查画像缺口和学习目标",
                    reads=("user_profile",),
                    writes=("profile_gaps",),
                    tools=("inspect_profile_gaps",),
                    depends_on=("context_builder",),
                ),
                RuntimeNode(
                    name="resource_retriever",
                    role="检索人工登记的学习资源",
                    reads=("profile_gaps",),
                    writes=("learning_resources",),
                    tools=("recommend_learning_resources",),
                    depends_on=("gap_inspector",),
                ),
                RuntimeNode(
                    name="writer",
                    role="输出可执行学习计划",
                    reads=("profile_gaps", "learning_resources"),
                    writes=("messages",),
                    depends_on=("resource_retriever",),
                    prompt_template="career_advice_writer",
                ),
            ],
        }
        return [*common_start, *branches.get(task_type, branches["build_profile"])]

    def allowed_tools(self, task_type: TaskType) -> list[str]:
        names: list[str] = []
        for node in self.workflow(task_type):
            for item in node.tools:
                if item not in names:
                    names.append(item)
        return names

    def select_context(self, task_type: TaskType, context: dict[str, Any] | None) -> ContextSelection:
        """Select, compress and isolate runtime context for a task."""
        raw = dict(context or {})
        keys_by_task: dict[TaskType, tuple[str, ...]] = {
            "build_profile": ("user_id", "session_id", "messages", "profile_summary", "resume_summary"),
            "recommend_jobs": ("user_id", "profile_summary", "skills", "target_roles", "preferred_locations", "salary_range"),
            "analyze_job": ("user_id", "job_id", "job_text", "company_name", "profile_summary", "history_job_context"),
            "generate_resume": ("user_id", "target_job", "profile_summary", "project_summaries", "resume_style"),
            "career_advice": ("user_id", "profile_summary", "skills", "target_roles", "profile_gaps"),
        }
        allowed = set(keys_by_task.get(task_type, keys_by_task["build_profile"]))
        selected = {key: self._compress_value(value) for key, value in raw.items() if key in allowed}
        omitted = sorted(key for key in raw if key not in allowed)
        serialized = json.dumps(selected, ensure_ascii=False, sort_keys=True, default=str)
        return ContextSelection(
            task_type=task_type,
            selected=selected,
            omitted_keys=omitted,
            compression={
                "max_string_chars": 1200,
                "max_list_items": 8,
                "raw_context_keys": sorted(raw.keys()),
                "selected_context_keys": sorted(selected.keys()),
            },
            isolation={
                "user_scope_required": True,
                "tool_scope": self.allowed_tools(task_type),
                "raw_resume_text_allowed": False,
                "cross_user_access_allowed": False,
            },
            fingerprint=hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16],
        )

    def build_prompt(self, task_type: TaskType, context: dict[str, Any] | None = None) -> PromptAssembly:
        """Assemble task-specific prompt rules and schema metadata."""
        selection = self.select_context(task_type, context)
        allowed_tools = self.allowed_tools(task_type)
        evidence_required = any(node.evidence_required for node in self.workflow(task_type))
        schema = self._output_schema(task_type)
        rules = [
            "你是 JobGuard 求职决策 Agent，所有回答使用中文。",
            "只能基于用户画像、岗位数据、工具结果和可追溯证据回答，不得编造经历或企业事实。",
            "结构化任务必须遵循输出 Schema；缺失或未核验事实使用 unknown/no_evidence。",
            "写入用户画像、简历或历史记录前必须经过业务层确认。",
        ]
        if task_type == "recommend_jobs":
            rules.append("岗位推荐优先满足方向、城市、薪资等硬约束，再结合关键词和语义相似度解释。")
        if task_type == "generate_resume":
            rules.append("简历生成只能重组和改写已有经历，不新增不存在的项目、奖项或技能。")
        preview = "\n".join([
            "系统规则：",
            *[f"- {rule}" for rule in rules],
            f"任务类型：{task_type}",
            f"允许工具：{', '.join(allowed_tools) or '无'}",
            f"上下文键：{', '.join(selection.selected.keys()) or '无'}",
            f"证据策略：{'必须绑定来源' if evidence_required else '按任务需要'}",
            f"输出字段：{', '.join(schema.get('properties', {}).keys())}",
        ])
        return PromptAssembly(
            task_type=task_type,
            system_rules=rules,
            context_keys=sorted(selection.selected.keys()),
            allowed_tools=allowed_tools,
            output_schema=schema,
            evidence_policy={
                "require_source_links": evidence_required,
                "allow_unverified_numbers": False,
                "on_missing_evidence": "unknown/no_evidence",
            },
            prompt_preview=preview,
        )

    def describe(self, task_type: TaskType = "analyze_job", context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a JSON-serialisable runtime blueprint for UI/API/interview docs."""
        selection = self.select_context(task_type, context)
        prompt = self.build_prompt(task_type, context)
        workflow = self.workflow(task_type)
        tool_details = []
        for name in self.allowed_tools(task_type):
            tool = self.registry.get(name)
            if not tool:
                continue
            tool_details.append({
                "name": tool.name,
                "category": tool.category,
                "execution_mode": tool.execution_mode,
                "risk_level": tool.risk_level,
                "requires_confirmation": tool.requires_confirmation,
                "expose_via_mcp": tool.expose_via_mcp,
            })
        return {
            "runtime": "LangGraph + deterministic Agent Runtime",
            "task_type": task_type,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "workflow": [
                {
                    "name": node.name,
                    "role": node.role,
                    "reads": list(node.reads),
                    "writes": list(node.writes),
                    "tools": list(node.tools),
                    "depends_on": list(node.depends_on),
                    "parallel_group": node.parallel_group,
                    "evidence_required": node.evidence_required,
                    "prompt_template": node.prompt_template,
                }
                for node in workflow
            ],
            "state_owners": STATE_OWNERS,
            "context_engineering": {
                "write": "节点只写入自己拥有的 State 字段，最终 DB 副作用由 service/API 层提交。",
                "select": selection.selected,
                "compress": selection.compression,
                "isolate": selection.isolation,
                "omitted_keys": selection.omitted_keys,
                "fingerprint": selection.fingerprint,
            },
            "prompt_assembly": {
                "system_rules": prompt.system_rules,
                "context_keys": prompt.context_keys,
                "allowed_tools": prompt.allowed_tools,
                "output_schema": prompt.output_schema,
                "evidence_policy": prompt.evidence_policy,
                "prompt_preview": prompt.prompt_preview,
            },
            "middleware_chain": [policy.__dict__ for policy in self.middlewares],
            "tool_scope": tool_details,
        }

    @staticmethod
    def _compress_value(value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            return text[:1200] + ("...[compressed]" if len(text) > 1200 else "")
        if isinstance(value, list):
            return [AgentRuntime._compress_value(item) for item in value[:8]]
        if isinstance(value, dict):
            return {str(key): AgentRuntime._compress_value(item) for key, item in list(value.items())[:24]}
        return value

    @staticmethod
    def _output_schema(task_type: TaskType) -> dict[str, Any]:
        schemas: dict[TaskType, dict[str, Any]] = {
            "build_profile": {
                "type": "object",
                "properties": {
                    "profile_delta": {"type": "object"},
                    "needs_confirmation": {"type": "boolean"},
                    "next_question": {"type": "string"},
                },
                "required": ["profile_delta", "needs_confirmation"],
            },
            "recommend_jobs": {
                "type": "object",
                "properties": {
                    "items": {"type": "array"},
                    "scoring_version": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["items", "scoring_version"],
            },
            "analyze_job": {
                "type": "object",
                "properties": {
                    "job_summary": {"type": "object"},
                    "match_score": {"type": "object"},
                    "risk_assessment": {"type": "object"},
                    "evidence": {"type": "array"},
                    "unknown_fields": {"type": "array"},
                },
                "required": ["job_summary", "risk_assessment", "unknown_fields"],
            },
            "generate_resume": {
                "type": "object",
                "properties": {
                    "resume_markdown": {"type": "string"},
                    "selected_projects": {"type": "array"},
                    "greeting": {"type": "string"},
                    "unsupported_claims": {"type": "array"},
                },
                "required": ["resume_markdown", "selected_projects", "unsupported_claims"],
            },
            "career_advice": {
                "type": "object",
                "properties": {
                    "skill_gaps": {"type": "array"},
                    "learning_plan": {"type": "array"},
                    "resources": {"type": "array"},
                },
                "required": ["skill_gaps", "learning_plan"],
            },
        }
        return schemas.get(task_type, schemas["build_profile"])


agent_runtime = AgentRuntime()
