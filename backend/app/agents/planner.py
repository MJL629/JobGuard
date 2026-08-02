"""
Planner-Executor 架构

Planner: 用 LLM 分析用户需求，制定多步骤执行计划。
Executor: 按依赖关系拓扑排序执行计划，并行执行无依赖步骤。
"""

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from app.agents.tool_registry import ToolRegistry, tool_registry
from app.llm.gateway import llm_gateway

logger = logging.getLogger(__name__)

# ─── Planner Prompt ─────────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """你是 JobGuard 的任务规划器。你的职责是根据用户需求，制定由可用工具组成的多步骤执行计划。

规则：
1. 每个步骤必须使用一个已注册的工具（tool_name 必须与可用工具列表中的名称完全一致）
2. 步骤应按逻辑顺序排列，有依赖关系的步骤通过 depends_on 声明
3. depends_on 中的 ID 必须是已存在的步骤 ID
4. 每个步骤的 description 应该是人类可读的一句话描述
5. tool_args 必须符合对应工具的参数 schema
6. 只使用必要的工具，不要增加多余的步骤
7. **重要：tool_name 必须使用工具列表中的确切名称，不要用大写或缩写！**

请输出 JSON 格式的执行计划数组（不要包含其他文字）：
[{"step_id": 1, "tool_name": "...", "tool_args": {...}, "description": "...", "depends_on": []}]"""


# ─── Data Classes ───────────────────────────────────────────────────────

@dataclass
class PlanStep:
    """执行计划中的单个步骤"""
    step_id: int
    tool_name: str
    tool_args: dict
    description: str
    depends_on: list[int] = field(default_factory=list)
    status: str = "pending"  # pending / running / completed / failed
    result: Any = None
    error: Optional[str] = None


# ─── Planner ────────────────────────────────────────────────────────────

class Planner:
    """
    任务规划器。

    接收用户消息和上下文，通过 LLM 分析并生成由 PlanStep 组成的执行计划。
    支持根据执行反馈修订计划。
    """

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or tool_registry

    async def create_plan(
        self,
        user_message: str,
        context: Optional[dict] = None,
    ) -> list[PlanStep]:
        """
        根据用户消息和上下文，用 LLM 生成执行计划。

        Args:
            user_message: 用户输入的消息
            context: 可选的上下文信息（如已有画像、历史对话等）

        Returns:
            PlanStep 列表

        Raises:
            ValueError: LLM 返回的计划无法解析时
        """
        tools_desc = self.registry.get_tools_description()
        context_str = json.dumps(context, ensure_ascii=False) if context else "（无上下文）"

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_planning_prompt(user_message, tools_desc, context_str)},
        ]

        logger.info("[Planner] 开始生成执行计划...")
        logger.debug(f"[Planner] 用户消息: {user_message}")

        try:
            response = await llm_gateway.chat_primary(messages, stream=False)
            plan = self._parse_plan(response)
            logger.info(f"[Planner] 计划生成完成，共 {len(plan)} 个步骤")
            for step in plan:
                logger.debug(f"  Step {step.step_id}: {step.tool_name} — {step.description}")
            return plan
        except Exception as e:
            logger.error(f"[Planner] 计划生成失败: {e}")
            raise ValueError(f"无法生成执行计划: {e}") from e

    async def revise_plan(
        self,
        plan: list[PlanStep],
        feedback: str,
    ) -> list[PlanStep]:
        """
        根据执行反馈修订计划。

        将当前计划状态和失败反馈发给 LLM，生成修订后的计划。

        Args:
            plan: 当前计划（含各步骤的执行状态和结果）
            feedback: 失败原因或修订建议

        Returns:
            修订后的 PlanStep 列表
        """
        plan_summary = self._summarize_plan(plan)
        tools_desc = self.registry.get_tools_description()

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_revision_prompt(plan_summary, feedback, tools_desc)},
        ]

        logger.info("[Planner] 开始修订执行计划...")
        logger.debug(f"[Planner] 反馈: {feedback}")

        try:
            response = await llm_gateway.chat_primary(messages, stream=False)
            revised = self._parse_plan(response)
            logger.info(f"[Planner] 计划修订完成，共 {len(revised)} 个步骤")
            return revised
        except Exception as e:
            logger.error(f"[Planner] 计划修订失败: {e}")
            raise ValueError(f"无法修订执行计划: {e}") from e

    # ─── 内部方法 ──────────────────────────────────────────────────────

    def _build_planning_prompt(
        self, user_message: str, tools_desc: str, context_str: str
    ) -> str:
        return f"""可用工具：
{tools_desc}

用户消息：{user_message}

上下文：{context_str}

请输出 JSON 格式的执行计划："""

    def _build_revision_prompt(
        self, plan_summary: str, feedback: str, tools_desc: str
    ) -> str:
        return f"""可用工具：
{tools_desc}

当前计划执行情况：
{plan_summary}

执行反馈 / 失败原因：{feedback}

请根据以上信息修订执行计划，输出 JSON 格式的新计划："""

    def _summarize_plan(self, plan: list[PlanStep]) -> str:
        """将当前计划状态总结为文本"""
        lines = []
        for step in plan:
            status_icon = {
                "pending": "⏳",
                "running": "🔄",
                "completed": "✅",
                "failed": "❌",
            }.get(step.status, "❓")
            line = f"  Step {step.step_id} [{status_icon} {step.status}] {step.tool_name}: {step.description}"
            if step.error:
                line += f" — 错误: {step.error}"
            if step.result and step.status == "completed":
                result_preview = json.dumps(step.result, ensure_ascii=False)
                if len(result_preview) > 200:
                    result_preview = result_preview[:200] + "..."
                line += f" — 结果: {result_preview}"
            lines.append(line)
        return "\n".join(lines)

    def _parse_plan(self, raw_response: str) -> list[PlanStep]:
        """
        从 LLM 响应中解析执行计划。

        支持多种格式：
        - 纯 JSON 数组
        - 包含 JSON 数组的文本（提取第一个数组）
        """
        # 尝试直接解析
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
            plan_data = json.loads(cleaned)
            if isinstance(plan_data, list):
                return self._validate_and_convert(plan_data)
            raise ValueError("LLM 返回的不是 JSON 数组")
        except json.JSONDecodeError:
            pass

        # 尝试从文本中提取 JSON 数组
        import re
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if match:
            try:
                plan_data = json.loads(match.group(0))
                return self._validate_and_convert(plan_data)
            except json.JSONDecodeError:
                pass

        raise ValueError(f"无法解析 LLM 返回的执行计划: {raw_response[:200]}...")

    def _validate_and_convert(self, plan_data: list[dict]) -> list[PlanStep]:
        """Validate and convert raw JSON plan to PlanStep list with fuzzy tool name matching"""
        steps = []
        for item in plan_data:
            if "step_id" not in item:
                raise ValueError(f"Plan item missing step_id: {item}")
            if "tool_name" not in item:
                raise ValueError(f"Step {item.get('step_id', '?')} missing tool_name")

            tool_name = item["tool_name"]
            # Try exact match first, then fuzzy match
            if self.registry.get(tool_name) is None:
                matched = self._fuzzy_match_tool(tool_name)
                if matched:
                    logger.info(f"[Planner] Tool '{item['tool_name']}' fuzzy matched to '{matched}'")
                    tool_name = matched
                else:
                    logger.warning(
                        f"[Planner] Tool '{item['tool_name']}' not registered, execution may fail"
                    )

            steps.append(PlanStep(
                step_id=int(item["step_id"]),
                tool_name=tool_name,
                tool_args=item.get("tool_args", {}),
                description=item.get("description", ""),
                depends_on=[int(d) for d in item.get("depends_on", [])],
            ))

        # Sort by step_id
        steps.sort(key=lambda s: s.step_id)
        return steps

    def _fuzzy_match_tool(self, name: str) -> str | None:
        """Fuzzy match tool name (case-insensitive, normalize separators)"""
        normalized = name.lower().replace("-", "_").replace(" ", "_")
        for tool in self.registry.list_all():
            tool_norm = tool.name.lower().replace("-", "_").replace(" ", "_")
            if tool_norm == normalized:
                return tool.name
            # Substring match
            if normalized in tool_norm or tool_norm in normalized:
                return tool.name
        return None

# ─── Executor ───────────────────────────────────────────────────────────

class Executor:
    """
    计划执行器。

    按依赖关系对步骤进行拓扑排序，并行执行无依赖关系的步骤。
    如果某步骤失败，收集失败信息供 Planner 修订。
    """

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or tool_registry

    async def execute(
        self,
        plan: list[PlanStep],
    ) -> list[PlanStep]:
        """
        按依赖关系执行计划。

        执行流程：
        1. 拓扑排序确定执行顺序
        2. 每一批无依赖的步骤并行执行
        3. 某步骤失败时标记状态，不阻塞后续步骤

        Args:
            plan: 待执行的 PlanStep 列表

        Returns:
            执行后的 PlanStep 列表（含各步骤的状态和结果）
        """
        if not plan:
            logger.warning("[Executor] 计划为空，跳过执行")
            return []

        logger.info(f"[Executor] 开始执行计划，共 {len(plan)} 个步骤")

        # 重置所有步骤状态
        for step in plan:
            step.status = "pending"
            step.result = None
            step.error = None

        # 构建依赖图
        step_map = {s.step_id: s for s in plan}
        in_degree = {s.step_id: len(s.depends_on) for s in plan}
        dependents = {s.step_id: [] for s in plan}
        for s in plan:
            for dep_id in s.depends_on:
                if dep_id in dependents:
                    dependents[dep_id].append(s.step_id)

        # 拓扑排序 + 分批并行执行
        completed = set()
        failed = set()

        while len(completed) + len(failed) < len(plan):
            # 找到所有就绪的步骤（依赖全部完成且未失败）
            ready = []
            for s in plan:
                if s.step_id in completed or s.step_id in failed:
                    continue
                if in_degree[s.step_id] == 0:
                    # 检查依赖步骤是否全部成功完成
                    all_deps_ok = all(
                        dep_id in completed
                        for dep_id in s.depends_on
                    )
                    if all_deps_ok:
                        ready.append(s)

            if not ready:
                # 没有就绪步骤但有未完成步骤 — 存在依赖环或依赖步骤失败
                pending_ids = set(s.step_id for s in plan) - completed - failed
                logger.error(f"[Executor] 无法继续执行，存在未解决的步骤: {pending_ids}")
                # 标记剩余步骤为失败
                for sid in pending_ids:
                    step_map[sid].status = "failed"
                    step_map[sid].error = "依赖步骤执行失败或存在循环依赖"
                    failed.add(sid)
                break

            logger.info(f"[Executor] 并行执行 {len(ready)} 个步骤: {[s.step_id for s in ready]}")

            # 并行执行
            tasks = [self._execute_step(step, step_map) for step in ready]
            await asyncio.gather(*tasks, return_exceptions=True)

            # 更新完成和失败集合
            for step in ready:
                if step.status == "completed":
                    completed.add(step.step_id)
                elif step.status == "failed":
                    failed.add(step.step_id)

        # 输出执行摘要
        self._log_summary(plan)
        return plan

    async def _execute_step(self, step: PlanStep, step_map: dict[int, PlanStep]) -> None:
        """
        执行单个步骤。

        解析参数中的依赖引用（如 $step_1.result.field），调用工具函数。
        """
        step.status = "running"
        logger.info(f"[Executor] Step {step.step_id}: 开始执行 {step.tool_name}")

        try:
            tool = self.registry.get(step.tool_name)
            if tool is None:
                raise ValueError(f"工具 '{step.tool_name}' 未注册")

            if tool.func is None:
                raise ValueError(f"工具 '{step.tool_name}' 的实现尚未注入 (func is None)")

            # 解析参数中的依赖引用
            resolved_args = self._resolve_args(step.tool_args, step_map)

            # 调用工具函数（支持同步和异步）
            if asyncio.iscoroutinefunction(tool.func):
                result = await tool.func(**resolved_args)
            else:
                result = tool.func(**resolved_args)

            step.result = result
            step.status = "completed"
            logger.info(f"[Executor] Step {step.step_id}: 执行成功")

        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            logger.error(f"[Executor] Step {step.step_id} 执行失败: {e}")

    def _resolve_args(self, args: dict, step_map: dict[int, PlanStep]) -> dict:
        """
        解析参数中的依赖引用。

        支持格式：将 "$step_N" 替换为步骤 N 的结果。
        支持嵌套引用：{"key": "$step_1"} → {"key": step_1.result}
        """
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str) and value.startswith("$step_"):
                try:
                    step_id = int(value.replace("$step_", ""))
                    dep_step = step_map.get(step_id)
                    if dep_step and dep_step.status == "completed":
                        resolved[key] = dep_step.result
                    else:
                        raise ValueError(
                            f"依赖步骤 Step {step_id} 未完成或不存在 "
                            f"(status={dep_step.status if dep_step else 'N/A'})"
                        )
                except ValueError:
                    # 不是有效的引用格式，保持原值
                    resolved[key] = value
            elif isinstance(value, dict):
                resolved[key] = self._resolve_args(value, step_map)
            elif isinstance(value, list):
                resolved[key] = [
                    self._resolve_args(item, step_map) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                resolved[key] = value
        return resolved

    def _log_summary(self, plan: list[PlanStep]) -> None:
        """输出执行摘要日志"""
        total = len(plan)
        completed = sum(1 for s in plan if s.status == "completed")
        failed = sum(1 for s in plan if s.status == "failed")
        logger.info(
            f"[Executor] 执行完成: {completed}/{total} 成功"
            + (f", {failed} 失败" if failed else "")
        )
