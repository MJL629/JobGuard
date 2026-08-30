"""
JobGuard LangGraph 全局状态定义
"""

from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages


class JobGuardState(TypedDict, total=False):
    """JobGuard 全局状态。

    上下文分三层管理：
    1. 长期上下文：MySQL / Chroma 中的用户画像、岗位、历史分析、简历片段。
    2. 运行态上下文：本 TypedDict，贯穿一次 LangGraph 请求。
    3. Prompt 上下文：每个 Agent 只接收自己需要的最小字段。

    为避免多 Agent “打架”，核心字段采用 state ownership：
    - Router/Orchestrator 只写 intent / execution_plan / evidence_policy。
    - Profile 节点只写 user_profile / user_projects。
    - Retrieval/Recommendation 节点只写 retrieval_results / recommended_jobs。
    - Job Analysis 节点只写 company_report / match_score。
    - Resume 节点只写 generated_resume / generated_greeting。
    - API/service 层负责最终 DB 写入，Agent 不直接随意覆盖持久化状态。
    """

    # 会话信息
    messages: Annotated[list, add_messages]
    user_id: str
    session_id: str
    session_type: str

    # 意图路由
    intent: str  # build_profile | analyze_job | generate_resume | recommend_jobs | career_advice
    current_stage: str
    graph_trace: list[str]
    execution_plan: list[dict]
    evidence_policy: dict
    state_owners: dict

    # 用户画像
    user_profile: Optional[dict]
    user_projects: Optional[list]

    # 岗位信息
    job_raw_input: Optional[str]
    job_info: Optional[dict]

    # 分析结果
    company_report: Optional[dict]
    match_score: Optional[dict]
    retrieval_results: Optional[dict]
    recommendation_breakdown: Optional[dict]

    # 生成结果
    generated_resume: Optional[str]
    generated_greeting: Optional[str]
    recommended_jobs: Optional[list]

    # 错误处理
    error: Optional[str]
    retry_count: int
