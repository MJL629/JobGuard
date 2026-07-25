"""
调度与自检 Agent（Orchestrator）
负责意图识别、状态管理、冲突仲裁、结果审查
"""

from app.llm.gateway import llm_gateway

INTENT_PROMPT = """你是 JobGuard 的调度器。根据用户的消息，判断用户意图。

意图类型：
- build_profile: 用户想要建立/更新个人画像（首次使用、补充信息、更新偏好）
- analyze_job: 用户发送了岗位链接/截图，想要分析这个岗位
- generate_resume: 用户想要针对某个岗位生成简历
- recommend_jobs: 用户想要系统推荐适合的岗位

用户消息：{user_message}
当前状态：用户画像是否完整=未知

请只返回意图类型（一个单词）。"""


async def detect_intent(user_message: str) -> str:
    """识别用户意图"""
    prompt = INTENT_PROMPT.format(user_message=user_message)
    messages = [{"role": "system", "content": prompt}]
    result = await llm_gateway.chat_primary(messages)
    return result.strip().lower()


async def route_by_intent(intent: str) -> str:
    """根据意图路由到对应流程"""
    routing = {
        "build_profile": "profile_agent",
        "analyze_job": "job_parser",
        "generate_resume": "resume_generator",
        "recommend_jobs": "job_matcher",
    }
    return routing.get(intent, "profile_agent")


class OrchestratorAgent:
    """调度与自检 Agent"""

    async def run(self, state: dict) -> dict:
        """
        调度入口：识别意图并路由
        """
        # 获取最后一条用户消息
        messages = state.get("messages", [])
        if not messages:
            return {**state, "intent": "build_profile", "current_stage": "init"}

        last_msg = messages[-1].content if hasattr(messages[-1], 'content') else str(messages[-1])

        intent = await detect_intent(last_msg)
        next_stage = await route_by_intent(intent)

        return {
            **state,
            "intent": intent,
            "current_stage": next_stage,
        }
