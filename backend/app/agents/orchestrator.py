"""
调度与自检 Agent（Orchestrator）
负责意图识别、状态管理、冲突仲裁、结果审查
"""

import re

from app.llm.gateway import llm_gateway

INTENT_PROMPT = """你是 JobGuard 的调度器。根据用户的消息和当前会话判断用户意图。

意图类型：
- build_profile: 用户想要建立/更新个人画像（首次使用、补充信息、更新偏好、描述求职意向但没有明确说"推荐岗位"）
- analyze_job: 用户发送了岗位链接/截图/完整JD，想要分析这个岗位
- generate_resume: 用户想要针对某个岗位生成简历
- recommend_jobs: 用户明确想要系统推荐/匹配适合的岗位（如"给我推荐岗位""匹配岗位"）
- career_advice: 用户咨询学习路线、课程资源、面试表达、职业规划或一般求职问题

判断规则：
- 如果用户提到"画像""建立画像""完善画像""更新画像""我的偏好"，返回 build_profile
- 如果用户只是描述自己想找什么工作（方向、城市、薪资），但没有明确说"推荐岗位"，优先返回 build_profile
- 如果用户明确说"推荐岗位""匹配岗位""有什么适合我的工作"，返回 recommend_jobs
- 如果用户发送了岗位链接或粘贴了JD，返回 analyze_job
- 只有用户明确要求生成、修改、优化或定制简历时，才返回 generate_resume；仅仅说“简历里没写某段经历”是在补充画像
- 当前会话处于 profile_building 时，用户陈述自己的经历、能力、求职偏好或限制条件，优先返回 build_profile

用户消息：{user_message}
当前会话：{session_type}

请只返回意图类型（一个单词）：build_profile / analyze_job / generate_resume / recommend_jobs / career_advice。"""


def _rule_based_intent(user_message: str, session_type: str | None = None) -> str | None:
    """基于规则的快速意图判断"""
    msg = user_message.lower()
    
    if any(kw in msg for kw in ['建立画像', '完善画像', '更新画像', '我的画像', '求职画像', '画像']):
        return 'build_profile'
    if any(kw in msg for kw in ['分析岗位', '分析这个', '岗位链接', '这个岗位', '判断这个', '值得投递', '帮忙看看这个岗位', 'jd']):
        return 'analyze_job'
    if any(kw in msg for kw in ['生成简历', '写一份简历', '生成针对', '定制简历', '修改简历', '优化简历']):
        return 'generate_resume'
    if any(kw in msg for kw in ['推荐岗位', '匹配岗位', '推荐工作', '有什么岗位', '适合我的岗位', '帮我匹配', '匹配工作']):
        return 'recommend_jobs'
    if any(kw in msg for kw in [
        '怎么学', '学习路线', '课程', '教程', 'b站', '网课', '面试怎么',
        '面试准备', '职业规划', '求职建议', '简历怎么讲', '项目怎么讲',
    ]):
        return 'career_advice'

    profile_evidence_phrases = [
        '我想找', '我的目标', '我的偏好', '我能接受', '我可以接受', '我不接受',
        '我做过', '我参加过', '我负责', '我的项目', '我的实习', '我的经历',
        '简历里没写', '没写进简历', '没有写进简历', '补充经历', '补充信息',
    ]
    if any(kw in msg for kw in profile_evidence_phrases):
        return 'build_profile'
    if session_type == 'profile_building':
        # 画像会话不是表单锁定模式。用户临时询问方向前景、学习或选择原因时，
        # 先回答问题，再继续画像；陈述个人信息时才进入画像抽取。
        asks_for_advice = bool(re.search(
            r"(?:为什么|怎么|如何|什么|哪些|是否|有没有|值得吗|靠谱吗|前景|区别|建议).{0,30}[？?]?$",
            msg,
        )) or msg.rstrip().endswith(("?", "？"))
        if asks_for_advice:
            return 'career_advice'
        return 'build_profile'
    
    return None


async def detect_intent(user_message: str, session_type: str | None = None) -> str:
    """识别用户意图，先用规则兜底，再用 LLM"""
    # 规则优先
    rule_intent = _rule_based_intent(user_message, session_type)
    if rule_intent:
        return rule_intent
    
    prompt = INTENT_PROMPT.format(
        user_message=user_message,
        session_type=session_type or 'general',
    )
    messages = [{"role": "user", "content": prompt}]
    result = await llm_gateway.chat_primary(messages)
    result = result.strip().lower()
    
    valid_intents = {'build_profile', 'analyze_job', 'generate_resume', 'recommend_jobs', 'career_advice'}
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
        "career_advice": "career_advisor",
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
