"""JobGuard MCP server.

The MCP surface and the in-app Agent call the same source-bound tool
implementation.  The server never accepts browser credentials, cookies or
CAPTCHA solutions; it only reads evidence that has already been normalized in
MySQL.

Run with::

    python -m app.mcp_server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.agents.tools.career_tools import (
    analyze_job_requirements,
    build_company_verification_plan,
    recommend_learning_resources,
    search_job_database,
)
from app.agents.tools.company_evidence import search_company_info


jobguard_mcp = FastMCP(
    "JobGuard Evidence Tools",
    instructions=(
        "Use these tools to read source-bound job and company evidence. "
        "Missing facts must remain unknown; never infer social-insurance, "
        "labor-dispute, registry-risk or reputation numbers without sources."
    ),
    json_response=True,
)


@jobguard_mcp.tool(
    name="search_company_info",
    description=(
        "查询企业的已落库证据，返回核验维度、缺失维度和可点击来源。"
        "没有证据时返回 no_evidence，不使用模型记忆补全。"
    ),
)
async def mcp_search_company_info(company_name: str, query_type: str = "all") -> dict:
    """Search source-bound company evidence by full company name."""
    return await search_company_info(company_name=company_name, query_type=query_type)


@jobguard_mcp.tool(
    name="search_job_database",
    description="搜索 JobGuard MySQL 中有效岗位并返回来源链接，不读取任何用户画像。",
)
async def mcp_search_job_database(
    keywords: str = "", location: str = "", limit: int = 10, source_kind: str = "all"
) -> dict:
    return await search_job_database(
        keywords=keywords, location=location, limit=limit, source_kind=source_kind
    )


@jobguard_mcp.tool(
    name="analyze_job_requirements",
    description="分析已落库岗位的 JD 原文和技能要求，不推断缺失企业事实。",
)
async def mcp_analyze_job_requirements(job_id: int) -> dict:
    return await analyze_job_requirements(job_id=job_id)


@jobguard_mcp.tool(
    name="recommend_learning_resources",
    description="返回经过人工登记的公开技术学习资源及可点击来源。",
)
async def mcp_recommend_learning_resources(topic: str = "", limit: int = 4) -> dict:
    return await recommend_learning_resources(topic=topic, limit=limit)


@jobguard_mcp.tool(
    name="build_company_verification_plan",
    description="为企业生成官方核验清单；需要登录或验证码的步骤保持人工执行。",
)
async def mcp_build_company_verification_plan(company_name: str) -> dict:
    return await build_company_verification_plan(company_name=company_name)


@jobguard_mcp.tool(
    name="get_jobguard_tool_status",
    description="返回 JobGuard 工具适配器状态和真实性保护策略。",
)
async def get_jobguard_tool_status() -> dict:
    """Describe the currently supported evidence adapters."""
    return {
        "status": "ready",
        "tools": [
            "search_company_info",
            "search_job_database",
            "analyze_job_requirements",
            "recommend_learning_resources",
            "build_company_verification_plan",
        ],
        "adapters": {
            "mysql_company_evidence": "ready",
            "beijing_open_data": "available_via_import",
            "gsxt": "manual_handoff",
        },
        "policy": "缺少来源的企业事实返回 unknown，禁止模型补全",
    }


def main() -> None:
    jobguard_mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
