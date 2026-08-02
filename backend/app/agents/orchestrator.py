"""
调度与自检 Agent（Orchestrator）
负责意图识别、状态管理、冲突仲裁、结果审查
"""

from app.llm.gateway import llm_gateway

INTENT_PROMPT = """你是 JobGuard 的调度器。根据用户的消息，判断用户意图。

意图类型：
- build_profile: 用户想要建立/更新个人画像（首次使用、补充信息、更新偏好、描述求职意向但没有明确说"推荐岗位"）
- analyze_job: 用户发送了岗位链接/截图/完整JD，想要分析这个岗位
- generate_resume: 用户想要针对某个岗位生成简历
- recommend_jobs: 用户明确想要系统推荐/匹配适合的岗位（如"给我推荐岗位""匹配岗位"）

判断规则：
- 如果用户提到"画像""建立画像""完善画像""更新画像""我的偏好"，返回 build_profile
- 如果用户只是描述自己想找什么工作（方向、城市、薪资），但没有明确说"推荐岗位"，优先返回 build_profile
- 如果用户明确说"推荐岗位""匹配岗位""有什么适合我的工作"，返回 recommend_jobs
- 如果用户发送了岗位链接或粘贴了JD，返回 analyze_job
- 如果用户提到"简历""生成简历"，返回 generate_resume

用户消息：{user_message}
当前状态：用户画像是否完整=未知

请只返回意图类型（一个单词）：build_profile / analyze_job / generate_resume / recommend_jobs。"""


def _rule_based_intent(user_message: str) -> str | None:
    """基于规则的快速意图判断"""
    msg = user_message.lower()
    
    if any(kw in msg for kw in ['建立画像', '完善画像', '更新画像', '我的画像', '求职画像', '画像']):
        return 'build_profile'
    if any(kw in msg for kw in ['分析岗位', '分析这个', '岗位链接', '这个岗位', '判断这个', '值得投递', '帮忙看看这个岗位', 'jd']):
        return 'analyze_job'
    if any(kw in msg for kw in ['生成简历', '写简历', '生成针对', '简历']):
        return 'generate_resume'
    if any(kw in msg for kw in ['推荐岗位', '匹配岗位', '推荐工作', '有什么岗位', '适合我的岗位', '帮我匹配', '匹配工作']):
        return 'recommend_jobs'
    
    return None


async def detect_intent(user_message: str) -> str:
    """识别用户意图，先用规则兜底，再用 LLM"""
    # 规则优先
    rule_intent = _rule_based_intent(user_message)
    if rule_intent:
        return rule_intent
    
    prompt = INTENT_PROMPT.format(user_message=user_message)
    messages = [{"role": "user", "content": prompt}]
    result = await llm_gateway.chat_primary(messages)
    result = result.strip().lower()
    
    valid_intents = {'build_profile', 'analyze_job', 'generate_resume', 'recommend_jobs'}
    for intent in valid_intents:
        if intent in result:
            return intent
    return 'build_profile'


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
