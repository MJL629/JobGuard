"""Executable Agent tool registry with safety and HITL metadata."""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.agents.tools.career_tools import (
    analyze_job_requirements,
    build_company_verification_plan,
    generate_targeted_resume,
    inspect_profile_gaps,
    recommend_jobs_for_profile,
    recommend_learning_resources,
    search_job_database,
)
from app.agents.tools.company_evidence import search_company_info

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """One callable capability and its execution policy."""

    name: str
    description: str
    parameters: dict
    func: Optional[Callable] = None
    category: str = "general"
    execution_mode: str = "read_only"
    risk_level: str = "low"
    requires_confirmation: bool = False
    inject_user_id: bool = False
    expose_via_mcp: bool = True

    @property
    def is_available(self) -> bool:
        return self.func is not None


class ToolRegistry:
    """Register, describe, validate and execute real tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._register_builtin_tools()

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            logger.warning("[ToolRegistry] 工具 '%s' 已存在，将被覆盖", tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        return list(self._tools.values())

    def list_by_category(self, category: str) -> list[Tool]:
        return [item for item in self.list_available() if item.category == category]

    def list_available(self) -> list[Tool]:
        return [item for item in self._tools.values() if item.is_available]

    def list_mcp_tools(self) -> list[Tool]:
        return [item for item in self.list_available() if item.expose_via_mcp]

    def list_categories(self) -> list[str]:
        return sorted({item.category for item in self.list_available()})

    def get_openai_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": item.name,
                    "description": item.description,
                    "parameters": item.parameters,
                },
            }
            for item in self.list_available()
        ]

    def get_tools_description(self) -> str:
        lines: list[str] = []
        for category in self.list_categories():
            lines.append(f"## {category.upper()}")
            for item in self.list_by_category(category):
                lines.append(f"- {item.name}: {item.description}")
                lines.append(f"  参数: {json.dumps(item.parameters, ensure_ascii=False)}")
                lines.append(
                    f"  执行策略: {item.execution_mode}; 风险={item.risk_level}; "
                    f"人工确认={'需要' if item.requires_confirmation else '不需要'}"
                )
        return "\n".join(lines)

    def get_tool_names(self) -> list[str]:
        return [item.name for item in self.list_available()]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        user_id: int | None = None,
        confirmed: bool = False,
    ) -> Any:
        tool = self.get(name)
        if not tool or not tool.is_available:
            raise KeyError("工具不存在或尚未接通")
        if tool.requires_confirmation and not confirmed:
            return {
                "tool_name": name,
                "status": "confirmation_required",
                "message": "此操作会写入业务数据，请用户确认后再执行。",
            }
        supplied = dict(arguments or {})
        self._validate_arguments(tool, supplied)
        if tool.inject_user_id:
            if user_id is None:
                raise PermissionError("此工具必须在登录态下执行")
            supplied["user_id"] = user_id
        result = tool.func(**supplied)
        if inspect.isawaitable(result):
            result = await result
        return result

    @staticmethod
    def _validate_arguments(tool: Tool, arguments: dict[str, Any]) -> None:
        schema = tool.parameters or {}
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        missing = sorted(required - set(arguments))
        if missing:
            raise ValueError(f"缺少必填参数：{', '.join(missing)}")
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise ValueError(f"不支持的参数：{', '.join(unknown)}")
        for key, value in arguments.items():
            spec = properties.get(key) or {}
            expected = spec.get("type")
            if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"参数 {key} 必须是整数")
            if expected == "string" and not isinstance(value, str):
                raise ValueError(f"参数 {key} 必须是字符串")
            if "enum" in spec and value not in spec["enum"]:
                raise ValueError(f"参数 {key} 不在允许范围内")

    def _register_builtin_tools(self) -> None:
        object_schema = lambda properties, required=(): {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        }

        self.register(Tool(
            name="search_company_info",
            description="查询已落库的企业证据；每条事实包含来源，缺失字段保持 unknown。",
            parameters=object_schema({
                "company_name": {"type": "string", "description": "企业全称"},
                "query_type": {
                    "type": "string",
                    "enum": ["basic", "social_security", "labor_arbitration", "punishment", "official_jobs", "all"],
                    "default": "all",
                },
            }, ["company_name"]),
            func=search_company_info,
            category="evidence",
        ))
        self.register(Tool(
            name="search_job_database",
            description="搜索 MySQL 中仍有效的真实岗位并返回原始来源链接。",
            parameters=object_schema({
                "keywords": {"type": "string", "default": ""},
                "location": {"type": "string", "default": ""},
                "limit": {"type": "integer", "default": 10},
                "source_kind": {
                    "type": "string",
                    "enum": ["all", "official", "job_board"],
                    "default": "all",
                },
            }),
            func=search_job_database,
            category="search",
        ))
        self.register(Tool(
            name="analyze_job_requirements",
            description="从已保存岗位的 JD 原文提取技能与要求，不推断企业风险。",
            parameters=object_schema({"job_id": {"type": "integer"}}, ["job_id"]),
            func=analyze_job_requirements,
            category="analyze",
        ))
        self.register(Tool(
            name="inspect_profile_gaps",
            description="检查当前登录用户画像的证据覆盖和下一步追问，不返回简历原文。",
            parameters=object_schema({}),
            func=inspect_profile_gaps,
            category="profile",
            inject_user_id=True,
            expose_via_mcp=False,
        ))
        self.register(Tool(
            name="recommend_jobs_for_profile",
            description="用当前登录用户的持久化画像对真实岗位库进行可解释评分。",
            parameters=object_schema({"limit": {"type": "integer", "default": 10}}),
            func=recommend_jobs_for_profile,
            category="analyze",
            inject_user_id=True,
            expose_via_mcp=False,
        ))
        self.register(Tool(
            name="recommend_learning_resources",
            description="按主题返回经过人工登记的公开学习资源链接，不生成虚假链接。",
            parameters=object_schema({
                "topic": {"type": "string", "default": ""},
                "limit": {"type": "integer", "default": 4},
            }),
            func=recommend_learning_resources,
            category="search",
        ))
        self.register(Tool(
            name="build_company_verification_plan",
            description="生成企业官方核验清单；登录、验证码和主体消歧必须由用户人工完成。",
            parameters=object_schema({"company_name": {"type": "string"}}, ["company_name"]),
            func=build_company_verification_plan,
            category="evidence",
        ))
        self.register(Tool(
            name="generate_targeted_resume",
            description="基于已保存画像和目标岗位生成并持久化定向简历，执行前必须人工确认。",
            parameters=object_schema({
                "job_id": {"type": "integer"},
                "template_id": {"type": "string", "default": "template-01"},
                "max_projects": {"type": "integer", "default": 3},
            }, ["job_id"]),
            func=generate_targeted_resume,
            category="generate",
            execution_mode="write",
            risk_level="medium",
            requires_confirmation=True,
            inject_user_id=True,
            expose_via_mcp=False,
        ))


tool_registry = ToolRegistry()
