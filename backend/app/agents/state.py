"""
JobGuard LangGraph 全局状态定义
"""

from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages


class JobGuardState(TypedDict, total=False):
    """JobGuard 全局状态"""

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

    # 用户画像
    user_profile: Optional[dict]
    user_projects: Optional[list]

    # 岗位信息
    job_raw_input: Optional[str]
    job_info: Optional[dict]

    # 分析结果
    company_report: Optional[dict]
    match_score: Optional[dict]

    # 生成结果
    generated_resume: Optional[str]
    generated_greeting: Optional[str]
    recommended_jobs: Optional[list]

    # 错误处理
    error: Optional[str]
    retry_count: int
