"""
企业背调 Agent

职责：
1. 通过 WebSearch 实时检索企业信息（社保人数、劳动争议、网络口碑等）
2. 分析 JD 话术，识别加班暗示、虚假宣传、刷 KPI 嫌疑
3. 结合用户画像的工作强度偏好，给出个性化推荐指数
4. 输出结构化风险评估报告

数据优先级：用户提供的岗位信息 > 实时检索结果 > 知识库历史数据
"""

import json
import logging
from typing import Optional, TYPE_CHECKING

from app.llm.gateway import llm_gateway
from app.rag.company_kb import company_kb
from app.agents.tools.company_evidence import search_company_info

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ─── 真实 WebSearch 集成 ─────────────────────────────────

async def _real_web_search(query: str, max_results: int = 5) -> str:
    """
    企业联网数据源尚未接入。禁止用 LLM 记忆冒充实时搜索结果。
    """
    logger.info(f"[WebSearch] 已阻止无来源查询: {query}")
    return "[未接入可核验联网数据源]"


async def _batch_web_search(queries: list[str]) -> list[str]:
    """批量并发执行网络搜索"""
    import asyncio
    tasks = [_real_web_search(q) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [
        r if not isinstance(r, Exception) else f"[搜索异常: {str(r)[:100]}]"
        for r in results
    ]

# ─── Prompt 模板 ─────────────────────────────────────────────────────────

# 阶段 1：JD 话术分析（用主力模型，速度快）
JD_ANALYSIS_PROMPT = """你是一位资深的招聘市场分析专家。请分析以下岗位描述，识别潜在的"话术陷阱"。

## 岗位信息
- 公司：{company_name}
- 岗位：{job_title}
- 薪资：{salary_min}-{salary_max}元/月
- 地点：{location}
- 岗位描述：{jd_text}
- 福利：{benefits}

## 分析维度

### 1. 加班暗示识别
以下话术通常暗示加班严重：
- "抗压能力强" → 工作压力大
- "拥抱变化" → 业务不稳定，经常调整
- "弹性工作制" → 可能意味着无偿加班（需结合上下文）
- "有创业精神" → 可能需要 996
- "以结果为导向" → 只看结果不计工时
- "能接受高强度工作" → 明确告知会加班
- "大小周" / "单休" → 明确告知非双休

### 2. 薪资真实性评估
- 薪资范围是否过大（如 10K-30K，实际大概率是 10K）
- 结合岗位要求判断薪资是否合理
- 是否有"薪资面议"等模糊表述

### 3. 虚假宣传/刷 KPI 判断
- 岗位描述过于宽泛/模板化 → 可能是假岗位
- 要求极低但薪资极高 → 虚假宣传
- 描述与岗位名称不匹配 → 挂羊头卖狗肉
- 只提福利不提工作内容 → 可能是传销/培训机构

### 4. 工作制度推断
- 从上下文字段推断单休还是双休
- 从福利描述推断社保公积金情况

## 输出格式
```json
{{
  "overtime_signals": ["识别到的加班暗示话术1", "话术2"],
  "overtime_risk": "low/medium/high",
  "salary_authenticity": "合理/偏高/偏低/薪资范围过大可能虚标/疑似虚假",
  "salary_analysis": "薪资分析说明",
  "fake_job_suspicion": "low/medium/high",
  "fake_job_reasons": ["疑似原因1"],
  "kpi_brushing_suspicion": "low/medium/high",
  "work_schedule_inferred": "推断的工作制度（双休/大小周/单休/未知）",
  "jd_quality": "详细专业/模板化/过于简略/可疑",
  "jd_analysis_summary": "JD 分析总结（1-2句话）"
}}
```

只输出 JSON。"""


# 阶段 2：综合风险评估（用 DeepSeek V3 推理模型）
RISK_ASSESSMENT_PROMPT = """你是一位企业风险评估专家。请综合以下信息，给出该岗位的全面风险评估。

## 岗位信息
{job_info}

## JD 分析结果
{jd_analysis}

## 企业公开信息
{company_info}

## 网络口碑
{online_reputation}

## 用户画像（用于个性化评估）
{user_profile}

## 评估要求
综合以上所有信息，从以下维度给出评估：

1. **社保/经营风险**：参保人数是否合理、是否有经营异常
2. **法律风险**：是否有劳动争议、类型和严重程度
3. **口碑风险**：员工评价、网络口碑倾向
4. **JD 风险**：是否存在虚假宣传、加班暗示
5. **薪资真实性**：结合用户期望，判断薪资是否合理
6. **匹配度**：该岗位与用户画像的匹配程度
7. **个性化建议**：结合用户的工作强度偏好给出建议

## 输出格式
```json
{{
  "risk_level": "low/medium/high/critical",
  "recommendation_index": 1-5的整数,
  "recommendation_text": "推荐/谨慎考虑/不太推荐/强烈不推荐",
  "dimensions": {{
    "social_insurance": {{
      "participants": "参保人数或null",
      "trend": "趋势分析",
      "assessment": "评估说明",
      "score": 1-5风险分（5=最安全）
    }},
    "labor_disputes": {{
      "total_cases": "劳动争议数量或null",
      "recent_12m": "近12个月数量",
      "main_types": ["类型1"],
      "assessment": "评估说明",
      "score": 1-5风险分
    }},
    "business_risk": {{
      "abnormal_operations": "经营异常数量",
      "administrative_penalties": "行政处罚数量",
      "assessment": "评估说明",
      "score": 1-5风险分
    }},
    "online_reputation": {{
      "overall_sentiment": "正面偏多/中性/负面偏多/严重负面",
      "common_complaints": ["常见投诉1"],
      "highlights": ["正面评价1"],
      "assessment": "评估说明",
      "score": 1-5风险分
    }},
    "jd_analysis": {{
      "overtime_risk": "low/medium/high",
      "fake_job_suspicion": "low/medium/high",
      "kpi_brushing_suspicion": "low/medium/high",
      "salary_authenticity": "评估",
      "assessment": "评估说明",
      "score": 1-5风险分
    }},
    "match_with_user": {{
      "skill_match": "匹配度描述",
      "salary_match": "匹配度描述",
      "location_match": "匹配度描述",
      "intensity_match": "是否匹配用户工作强度偏好",
      "score": 1-5匹配分（5=最匹配）
    }}
  }},
  "overall_score": 综合风险分 0-10（0=最安全）,
  "summary": "综合评估总结（2-3句话）",
  "red_flags": ["需要警惕的红旗信号"],
  "positive_points": ["值得考虑的亮点"],
  "advice": "给用户的个性化建议"
}}
```

只输出 JSON。"""


# 阶段 3：生成用户友好的分析报告
REPORT_GENERATION_PROMPT = """你是一位贴心的求职顾问。请将以下企业背调结果转化为用户友好的分析报告。

## 分析结果
{assessment_json}

## 要求
- 用平易近人的语言，像朋友在帮你分析一样
- 突出最重要的风险和亮点
- 给出明确的投递建议
- 如果风险高，解释清楚为什么
- 如果值得投，说明为什么

## 输出格式
用 Markdown 格式输出，包含：
1. 📊 综合评分（推荐指数：⭐×N）
2. ⚠️ 风险提示（如有）
3. ✅ 亮点（如有）
4. 📋 详细分析（社保/法律/口碑/JD）
5. 💡 投递建议

直接输出报告内容，不需要 JSON。"""


# ─── Agent 核心类 ────────────────────────────────────────────────────────

class BackgroundCheckAgent:
    """企业背调 Agent"""

    # ─── 主入口 ───────────────────────────────────────────────────────

    async def investigate(
        self,
        job_info: dict,
        user_profile: Optional[dict] = None,
        db: Optional["Session"] = None,
    ) -> dict:
        """
        对企业/岗位进行全面背调（使用真实 WebSearch）

        Args:
            job_info: 岗位解析 Agent 输出的结构化岗位信息
            user_profile: 用户画像（用于个性化评估）

        Returns:
            完整的风险评估报告 dict
        """
        company_name = job_info.get("company_name", "未知企业")
        job_title = job_info.get("job_title", "未知岗位")
        logger.info(f"[BackgroundCheck] 开始背调：{company_name} - {job_title}")

        # 1. 先查知识库（历史分析记录）
        kb_results = await self._search_knowledge_base(company_name, job_title)

        # 2. JD 话术分析（主力模型，快）
        jd_analysis = await self._analyze_jd(job_info)
        logger.info(f"[BackgroundCheck] JD分析完成，加班风险={jd_analysis.get('overtime_risk')}")

        # 3. 从 MySQL 读取已经绑定来源的企业证据。联网失败不会触发模型补全。
        if db is not None:
            try:
                evidence_summary = await search_company_info(
                    company_name=company_name,
                    query_type="all",
                    db=db,
                )
            except Exception as exc:
                logger.warning("[BackgroundCheck] search_company_info 工具失败: %s", exc)
                evidence_summary = {
                    "tool_name": "search_company_info",
                    "status": "failed",
                    "verification_status": "unverified",
                    "sources": [],
                    "dimensions": {},
                    "evidence": [],
                    "error": "企业证据查询暂不可用",
                }
        else:
            evidence_summary = {
                "tool_name": "search_company_info",
                "status": "skipped_no_database",
                "verification_status": "unverified",
                "sources": [],
                "dimensions": {},
                "evidence": [],
            }

        # 4. 先生成只依赖 JD 的确定性评估，再逐项覆盖确有来源的企业维度。
        assessment = self._build_evidence_limited_assessment(
            jd_analysis,
            user_profile,
            job_info,
        )
        assessment = self._apply_stored_evidence(assessment, evidence_summary)
        assessment = self._apply_live_queries(assessment, evidence_summary)
        assessment["tool_trace"] = [{
            "tool_name": evidence_summary.get("tool_name", "search_company_info"),
            "status": evidence_summary.get("status", "unknown"),
            "verification_status": evidence_summary.get("verification_status", "unverified"),
            "verified_dimensions": evidence_summary.get("verified_dimensions", []),
            "missing_dimensions": evidence_summary.get("missing_dimensions", []),
            "source_count": len(evidence_summary.get("sources", [])),
            "live_queries": evidence_summary.get("live_queries", []),
        }]
        logger.info(f"[BackgroundCheck] 风险评估完成，等级={assessment.get('risk_level')}")

        # 5. 合并知识库数据（实时结果优先）
        if assessment.get("verification_status") != "jd_only":
            assessment = self._merge_with_kb(assessment, kb_results)

        # 6. 使用确定性报告，避免生成阶段重新引入无来源事实。
        report = self._generate_fallback_report(assessment)

        # 7. 存入知识库
        await self._save_to_kb(company_name, job_title, assessment, report)

        return {
            "company_name": company_name,
            "job_title": job_title,
            "risk_level": assessment.get("risk_level", "unknown"),
            "recommendation_index": assessment.get("recommendation_index", 3),
            "recommendation_text": assessment.get("recommendation_text", "无法判断"),
            "dimensions": assessment.get("dimensions", {}),
            "overall_score": assessment.get("overall_score", 5),
            "summary": assessment.get("summary", ""),
            "red_flags": assessment.get("red_flags", []),
            "positive_points": assessment.get("positive_points", []),
            "advice": assessment.get("advice", ""),
            "report": report,
            "verification_status": assessment.get("verification_status", "jd_only"),
            "sources": assessment.get("sources", []),
            "verification_tasks": assessment.get("verification_tasks", []),
            "tool_trace": assessment.get("tool_trace", []),
        }

    @staticmethod
    def _apply_stored_evidence(assessment: dict, evidence_summary: dict) -> dict:
        """Apply only source-backed facts; an official job never proves company risk facts."""
        evidence_rows = evidence_summary.get("evidence") or []
        if not evidence_rows:
            return assessment

        company_fact_types = {
            "registry",
            "operating_abnormality",
            "administrative_penalty",
            "social_insurance",
            "labor_dispute",
        }
        verified_fact_rows = [
            item
            for item in evidence_rows
            if item.get("is_verified") and item.get("evidence_type") in company_fact_types
        ]
        official_job_rows = [
            item
            for item in evidence_rows
            if item.get("is_verified") and item.get("evidence_type") == "official_job"
        ]
        dimensions = assessment.setdefault("dimensions", {})
        stored_dimensions = evidence_summary.get("dimensions") or {}

        social = stored_dimensions.get("social_insurance") or {}
        if social.get("verified"):
            facts = social.get("facts") or {}
            participants = facts.get("participants")
            year = facts.get("reporting_year")
            dimensions["social_insurance"] = {
                "participants": participants,
                "reporting_year": year,
                "trend": "来源未提供连续年度数据，不能判断趋势",
                "assessment": (
                    f"官方来源记录{year or '对应年度'}参保人数为{participants}人。"
                    if participants is not None
                    else "已保存社保官方来源，但该来源未提供可用参保人数字段。"
                ),
                "score": None,
                "verified": True,
                "evidence_ids": social.get("evidence_ids", []),
            }

        disputes = stored_dimensions.get("labor_disputes") or {}
        if disputes.get("verified"):
            facts = disputes.get("facts") or {}
            case_count = facts.get("case_count")
            dimensions["labor_disputes"] = {
                "total_cases": case_count,
                "recent_12m": None,
                "main_types": [facts["cause"]] if facts.get("cause") else [],
                "assessment": (
                    f"保存的官方来源在其查询范围内记录{case_count}起相关案件；结果数不等同于企业全部历史案件。"
                    if case_count is not None
                    else "已保存公开裁判来源，但未提供可去重的案件数量。"
                ),
                "score": None,
                "verified": True,
                "evidence_ids": disputes.get("evidence_ids", []),
            }

        registry = stored_dimensions.get("registry") or {}
        business = stored_dimensions.get("business_risk") or {}
        if registry.get("verified") or business.get("verified"):
            facts = {**(registry.get("facts") or {}), **(business.get("facts") or {})}
            status = facts.get("registration_status")
            abnormal = facts.get("abnormal_count")
            penalties = facts.get("penalty_count")
            statements = []
            if status is not None:
                statements.append(f"登记状态：{status}")
            if abnormal is not None:
                statements.append(f"来源记录经营异常{abnormal}项")
            if penalties is not None:
                statements.append(f"来源记录行政处罚{penalties}项")
            dimensions["business_risk"] = {
                "registration_status": status,
                "abnormal_operations": abnormal,
                "administrative_penalties": penalties,
                "assessment": "；".join(statements) if statements else "已保存工商官方来源，但未提取风险数量字段。",
                "score": None,
                "verified": True,
                "evidence_ids": list(dict.fromkeys([
                    *(registry.get("evidence_ids") or []),
                    *(business.get("evidence_ids") or []),
                ])),
            }

        reputation = stored_dimensions.get("online_reputation") or {}
        if reputation.get("evidence_count"):
            dimensions["online_reputation"] = {
                "overall_sentiment": "有来源但未作统计推断",
                "common_complaints": [],
                "highlights": [],
                "assessment": "已保存口碑来源，仅作为线索展示；不能据零散样本推断整体员工口碑。",
                "score": None,
                "verified": False,
                "evidence_ids": reputation.get("evidence_ids", []),
            }

        if official_job_rows:
            dimensions["official_jobs"] = {
                "verified": True,
                "evidence_count": len(official_job_rows),
                "assessment": f"北京市公共数据开放平台保存了该企业{len(official_job_rows)}条招聘岗位记录；这只证明招聘来源，不证明企业无风险。",
                "score": None,
                "evidence_ids": [item.get("id") for item in official_job_rows],
            }
            assessment.setdefault("positive_points", []).append(
                "岗位可追溯到北京市公共数据开放平台的单位招聘数据"
            )

        existing_sources = assessment.get("sources") or []
        evidence_sources = evidence_summary.get("sources") or []
        assessment["sources"] = list({
            (item.get("url"), item.get("supports")): item
            for item in [*existing_sources, *evidence_sources]
            if item.get("url")
        }.values())
        if verified_fact_rows:
            assessment["verification_status"] = "official_company_evidence"
            assessment["summary"] = (
                f"已读取{len(verified_fact_rows)}条企业官方证据，并逐项标注来源。"
                + assessment.get("summary", "")
            )
        elif official_job_rows:
            assessment["verification_status"] = "official_job_evidence"
            assessment["summary"] = (
                "岗位来源已由北京市官方开放数据核验；社保、劳动争议、工商风险和口碑仍未核验。 "
                + assessment.get("summary", "")
            )
        return assessment

    @staticmethod
    def _apply_live_queries(assessment: dict, evidence_summary: dict) -> dict:
        """Expose live-query outcomes without converting absence into a clean bill."""
        live_queries = evidence_summary.get("live_queries") or []
        if not live_queries:
            return assessment

        dimensions = assessment.setdefault("dimensions", {})
        by_adapter = {item.get("adapter"): item for item in live_queries}
        transactions = by_adapter.get("national_public_resource_transactions") or {}
        transaction_status = transactions.get("status")
        transaction_count = transactions.get("result_count", 0)
        if transaction_status == "success_with_results":
            assessment_text = (
                f"已实时查询全国公共资源交易平台，命中企业全称，返回"
                f"{transaction_count}条主体记录；成交项目数仅按平台当前返回值展示。"
            )
        elif transaction_status == "success_no_results":
            assessment_text = (
                "已实时查询全国公共资源交易平台，当前未命中该企业全称。"
                "无结果不代表企业不存在，也不代表企业没有其他经营活动。"
            )
        else:
            assessment_text = "全国公共资源交易平台本次暂时不可访问，未把失败查询解释为无记录。"
        dimensions["public_transactions"] = {
            "verified": transaction_status == "success_with_results",
            "status": transaction_status or "not_queried",
            "record_count": transaction_count,
            "assessment": assessment_text,
            "score": None,
        }

        mentions = by_adapter.get("bing_public_web_search") or {}
        mentions_status = mentions.get("status")
        mentions_count = mentions.get("result_count", 0)
        reputation = dimensions.setdefault("online_reputation", {})
        if mentions_status == "success_with_results":
            reputation.update({
                "status": "live_results",
                "assessment": (
                    f"已实时检索公开网页，保留{mentions_count}条包含企业全称的来源链接。"
                    "这些结果仅是核验线索，不能代表整体员工口碑。"
                ),
                "verified": False,
            })
        elif mentions_status == "success_no_results":
            reputation.update({
                "status": "queried_no_results",
                "assessment": (
                    "已实时检索公开网页，当前未找到包含企业全称的结果。"
                    "无结果不等于口碑良好或企业无风险。"
                ),
                "verified": False,
            })
        else:
            reputation.update({
                "status": "temporarily_unavailable",
                "assessment": "公开网页检索本次暂时不可用，未生成任何口碑结论。",
                "verified": False,
            })

        successful_queries = [
            item for item in live_queries
            if item.get("status") in {"success_with_results", "success_no_results"}
        ]
        if successful_queries:
            if assessment.get("verification_status") in {"jd_only", "jd_source_fetched"}:
                assessment["verification_status"] = "live_sources_queried"
            previous_summary = assessment.get("summary", "")
            previous_summary = previous_summary.replace(
                "岗位来源已由北京市官方开放数据核验；社保、劳动争议、工商风险和口碑仍未核验。 ",
                "岗位来源已由北京市官方开放数据核验。 ",
            ).replace(
                "企业社保、劳动争议、工商风险和网络口碑均未联网核验，不提供具体数字。",
                "社保人数无公开统一接口，工商与裁判文书受访问控制；公开网页和公共交易来源已实时查询。",
            )
            assessment["summary"] = (
                f"已执行{len(successful_queries)}个实时外部来源查询；无结果不等于无风险。 "
                + previous_summary
            )

        sources = assessment.get("sources") or []
        query_sources = [
            source for source in (evidence_summary.get("sources") or [])
            if source.get("status") in {
                "success_with_results", "success_no_results", "temporarily_unavailable"
            }
        ]
        assessment["sources"] = list({
            item.get("url"): item for item in [*sources, *query_sources] if item.get("url")
        }.values())
        return assessment

    def _build_evidence_limited_assessment(
        self,
        jd_analysis: dict,
        user_profile: Optional[dict] = None,
        job_info: Optional[dict] = None,
    ) -> dict:
        """仅根据用户提供的 JD 原文输出风险，不伪造企业外部事实。"""
        job_info = job_info or {}
        overtime_risk = jd_analysis.get("overtime_risk", "low")
        fake_risk = jd_analysis.get("fake_job_suspicion", "low")
        kpi_risk = jd_analysis.get("kpi_brushing_suspicion", "low")
        risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        highest = max(
            (overtime_risk, fake_risk, kpi_risk),
            key=lambda value: risk_order.get(value, 0),
        )
        risk_level = "high" if highest in {"high", "critical"} else ("medium" if highest == "medium" else "low")
        recommendation_index = {"low": 4, "medium": 3, "high": 2}[risk_level]

        red_flags = list(jd_analysis.get("fake_job_reasons", []))
        if not red_flags and jd_analysis.get("overtime_signals"):
            red_flags.append("JD 中存在可能暗示高强度工作的词语")

        preferences = (user_profile or {}).get("preferences", {})
        if (
            preferences.get("labor_intensity") == "排斥高强度"
            and overtime_risk in {"medium", "high"}
        ):
            red_flags.append("该 JD 的工作强度信号与你明确排斥高强度工作的偏好冲突")
        schedule = jd_analysis.get("work_schedule_inferred", "")
        if preferences.get("weekend_preference") == "必须双休" and any(
            item in schedule for item in ("单休", "大小周")
        ):
            red_flags.append(f"该 JD 出现{schedule}，与你的必须双休条件冲突")

        source_evidence = job_info.get("source_evidence") or {}
        sources = []
        if source_evidence.get("final_url"):
            sources.append({
                "title": source_evidence.get("page_title") or "岗位公开页面",
                "url": source_evidence["final_url"],
                "fetched_at": source_evidence.get("fetched_at"),
                "status": "fetched",
                "supports": "仅支持岗位原文与页面当时展示的信息",
            })
        company_name = job_info.get("company_name") or "该企业"
        verification_tasks = self._official_verification_tasks(company_name)

        positive_points = []
        if job_info.get("salary_min") and job_info.get("salary_max"):
            positive_points.append("JD 提供了明确薪资范围，但固定薪资、绩效占比和职级仍需确认")
        if job_info.get("location"):
            positive_points.append(f"JD 提供了工作地点：{job_info['location']}")
        if len(str(job_info.get("jd_raw_text") or job_info.get("job_description") or "")) >= 200:
            positive_points.append("岗位职责和要求的信息量相对完整，便于逐条核实")

        return {
            "risk_level": risk_level,
            "recommendation_index": recommendation_index,
            "recommendation_text": {
                "low": "JD 暂未发现明显红旗，仍需面试核实",
                "medium": "存在需进一步核实的 JD 信号",
                "high": "发现高风险 JD 信号，建议谨慎",
            }[risk_level],
            "dimensions": {
                "social_insurance": {
                    "participants": None,
                    "trend": "未核验",
                    "status": "not_publicly_available",
                    "assessment": "当前没有无需授权且稳定公开的全国企业参保人数接口，系统不会猜测社保人数。",
                    "score": None,
                    "verified": False,
                },
                "labor_disputes": {
                    "total_cases": None,
                    "recent_12m": None,
                    "main_types": [],
                    "status": "access_controlled",
                    "assessment": "裁判文书官方查询受登录和访问控制限制，当前 Agent 不绕过验证；不能提供劳动争议数量。",
                    "score": None,
                    "verified": False,
                },
                "business_risk": {
                    "abnormal_operations": None,
                    "administrative_penalties": None,
                    "status": "access_controlled",
                    "assessment": "国家企业信用信息公示系统需要交互验证，当前 Agent 不绕过验证码；工商风险需通过下方官方入口人工核验。",
                    "score": None,
                    "verified": False,
                },
                "online_reputation": {
                    "overall_sentiment": "未核验",
                    "common_complaints": [],
                    "highlights": [],
                    "status": "not_queried",
                    "assessment": "等待实时公开网页检索；只保留包含企业全称的来源，不直接概括员工口碑。",
                    "score": None,
                    "verified": False,
                },
                "jd_analysis": {
                    **jd_analysis,
                    "assessment": jd_analysis.get("jd_analysis_summary", ""),
                    "score": {"low": 4, "medium": 3, "high": 1}.get(risk_level, 3),
                    "verified": True,
                    "source": source_evidence.get("final_url") or "用户粘贴/上传的岗位描述",
                },
                "match_with_user": {
                    "assessment": "本阶段尚未计算画像匹配分。",
                    "score": None,
                    "verified": False,
                },
            },
            "overall_score": {"low": 2, "medium": 5, "high": 8}[risk_level],
            "summary": (
                ("系统已读取并分析公开岗位页面。" if sources else "当前报告仅分析用户提供的岗位描述。")
                + "企业社保、劳动争议、工商风险和网络口碑均未联网核验，不提供具体数字。"
                f" {jd_analysis.get('jd_analysis_summary', '')}"
            ).strip(),
            "red_flags": list(dict.fromkeys(red_flags)),
            "positive_points": positive_points,
            "advice": (
                "建议按以下顺序核实：1）让招聘方书面说明固定薪资、绩效占比和试用期折扣；"
                "2）确认日常下班时间、月均加班天数、调休与加班费；"
                "3）确认周末制度和紧急响应频率；"
                "4）用下方官方入口按企业全称核对登记状态、经营异常、行政处罚与公开裁判文书。"
            ),
            "verification_status": "jd_source_fetched" if sources else "jd_only",
            "sources": sources,
            "verification_tasks": verification_tasks,
        }

    @staticmethod
    def _official_verification_tasks(company_name: str) -> list[dict]:
        """提供免费官方人工核验入口，不把入口本身冒充为已经查到的结论。"""
        search_term = company_name.strip()
        return [
            {
                "dimension": "工商登记/经营异常",
                "title": "国家企业信用信息公示系统",
                "url": "https://www.gsxt.gov.cn/index.html",
                "search_term": search_term,
                "status": "manual_required",
                "instructions": "搜索企业全称，核对统一社会信用代码、登记状态、经营异常名录和行政处罚。",
            },
            {
                "dimension": "公共信用记录",
                "title": "信用中国",
                "url": "https://www.creditchina.gov.cn/",
                "search_term": search_term,
                "status": "manual_required",
                "instructions": "搜索企业全称，查看网站公开的行政管理与失信相关信息。",
            },
            {
                "dimension": "公开裁判文书",
                "title": "中国裁判文书网",
                "url": "https://wenshu.court.gov.cn/",
                "search_term": f"{search_term} 劳动争议",
                "status": "manual_required",
                "instructions": "登录后以企业全称为当事人关键词，并结合“劳动争议”等案由筛选；同一案件可能有多份文书，不可直接按结果数计案件数。",
            },
            {
                "dimension": "被执行/失信信息",
                "title": "中国执行信息公开网",
                "url": "https://zxgk.court.gov.cn/",
                "search_term": search_term,
                "status": "manual_required",
                "instructions": "按企业全称查询公开执行信息，并核对主体名称和统一社会信用代码，避免同名误判。",
            },
        ]

    # ─── JD 话术分析 ─────────────────────────────────────────────────

    async def _analyze_jd(self, job_info: dict) -> dict:
        """基于用户提供的 JD 原文做可复现规则分析，不生成原文不存在的事实。"""
        jd_text = str(job_info.get("jd_raw_text") or job_info.get("job_description") or "")
        overtime_phrases = [
            "抗压能力强", "能承受较大压力", "拥抱变化", "创业精神", "结果导向",
            "高强度工作", "大小周", "单休", "996", "随时响应", "服从加班",
        ]
        kpi_phrases = [
            "长期招聘", "急招", "大量招聘", "无需经验", "当天入职", "高薪轻松",
            "零基础高薪", "入职缴费", "培训费", "押金",
        ]
        overtime_signals = [phrase for phrase in overtime_phrases if phrase in jd_text]
        kpi_signals = [phrase for phrase in kpi_phrases if phrase in jd_text]

        salary_min = job_info.get("salary_min")
        salary_max = job_info.get("salary_max")
        salary_range_too_wide = bool(
            salary_min and salary_max and salary_min > 0 and salary_max / salary_min >= 2.5
        )

        if any(phrase in overtime_signals for phrase in ["单休", "996", "服从加班", "高强度工作"]):
            overtime_risk = "high"
        elif overtime_signals:
            overtime_risk = "medium"
        else:
            overtime_risk = "low"

        fake_suspicion = "high" if any(
            phrase in kpi_signals for phrase in ["入职缴费", "培训费", "押金", "零基础高薪"]
        ) else ("medium" if kpi_signals or salary_range_too_wide else "low")

        if "双休" in jd_text:
            schedule = "双休（仅依据 JD 文案，需面试确认）"
        elif "大小周" in jd_text:
            schedule = "大小周"
        elif "单休" in jd_text:
            schedule = "单休"
        else:
            schedule = "未知"

        reasons = []
        if overtime_signals:
            reasons.append("发现可能暗示高强度工作的原文词语：" + "、".join(overtime_signals))
        if kpi_signals:
            reasons.append("发现需进一步核实的招聘话术：" + "、".join(kpi_signals))
        if salary_range_too_wide:
            reasons.append("薪资上下限跨度达到 2.5 倍或以上，需确认固定薪资、绩效和职级范围")

        return {
            "overtime_signals": overtime_signals,
            "overtime_risk": overtime_risk,
            "salary_authenticity": "薪资范围过大，需核实" if salary_range_too_wide else "仅依据 JD 无法核验真实性",
            "salary_analysis": "；".join(reasons) if reasons else "未发现明确异常，但仍需面试核实",
            "fake_job_suspicion": fake_suspicion,
            "fake_job_reasons": reasons,
            "kpi_brushing_suspicion": "medium" if kpi_signals else "low",
            "work_schedule_inferred": schedule,
            "jd_quality": "过于简略" if len(jd_text.strip()) < 80 else "信息量尚可",
            "jd_analysis_summary": "；".join(reasons) if reasons else "未在 JD 原文中发现明确高风险话术。",
            "evidence_phrases": overtime_signals + kpi_signals,
        }

    # ─── 企业信息检索 ────────────────────────────────────────────────

    async def _search_company_info(self, company_name: str) -> str:
        """检索企业公开信息（真实 WebSearch）"""
        queries = [
            f"{company_name} 公司 社保人数 参保人数 天眼查",
            f"{company_name} 劳动仲裁 劳动争议 裁判文书",
            f"{company_name} 经营异常 行政处罚 工商信息",
        ]

        results = await _batch_web_search(queries)
        valid_results = [r for r in results if r and "[搜索" not in r]
        return "\n---\n".join(valid_results) if valid_results else "未获取到企业公开信息"

    async def _search_reputation(self, company_name: str) -> str:
        """检索网络口碑（真实 WebSearch）"""
        queries = [
            f"{company_name} 员工评价 工作体验 怎么样 脉脉 看准网",
            f"{company_name} 知乎 小红书 加班 工资 待遇",
            f"{company_name} 招聘 靠谱吗 值得去吗",
        ]

        results = await _batch_web_search(queries)
        valid_results = [r for r in results if r and "[搜索" not in r]
        return "\n---\n".join(valid_results) if valid_results else "未获取到网络口碑信息"

    # ─── 综合风险评估 ────────────────────────────────────────────────

    async def _assess_risk(
        self,
        job_info: dict,
        jd_analysis: dict,
        company_info: str,
        online_reputation: str,
        user_profile: Optional[dict] = None,
    ) -> dict:
        """使用 DeepSeek V3 进行综合风险评估"""
        # 格式化用户画像
        user_profile_str = "未提供用户画像"
        if user_profile:
            basic = user_profile.get("basic", {})
            prefs = user_profile.get("preferences", {})
            user_profile_str = json.dumps({
                "学历": basic.get("degree"),
                "期望薪资": f"{basic.get('expected_salary_min', 0)}-{basic.get('expected_salary_max', 0)}",
                "偏好城市": prefs.get("preferred_locations", []),
                "周末偏好": prefs.get("weekend_preference", "未设置"),
                "加班接受度": prefs.get("overtime_tolerance", "未设置"),
                "劳动强度": prefs.get("labor_intensity", "未设置"),
            }, ensure_ascii=False)

        prompt = RISK_ASSESSMENT_PROMPT.format(
            job_info=json.dumps(job_info, ensure_ascii=False, indent=2)[:2000],
            jd_analysis=json.dumps(jd_analysis, ensure_ascii=False, indent=2),
            company_info=company_info[:3000] if company_info else "未获取",
            online_reputation=online_reputation[:3000] if online_reputation else "未获取",
            user_profile=user_profile_str,
        )

        messages = [
            {"role": "system", "content": "你是一位企业风险评估专家。只输出 JSON。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat_reasoning(messages)
            return json.loads(self._clean_json(response))
        except Exception as e:
            logger.error(f"[BackgroundCheck] 风险评估失败: {e}")
            return {
                "risk_level": "medium",
                "recommendation_index": 3,
                "recommendation_text": "信息不足，建议进一步了解",
                "dimensions": {},
                "overall_score": 5,
                "summary": "由于信息获取不完整，无法给出准确评估。",
                "red_flags": [],
                "positive_points": [],
                "advice": "建议通过更多渠道了解该公司信息后再做决定。",
            }

    # ─── 生成用户报告 ────────────────────────────────────────────────

    async def _generate_report(self, assessment: dict) -> str:
        """生成用户友好的分析报告"""
        prompt = REPORT_GENERATION_PROMPT.format(
            assessment_json=json.dumps(assessment, ensure_ascii=False, indent=2),
        )

        messages = [
            {"role": "system", "content": "你是一位贴心的求职顾问，用平易近人的语言给出分析报告。"},
            {"role": "user", "content": prompt},
        ]

        try:
            return await llm_gateway.chat(messages, provider="zhipu", temperature=0.5)
        except Exception as e:
            logger.error(f"[BackgroundCheck] 报告生成失败: {e}")
            return self._generate_fallback_report(assessment)

    def _generate_fallback_report(self, assessment: dict) -> str:
        """生成降级报告（LLM 不可用时）"""
        stars = "⭐" * assessment.get("recommendation_index", 3)
        risk_level = assessment.get("risk_level", "unknown")
        risk_map = {"low": "🟢 低风险", "medium": "🟡 中等风险", "high": "🟠 高风险", "critical": "🔴 严重风险"}
        risk_text = risk_map.get(risk_level, "⚪ 未知")

        lines = [
            f"## 📊 综合评分\n\n推荐指数：{stars}\n\n风险等级：{risk_text}\n",
            f"## 💡 综合评估\n\n{assessment.get('summary', '暂无评估')}\n",
        ]

        red_flags = assessment.get("red_flags", [])
        if red_flags:
            lines.append("## ⚠️ 风险提示\n")
            for flag in red_flags:
                lines.append(f"- {flag}")

        positive = assessment.get("positive_points", [])
        if positive:
            lines.append("\n## ✅ 亮点\n")
            for p in positive:
                lines.append(f"- {p}")

        advice = assessment.get("advice", "")
        if advice:
            lines.append(f"\n## 💡 投递建议\n\n{advice}")

        jd_dimension = assessment.get("dimensions", {}).get("jd_analysis", {})
        evidence_phrases = jd_dimension.get("evidence_phrases", [])
        lines.append("\n## 🔎 证据边界\n")
        if evidence_phrases:
            lines.append("本次在 JD 原文中命中的信号：" + "、".join(evidence_phrases) + "。")
        else:
            lines.append("JD 原文未命中内置高风险词，但这不等于企业外部风险已经核验。")

        dimension_labels = {
            "social_insurance": "社保人数",
            "labor_disputes": "劳动争议",
            "business_risk": "工商风险",
            "online_reputation": "员工口碑",
        }
        dimensions = assessment.get("dimensions", {})
        verified_labels = [
            label
            for key, label in dimension_labels.items()
            if dimensions.get(key, {}).get("verified")
        ]
        unverified_labels = [
            label
            for key, label in dimension_labels.items()
            if not dimensions.get(key, {}).get("verified")
        ]
        if verified_labels:
            lines.append("已绑定官方来源的维度：" + "、".join(verified_labels) + "。")
        if unverified_labels:
            lines.append("仍未核验的维度：" + "、".join(unverified_labels) + "；报告不会补造数字。")

        sources = assessment.get("sources", [])
        if sources:
            lines.append("\n## 🔗 可核验来源\n")
            for source in sources:
                lines.append(
                    f"- [{source.get('title') or source.get('url')}]({source.get('url')})："
                    f"仅支持 {source.get('supports') or '来源页面直接展示的内容'}"
                )

        tasks = assessment.get("verification_tasks", [])
        if tasks:
            lines.append("\n## 🧭 下一步官方核验\n")
            for task in tasks:
                lines.append(
                    f"- {task.get('dimension')}：{task.get('title')}，"
                    f"搜索“{task.get('search_term')}”。{task.get('instructions')}"
                )

        return "\n".join(lines)

    # ─── 知识库操作 ──────────────────────────────────────────────────

    async def _search_knowledge_base(self, company_name: str, job_title: str) -> list[dict]:
        """从知识库检索历史分析记录"""
        try:
            query = f"{company_name} {job_title} 风险评估 企业背调"
            return await company_kb.search(query, company_name=company_name, top_k=3)
        except Exception as e:
            logger.warning(f"[BackgroundCheck] 知识库检索失败: {e}")
            return []

    async def _save_to_kb(
        self, company_name: str, job_title: str, assessment: dict, report: str
    ):
        """保存分析结果到知识库"""
        try:
            await company_kb.add_analysis(
                company_name=company_name,
                job_title=job_title,
                analysis_text=json.dumps(assessment, ensure_ascii=False),
                metadata={
                    "risk_level": assessment.get("risk_level", "unknown"),
                    "recommendation_index": assessment.get("recommendation_index", 3),
                    "analyzed_at": str(__import__("datetime").datetime.utcnow()),
                },
            )
            logger.info(f"[BackgroundCheck] 已存入知识库: {company_name}")
        except Exception as e:
            logger.warning(f"[BackgroundCheck] 知识库存储失败: {e}")

    def _merge_with_kb(self, assessment: dict, kb_results: list[dict]) -> dict:
        """
        合并知识库数据（实时结果优先）
        知识库数据作为参考，不覆盖实时结果
        """
        if not kb_results:
            return assessment

        # 如果实时检索结果不够完整，用知识库补充
        kb_risk = None
        for result in kb_results:
            meta = result.get("metadata", {})
            if meta.get("risk_level"):
                kb_risk = meta
                break

        if kb_risk and not assessment.get("red_flags"):
            assessment.setdefault("kb_reference", {
                "risk_level": kb_risk.get("risk_level"),
                "recommendation_index": kb_risk.get("recommendation_index"),
                "note": "以下信息来自历史分析记录，仅供参考（实时数据优先）",
            })

        return assessment

    # ─── 工具方法 ─────────────────────────────────────────────────────

    @staticmethod
    def _clean_json(text: str) -> str:
        """清理 LLM 返回的 JSON 文本"""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()


# 全局单例
background_check = BackgroundCheckAgent()
