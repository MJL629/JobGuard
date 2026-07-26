"""
企业背调 Agent

职责�?
1. 通过 WebSearch 实时检索企业信息（社保人数、劳动争议、网络口碑等�?
2. 分析 JD 话术，识别加班暗示、虚假宣传、刷 KPI 嫌疑
3. 结合用户画像的工作强度偏好，给出个性化推荐指数
4. 输出结构化风险评估报�?

数据优先级：用户提供的岗位信�? > 实时检索结�? > 知识库历史数�?
"""

import json
import logging
from typing import Optional

from app.llm.gateway import llm_gateway
from app.rag.company_kb import company_kb

logger = logging.getLogger(__name__)

# ─── Prompt 模板 ─────────────────────────────────────────────────────────

# 阶段 1：JD 话术分析（用主力模型，速度快）
JD_ANALYSIS_PROMPT = """你是一位资深的招聘市场分析专家。请分析以下岗位描述，识别潜在的"话术陷阱"�?

## 岗位信息
- 公司：{company_name}
- 岗位：{job_title}
- 薪资：{salary_min}-{salary_max}�?/�?
- 地点：{location}
- 岗位描述：{jd_text}
- 福利：{benefits}

## 分析维度

### 1. 加班暗示识别
以下话术通常暗示加班严重�?
- "抗压能力�?" �? 工作压力�?
- "拥抱变化" �? 业务不稳定，经常调整
- "弹性工作制" �? 可能意味着无偿加班（需结合上下文）
- "有创业精�?" �? 可能需�? 996
- "以结果为导向" �? 只看结果不计工时
- "能接受高强度工作" �? 明确告知会加�?
- "大小�?" / "单休" �? 明确告知非双�?

### 2. 薪资真实性评�?
- 薪资范围是否过大（如 10K-30K，实际大概率�? 10K�?
- 结合岗位要求判断薪资是否合理
- 是否�?"薪资面议"等模糊表�?

### 3. 虚假宣传/�? KPI 判断
- 岗位描述过于宽泛/模板�? �? 可能是假岗位
- 要求极低但薪资极�? �? 虚假宣传
- 描述与岗位名称不匹配 �? 挂羊头卖狗肉
- 只提福利不提工作内容 �? 可能是传销/培训机构

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
  "work_schedule_inferred": "推断的工作制度（双休/大小�?/单休/未知�?",
  "jd_quality": "详细专业/模板�?/过于简�?/可疑",
  "jd_analysis_summary": "JD 分析总结�?1-2句话�?"
}}
```

只输�? JSON�?"""


# 阶段 2：综合风险评估（�? DeepSeek V3 推理模型�?
RISK_ASSESSMENT_PROMPT = """你是一位企业风险评估专家。请综合以下信息，给出该岗位的全面风险评估�?

## 岗位信息
{job_info}

## JD 分析结果
{jd_analysis}

## 企业公开信息
{company_info}

## 网络口碑
{online_reputation}

## 用户画像（用于个性化评估�?
{user_profile}

## 评估要求
综合以上所有信息，从以下维度给出评估：

1. **社保/经营风险**：参保人数是否合理、是否有经营异常
2. **法律风险**：是否有劳动争议、类型和严重程度
3. **口碑风险**：员工评价、网络口碑倾向
4. **JD 风险**：是否存在虚假宣传、加班暗�?
5. **薪资真实�?**：结合用户期望，判断薪资是否合理
6. **匹配�?**：该岗位与用户画像的匹配程度
7. **个性化建议**：结合用户的工作强度偏好给出建议

## 输出格式
```json
{{
  "risk_level": "low/medium/high/critical",
  "recommendation_index": 1-5的整�?,
  "recommendation_text": "推荐/谨慎考虑/不太推荐/强烈不推�?",
  "dimensions": {{
    "social_insurance": {{
      "participants": "参保人数或null",
      "trend": "趋势分析",
      "assessment": "评估说明",
      "score": 1-5风险分（5=最安全�?
    }},
    "labor_disputes": {{
      "total_cases": "劳动争议数量或null",
      "recent_12m": "�?12个月数量",
      "main_types": ["类型1"],
      "assessment": "评估说明",
      "score": 1-5风险�?
    }},
    "business_risk": {{
      "abnormal_operations": "经营异常数量",
      "administrative_penalties": "行政处罚数量",
      "assessment": "评估说明",
      "score": 1-5风险�?
    }},
    "online_reputation": {{
      "overall_sentiment": "正面偏多/中�?/负面偏多/严重负面",
      "common_complaints": ["常见投诉1"],
      "highlights": ["正面评价1"],
      "assessment": "评估说明",
      "score": 1-5风险�?
    }},
    "jd_analysis": {{
      "overtime_risk": "low/medium/high",
      "fake_job_suspicion": "low/medium/high",
      "kpi_brushing_suspicion": "low/medium/high",
      "salary_authenticity": "评估",
      "assessment": "评估说明",
      "score": 1-5风险�?
    }},
    "match_with_user": {{
      "skill_match": "匹配度描�?",
      "salary_match": "匹配度描�?",
      "location_match": "匹配度描�?",
      "intensity_match": "是否匹配用户工作强度偏好",
      "score": 1-5匹配分（5=最匹配�?
    }}
  }},
  "overall_score": 综合风险�? 0-10�?0=最安全�?,
  "summary": "综合评估总结�?2-3句话�?",
  "red_flags": ["需要警惕的红旗信号"],
  "positive_points": ["值得考虑的亮�?"],
  "advice": "给用户的个性化建议"
}}
```

只输�? JSON�?"""


# 阶段 3：生成用户友好的分析报告
REPORT_GENERATION_PROMPT = """你是一位贴心的求职顾问。请将以下企业背调结果转化为用户友好的分析报告�?

## 分析结果
{assessment_json}

## 要求
- 用平易近人的语言，像朋友在帮你分析一�?
- 突出最重要的风险和亮点
- 给出明确的投递建�?
- 如果风险高，解释清楚为什�?
- 如果值得投，说明为什�?

## 输出格式
�? Markdown 格式输出，包含：
1. 📊 综合评分（推荐指数：⭐×N�?
2. ⚠️ 风险提示（如有）
3. �? 亮点（如有）
4. 📋 详细分析（社�?/法律/口碑/JD�?
5. 💡 投递建�?

直接输出报告内容，不需�? JSON�?"""


# ─── Agent 核心�? ────────────────────────────────────────────────────────

class BackgroundCheckAgent:
    """企业背调 Agent"""

    # ─── 主入�? ───────────────────────────────────────────────────────

    async def investigate(
        self,
        job_info: dict,
        user_profile: Optional[dict] = None,
        web_search_func=None,  # WebSearch 回调函数（由调用方注入）
    ) -> dict:
        """
        对企�?/岗位进行全面背调

        Args:
            job_info: 岗位解析 Agent 输出的结构化岗位信息
            user_profile: 用户画像（用于个性化评估�?
            web_search_func: WebSearch 回调函数 async def(query) -> str

        Returns:
            完整的风险评估报�? dict
        """
        company_name = job_info.get("company_name", "未知企业")
        job_title = job_info.get("job_title", "未知岗位")
        logger.info(f"[BackgroundCheck] 开始背调：{company_name} - {job_title}")

        # 1. 先查知识库（历史分析记录�?
        kb_results = await self._search_knowledge_base(company_name, job_title)

        # 2. JD 话术分析（主力模型，快）
        jd_analysis = await self._analyze_jd(job_info)
        logger.info(f"[BackgroundCheck] JD分析完成，加班风�?={jd_analysis.get('overtime_risk')}")

        # 3. 实时检索企业公开信息 + 网络口碑（并行）
        company_info = ""
        online_reputation = ""

        if web_search_func:
            try:
                # 并行检�?
                company_info = await self._search_company_info(company_name, web_search_func)
                online_reputation = await self._search_reputation(company_name, web_search_func)
            except Exception as e:
                logger.warning(f"[BackgroundCheck] WebSearch 检索失�?: {e}")

        # 4. 综合风险评估（DeepSeek V3 推理�?
        assessment = await self._assess_risk(
            job_info, jd_analysis, company_info, online_reputation, user_profile
        )
        logger.info(f"[BackgroundCheck] 风险评估完成，等�?={assessment.get('risk_level')}")

        # 5. 合并知识库数据（实时结果优先�?
        assessment = self._merge_with_kb(assessment, kb_results)

        # 6. 生成用户友好的报�?
        report = await self._generate_report(assessment)

        # 7. 存入知识�?
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
        }

    # ─── JD 话术分析 ─────────────────────────────────────────────────

    async def _analyze_jd(self, job_info: dict) -> dict:
        """分析 JD 话术陷阱"""
        salary_min = job_info.get("salary_min", "未知")
        salary_max = job_info.get("salary_max", "未知")
        if salary_min and salary_max:
            salary_str = f"{salary_min}-{salary_max}"
        else:
            salary_str = "未标�?"

        prompt = JD_ANALYSIS_PROMPT.format(
            company_name=job_info.get("company_name", "未知"),
            job_title=job_info.get("job_title", "未知"),
            salary_min=salary_min,
            salary_max=salary_max,
            location=job_info.get("location", "未知"),
            jd_text=job_info.get("jd_raw_text", "") or job_info.get("job_description", "")[:3000],
            benefits=json.dumps(job_info.get("benefits", []), ensure_ascii=False),
        )

        messages = [
            {"role": "system", "content": "你是一个精确的 JSON 输出引擎�?"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat(messages, provider="zhipu", temperature=0.2)
            return json.loads(self._clean_json(response))
        except Exception as e:
            logger.error(f"[BackgroundCheck] JD分析失败: {e}")
            return {
                "overtime_signals": [],
                "overtime_risk": "unknown",
                "salary_authenticity": "无法判断",
                "fake_job_suspicion": "low",
                "kpi_brushing_suspicion": "low",
            }

    # ─── 企业信息检�? ────────────────────────────────────────────────

    async def _search_company_info(self, company_name: str, web_search_func) -> str:
        """检索企业公开信息"""
        queries = [
            f"{company_name} 公司 社保人数 参保人数 天眼�?",
            f"{company_name} 劳动仲裁 劳动争议 裁判文书",
            f"{company_name} 经营异常 行政处罚 工商信息",
        ]

        results = []
        for query in queries:
            try:
                result = await web_search_func(query)
                if result:
                    results.append(result)
            except Exception as e:
                logger.warning(f"[BackgroundCheck] 检索失�? '{query}': {e}")

        return "\n---\n".join(results) if results else "未获取到企业公开信息"

    async def _search_reputation(self, company_name: str, web_search_func) -> str:
        """检索网络口�?"""
        queries = [
            f"{company_name} 员工评价 工作体验 怎么�? 脉脉 看准�?",
            f"{company_name} 知乎 小红�? 加班 工资 待遇",
            f"{company_name} 招聘 靠谱�? 值得去吗",
        ]

        results = []
        for query in queries:
            try:
                result = await web_search_func(query)
                if result:
                    results.append(result)
            except Exception as e:
                logger.warning(f"[BackgroundCheck] 检索失�? '{query}': {e}")

        return "\n---\n".join(results) if results else "未获取到网络口碑信息"

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
        # 格式化用户画�?
        user_profile_str = "未提供用户画�?"
        if user_profile:
            basic = user_profile.get("basic", {})
            prefs = user_profile.get("preferences", {})
            user_profile_str = json.dumps({
                "学历": basic.get("degree"),
                "期望薪资": f"{basic.get('expected_salary_min', 0)}-{basic.get('expected_salary_max', 0)}",
                "偏好城市": prefs.get("preferred_locations", []),
                "周末偏好": prefs.get("weekend_preference", "未设�?"),
                "加班接受�?": prefs.get("overtime_tolerance", "未设�?"),
                "劳动强度": prefs.get("labor_intensity", "未设�?"),
            }, ensure_ascii=False)

        prompt = RISK_ASSESSMENT_PROMPT.format(
            job_info=json.dumps(job_info, ensure_ascii=False, indent=2)[:2000],
            jd_analysis=json.dumps(jd_analysis, ensure_ascii=False, indent=2),
            company_info=company_info[:3000] if company_info else "未获�?",
            online_reputation=online_reputation[:3000] if online_reputation else "未获�?",
            user_profile=user_profile_str,
        )

        messages = [
            {"role": "system", "content": "你是一位企业风险评估专家。只输出 JSON�?"},
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
                "recommendation_text": "信息不足，建议进一步了�?",
                "dimensions": {},
                "overall_score": 5,
                "summary": "由于信息获取不完整，无法给出准确评估�?",
                "red_flags": [],
                "positive_points": [],
                "advice": "建议通过更多渠道了解该公司信息后再做决定�?",
            }

    # ─── 生成用户报告 ────────────────────────────────────────────────

    async def _generate_report(self, assessment: dict) -> str:
        """生成用户友好的分析报�?"""
        prompt = REPORT_GENERATION_PROMPT.format(
            assessment_json=json.dumps(assessment, ensure_ascii=False, indent=2),
        )

        messages = [
            {"role": "system", "content": "你是一位贴心的求职顾问，用平易近人的语言给出分析报告�?"},
            {"role": "user", "content": prompt},
        ]

        try:
            return await llm_gateway.chat(messages, provider="zhipu", temperature=0.5)
        except Exception as e:
            logger.error(f"[BackgroundCheck] 报告生成失败: {e}")
            return self._generate_fallback_report(assessment)

    def _generate_fallback_report(self, assessment: dict) -> str:
        """生成降级报告（LLM 不可用时�?"""
        stars = "�?" * assessment.get("recommendation_index", 3)
        risk_level = assessment.get("risk_level", "unknown")
        risk_map = {"low": "🟢 低风�?", "medium": "🟡 中等风险", "high": "🟠 高风�?", "critical": "🔴 严重风险"}
        risk_text = risk_map.get(risk_level, "�? 未知")

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
            lines.append("\n## �? 亮点\n")
            for p in positive:
                lines.append(f"- {p}")

        advice = assessment.get("advice", "")
        if advice:
            lines.append(f"\n## 💡 投递建议\n\n{advice}")

        return "\n".join(lines)

    # ─── 知识库操�? ──────────────────────────────────────────────────

    async def _search_knowledge_base(self, company_name: str, job_title: str) -> list[dict]:
        """从知识库检索历史分析记�?"""
        try:
            query = f"{company_name} {job_title} 风险评估 企业背调"
            return await company_kb.search(query, company_name=company_name, top_k=3)
        except Exception as e:
            logger.warning(f"[BackgroundCheck] 知识库检索失�?: {e}")
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
            logger.warning(f"[BackgroundCheck] 知识库存储失�?: {e}")

    def _merge_with_kb(self, assessment: dict, kb_results: list[dict]) -> dict:
        """
        合并知识库数据（实时结果优先�?
        知识库数据作为参考，不覆盖实时结�?
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
                "note": "以下信息来自历史分析记录，仅供参考（实时数据优先�?",
            })

        return assessment

    # ─── 工具方法 ─────────────────────────────────────────────────────

    @staticmethod
    def _clean_json(text: str) -> str:
        """清理 LLM 返回�? JSON 文本"""
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
