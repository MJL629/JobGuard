"""
Critic Agent — Reflexion 反思机制

在 Agent 输出后进行质量评估，如果不合格触发重新执行。
支持 job_analysis / resume_generation / profile_building / general 四种任务类型的评估维度。
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Any

from app.llm.gateway import llm_gateway

logger = logging.getLogger(__name__)

# ─── Evaluation Dimensions ───────────────────────────────────────────────

EVALUATION_DIMENSIONS = {
    "job_analysis": (
        "1. 完整性：是否包含公司信息、JD分析、风险维度、建议？\n"
        "2. 准确性：风险判断是否有依据？\n"
        "3. 可用性：建议是否具体可操作？\n"
        "4. 格式：输出是否符合预期结构？"
    ),
    "resume_generation": (
        "1. 真实性：内容是否与用户画像一致？（配合 fact_check 结果）\n"
        "2. 针对性：是否针对目标岗位定制？\n"
        "3. 专业性：用词是否专业、量化是否合理？\n"
        "4. 完整性：是否包含所有必要模块？"
    ),
    "profile_building": (
        "1. 信息增量：是否提取了新的有用信息？\n"
        "2. 准确性：提取的信息是否正确？\n"
        "3. 追问质量：追问是否合理？"
    ),
    "general": (
        "1. 相关性：回复是否与用户需求相关？\n"
        "2. 完整性：是否回答了用户问题？\n"
        "3. 准确性：是否有明显错误？"
    ),
}

# ─── Critic Prompt ───────────────────────────────────────────────────────

CRITIC_SYSTEM_PROMPT = """你是 JobGuard 的质量评审员。你的职责是客观、严格地评估 Agent 输出质量。

## 评估规则
1. 严格按照评估维度逐项打分
2. 每个维度满分 25 分（4 个维度共 100 分），不足 4 个维度时按比例调整
3. 评分标准：0-40 严重不合格 / 40-69 需要改进 / 70-85 良好 / 86-100 优秀
4. 发现问题时必须指出具体问题和改进建议
5. 如果分数低于 70，必须标记 needs_retry=true 并提供具体的 retry_hint
6. retry_hint 应该具体、可操作，告诉 Agent 哪里做得不好、应该如何改进

## 输出格式
只输出 JSON，不要包含任何其他文字：
{
  "score": 0-100,
  "passed": true/false,
  "issues": [
    {
      "severity": "critical/high/medium/low",
      "description": "具体问题描述",
      "suggestion": "改进建议"
    }
  ],
  "summary": "评审总结（一句话概括）",
  "needs_retry": true/false,
  "retry_hint": "如果需要重试，给出明确的改进方向"
}"""


# ─── Data Classes ────────────────────────────────────────────────────────

@dataclass
class CritiqueResult:
    """Critic 评估结果"""
    score: float              # 0-100 质量评分
    passed: bool              # 是否通过（score >= threshold）
    issues: list[dict] = field(default_factory=list)
    # issues: [{"severity": "critical/high/medium/low", "description": "...", "suggestion": "..."}]
    summary: str = ""         # 评审总结
    needs_retry: bool = False # 是否需要重试
    retry_hint: str = ""      # 重试时的改进建议


# ─── Critic Agent ────────────────────────────────────────────────────────

class Critic:
    """
    Critic 反思 Agent。

    对 Agent 输出进行质量评估，如果不合格（score < pass_threshold），
    通过 reflect_and_retry 将改进建议注入到输入数据中，触发重新执行。

    使用示例:
        critic = Critic(pass_threshold=70.0, max_retries=2)

        # 单次评估
        result = await critic.evaluate("resume_generation", input_data, output_data)

        # 完整反思-重试循环
        final_output = await critic.reflect_and_retry(
            task_type="resume_generation",
            input_data=user_input,
            execute_func=some_agent.execute,
            max_retries=2,
        )
    """

    def __init__(self, pass_threshold: float = 70.0, max_retries: int = 2):
        self.pass_threshold = pass_threshold
        self.max_retries = max_retries

    # ─── 单次评估 ─────────────────────────────────────────────────────

    async def evaluate(
        self,
        task_type: str,
        input_data: dict,
        output_data: dict,
    ) -> CritiqueResult:
        """
        评估 Agent 输出质量。

        Args:
            task_type: 任务类型（job_analysis / resume_generation / profile_building / general）
            input_data: Agent 的输入数据（用户输入、上下文等）
            output_data: Agent 的输出数据

        Returns:
            CritiqueResult 评估结果
        """
        dimensions = EVALUATION_DIMENSIONS.get(
            task_type, EVALUATION_DIMENSIONS["general"]
        )

        # 构建用户提示
        user_prompt = self._build_evaluation_prompt(task_type, input_data, output_data, dimensions)

        messages = [
            {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(f"[Critic] 开始评估 task_type={task_type}")

        try:
            response = await llm_gateway.chat_primary(messages, stream=False)
            result = self._parse_critique(response)
            logger.info(
                f"[Critic] 评估完成: score={result.score}, passed={result.passed}, "
                f"needs_retry={result.needs_retry}"
            )
            if result.issues:
                logger.debug(f"[Critic] 发现 {len(result.issues)} 个问题")
            return result
        except Exception as e:
            logger.error(f"[Critic] 评估失败: {e}")
            # 评估失败时默认通过，不阻塞流程
            return CritiqueResult(
                score=100.0,
                passed=True,
                issues=[],
                summary=f"Critic 评估失败（{str(e)}），默认通过",
                needs_retry=False,
                retry_hint="",
            )

    # ─── 反思-重试循环 ─────────────────────────────────────────────────

    async def reflect_and_retry(
        self,
        task_type: str,
        input_data: dict,
        execute_func: Callable,  # async def(stage: dict) -> dict
        max_retries: int = 2,
    ) -> dict:
        """
        完整的反思-重试循环。

        流程:
        1. 调用 execute_func 执行任务
        2. 用 Critic 评估输出
        3. 如果 needs_retry=True，将 retry_hint 注入 input_data.critic_feedback，重新执行
        4. 最多重试 max_retries 次
        5. 达到最大重试次数后，返回最后一次输出并附带警告

        Args:
            task_type: 任务类型
            input_data: 执行输入数据
            execute_func: 执行函数，签名 async def(stage: dict) -> dict
            max_retries: 最大重试次数（会与实例默认值取最小值）

        Returns:
            dict: {
                "output": ...     # 最终输出
                "critiques": [...] # 历次评估结果
                "retries": int     # 实际重试次数
                "final_passed": bool
            }
        """
        retry_limit = min(max_retries, self.max_retries)
        critiques = []

        current_input = dict(input_data)  # 复制，避免修改原始数据

        for attempt in range(retry_limit + 1):
            if attempt > 0:
                logger.info(
                    f"[Critic] 第 {attempt}/{retry_limit} 次重试..."
                )

            # 1. 执行任务
            output = await execute_func(current_input)

            # 2. 评估
            critique = await self.evaluate(task_type, current_input, output)
            critiques.append(critique)

            # 3. 判断是否需要重试
            if not critique.needs_retry or attempt >= retry_limit:
                logger.info(
                    f"[Critic] 反思-重试完成: retries={attempt}, "
                    f"final_passed={critique.passed}, score={critique.score}"
                )
                return {
                    "output": output,
                    "critiques": [
                        {
                            "score": c.score,
                            "passed": c.passed,
                            "issues": c.issues,
                            "summary": c.summary,
                            "needs_retry": c.needs_retry,
                            "retry_hint": c.retry_hint,
                        }
                        for c in critiques
                    ],
                    "retries": attempt,
                    "final_passed": critique.passed,
                }

            # 4. 注入反馈，准备重试
            logger.info(
                f"[Critic] 输出不合格 (score={critique.score})，准备重试。"
                f"提示: {critique.retry_hint[:100]}..."
            )
            current_input = dict(current_input)
            current_input["critic_feedback"] = critique.retry_hint

            # 合并之前的问题描述，帮助 Agent 理解之前错在哪里
            if attempt > 0 and critiques:
                previous_issues = []
                for c in critiques:
                    for issue in c.issues:
                        previous_issues.append(
                            f"- [{issue['severity']}] {issue['description']}"
                        )
                current_input["previous_issues"] = previous_issues

        # 不应该到达这里，但作为兜底
        logger.warning("[Critic] 反思-重试循环异常退出")
        return {
            "output": output,
            "critiques": [
                {
                    "score": c.score,
                    "passed": c.passed,
                    "issues": c.issues,
                    "summary": c.summary,
                    "needs_retry": c.needs_retry,
                    "retry_hint": c.retry_hint,
                }
                for c in critiques
            ],
            "retries": retry_limit,
            "final_passed": False,
        }

    # ─── 内部方法 ──────────────────────────────────────────────────────

    def _build_evaluation_prompt(
        self,
        task_type: str,
        input_data: dict,
        output_data: dict,
        dimensions: str,
    ) -> str:
        """构建评估 prompt"""
        user_input = json.dumps(input_data, ensure_ascii=False, indent=2)
        agent_output = json.dumps(output_data, ensure_ascii=False, indent=2)

        # 截断过长内容
        if len(user_input) > 3000:
            user_input = user_input[:3000] + "\n... (内容过长，已截断)"
        if len(agent_output) > 5000:
            agent_output = agent_output[:5000] + "\n... (内容过长，已截断)"

        return f"""请评估以下 Agent 输出。

任务类型：{task_type}
通过阈值：{self.pass_threshold} 分

评估维度：
{dimensions}

用户输入/上下文：
{user_input}

Agent 输出：
{agent_output}

请严格按照评估规则输出 JSON 格式的评估结果。"""

    def _parse_critique(self, raw_response: str) -> CritiqueResult:
        """
        从 LLM 响应中解析评估结果。

        支持多种格式：
        - 纯 JSON
        - markdown 代码块包裹的 JSON
        - 包含 JSON 对象的文本
        """
        cleaned = raw_response.strip()

        # 移除 markdown 代码块标记
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # 尝试从文本中提取 JSON 对象
            import re
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    logger.warning(f"[Critic] 无法解析评估结果: {raw_response[:200]}...")
                    return self._default_result()
            else:
                logger.warning(f"[Critic] 响应中未找到 JSON: {raw_response[:200]}...")
                return self._default_result()

        return CritiqueResult(
            score=float(data.get("score", 0)),
            passed=bool(data.get("passed", False)),
            issues=data.get("issues", []),
            summary=data.get("summary", ""),
            needs_retry=bool(data.get("needs_retry", False)),
            retry_hint=data.get("retry_hint", ""),
        )

    def _default_result(self) -> CritiqueResult:
        """解析失败时的默认结果"""
        return CritiqueResult(
            score=100.0,
            passed=True,
            issues=[],
            summary="评估解析失败，默认通过",
            needs_retry=False,
            retry_hint="",
        )


# ─── Global Singleton ────────────────────────────────────────────────────

critic = Critic()
