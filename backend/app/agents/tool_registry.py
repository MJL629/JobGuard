"""
Tool Registry — 统一管理所有 Agent 工具

提供工具的注册、查询、分类和格式转换功能。
支持 OpenAI Function Calling 格式输出。
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """单个工具定义"""
    name: str
    description: str
    parameters: dict          # JSON Schema 格式的参数定义
    func: Optional[Callable] = None  # 异步或同步函数，后续由 API 层注入
    category: str = "general"  # search / parse / generate / analyze


class ToolRegistry:
    """
    工具注册中心。

    统一管理所有 Agent 可用的工具，提供：
    - 注册 / 查询工具
    - 按分类筛选
    - 导出为 OpenAI Function Calling 格式
    - 生成人类可读的工具列表
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._register_builtin_tools()

    # ─── 注册 ──────────────────────────────────────────────────────────

    def register(self, tool: Tool) -> None:
        """注册一个工具（同名工具会被覆盖）"""
        if tool.name in self._tools:
            logger.warning(f"[ToolRegistry] 工具 '{tool.name}' 已存在，将被覆盖")
        self._tools[tool.name] = tool
        logger.info(f"[ToolRegistry] 注册工具: {tool.name} (category={tool.category})")

    # ─── 查询 ──────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[Tool]:
        """按名称获取工具"""
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        """获取所有已注册工具"""
        return list(self._tools.values())

    def list_by_category(self, category: str) -> list[Tool]:
        """按分类获取工具列表"""
        return [t for t in self._tools.values() if t.category == category]

    def list_categories(self) -> list[str]:
        """获取所有工具分类"""
        return sorted(set(t.category for t in self._tools.values()))

    # ─── 格式转换 ──────────────────────────────────────────────────────

    def get_openai_tools(self) -> list[dict]:
        """
        将所有工具转为 OpenAI Function Calling 格式。

        Returns:
            [{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}]
        """
        result = []
        for tool in self._tools.values():
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })
        return result

    def get_tools_description(self) -> str:
        """
        生成人类可读的工具列表描述，供 Planner prompt 使用。

        Returns:
            格式化的工具描述字符串
        """
        lines = []
        categories = self.list_categories()
        for cat in categories:
            lines.append(f"## {cat.upper()}")
            for tool in self.list_by_category(cat):
                params_str = json.dumps(tool.parameters, ensure_ascii=False, indent=2)
                lines.append(f"  - {tool.name}: {tool.description}")
                lines.append(f"    参数: {params_str}")
        return "\n".join(lines)

    def get_tool_names(self) -> list[str]:
        """获取所有工具名称列表"""
        return list(self._tools.keys())

    # ─── 内置工具注册 ──────────────────────────────────────────────────

    def _register_builtin_tools(self) -> None:
        """预注册所有内置工具（func 先设为 None，由 API 层注入实际实现）"""

        # --- SEARCH ---
        self.register(Tool(
            name="search_company_info",
            description="搜索企业公开信息，包括工商注册、社保缴纳、劳动仲裁、行政处罚等记录。",
            parameters={
                "type": "object",
                "properties": {
                    "company_name": {
                        "type": "string",
                        "description": "企业全称或统一社会信用代码",
                    },
                    "query_type": {
                        "type": "string",
                        "enum": ["basic", "social_security", "labor_arbitration", "punishment", "all"],
                        "description": "查询类型：basic=基础工商信息, social_security=社保信息, labor_arbitration=劳动仲裁, punishment=行政处罚, all=全部",
                        "default": "all",
                    },
                },
                "required": ["company_name"],
            },
            category="search",
        ))

        self.register(Tool(
            name="web_search",
            description="通用网络搜索，获取最新的公开信息、新闻、政策等。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            category="search",
        ))

        # --- PARSE ---
        self.register(Tool(
            name="parse_job",
            description="解析岗位链接或文本，提取公司名称、职位、薪资、要求等结构化信息。",
            parameters={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "岗位链接 URL 或岗位描述文本",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["url", "text", "auto"],
                        "description": "输入类型",
                        "default": "auto",
                    },
                },
                "required": ["input"],
            },
            category="parse",
        ))

        self.register(Tool(
            name="build_profile",
            description="从对话中提取或更新用户求职画像，包括技能、经验、期望薪资、意向行业等。",
            parameters={
                "type": "object",
                "properties": {
                    "conversation_text": {
                        "type": "string",
                        "description": "用户与助手的对话内容，用于提取画像信息",
                    },
                    "existing_profile": {
                        "type": "object",
                        "description": "已有的用户画像（首次为空），新信息会合并进去",
                    },
                },
                "required": ["conversation_text"],
            },
            category="parse",
        ))

        # --- ANALYZE ---
        self.register(Tool(
            name="analyze_job_risk",
            description="对企业或岗位进行风险评估，包括经营风险、劳动纠纷风险、行业风险等多维度分析。",
            parameters={
                "type": "object",
                "properties": {
                    "company_name": {
                        "type": "string",
                        "description": "企业名称",
                    },
                    "job_info": {
                        "type": "object",
                        "description": "岗位结构化信息（由 parse_job 输出）",
                    },
                },
                "required": ["company_name"],
            },
            category="analyze",
        ))

        self.register(Tool(
            name="match_jobs",
            description="将用户画像与岗位库进行匹配，计算匹配度分数并排序推荐。",
            parameters={
                "type": "object",
                "properties": {
                    "user_profile": {
                        "type": "object",
                        "description": "用户求职画像",
                    },
                    "job_list": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "待匹配的岗位列表",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回前 K 个最匹配的岗位",
                        "default": 10,
                    },
                },
                "required": ["user_profile", "job_list"],
            },
            category="analyze",
        ))

        # --- GENERATE ---
        self.register(Tool(
            name="generate_resume",
            description="根据用户画像和目标岗位，生成定制化的求职简历。",
            parameters={
                "type": "object",
                "properties": {
                    "user_profile": {
                        "type": "object",
                        "description": "用户求职画像",
                    },
                    "job_info": {
                        "type": "object",
                        "description": "目标岗位的结构化信息",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["standard", "creative", "technical", "management"],
                        "description": "简历风格",
                        "default": "standard",
                    },
                },
                "required": ["user_profile", "job_info"],
            },
            category="generate",
        ))


# 全局单例
tool_registry = ToolRegistry()
