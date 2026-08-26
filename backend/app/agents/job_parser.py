"""
岗位解析 Agent

职责：
1. 解析用户粘贴的岗位链接 → 通过 WebFetch 获取页面内容，提取结构化岗位信息
2. 解析用户上传的岗位截图 → OCR + LLM 提取信息
3. 解析用户直接粘贴的岗位描述文本
4. 输出统一的岗位结构化 JSON
"""

import json
import logging
from typing import Optional

from app.llm.gateway import llm_gateway
from app.observability.tracing import traced_node

logger = logging.getLogger(__name__)
JOB_EXTRACT_PROMPT_VERSION = "job_extract.v2"
JOB_CLASSIFY_PROMPT_VERSION = "job_classify.v2"

# ─── Prompt 模板 ─────────────────────────────────────────────────────────

JOB_EXTRACT_PROMPT = """你是一位专业的招聘信息分析专家。请从以下岗位信息中提取结构化字段。

## 岗位信息原文
{raw_text}

## 提取要求
请提取以下字段（如果原文中没有，填 null）：

```json
{{
  "company_name": "公司名称（严格按原文提取，不要求工商全称，不要自行补全）",
  "job_title": "岗位名称",
  "salary_min": 最低月薪（整数，单位：元）,
  "salary_max": 最高月薪（整数，单位：元）,
  "salary_type": "月薪/年薪/日薪",
  "location": "工作地点（城市+区）",
  "experience_required": "经验要求（如：1-3年/应届生/不限）",
  "education_required": "学历要求（如：本科/大专/不限）",
  "job_category": "岗位大类（engineering/algorithm/product_data_testing/security）",
  "sub_category": "岗位细分（如：后端开发/前端开发/AI算法/数据分析）",
  "job_description": "岗位职责描述（完整原文）",
  "requirements": ["技术要求1", "技术要求2"],
  "benefits": ["福利1", "福利2"],
  "tags": ["标签1", "标签2"],
  "headcount": "招聘人数（如有）",
  "employment_type": "全职/实习/兼职/外包",
  "source_url": "来源链接",
  "source_type": "来源平台（boss_zhipin/lagou/51job/liepin/other）",
  "jd_raw_text": "岗位描述完整原文"
}}
```

## 岗位分类规则
- engineering: 前端开发/后端开发/全栈开发/客户端开发/运维开发/AI Infra开发
- algorithm: 大模型算法/Agent算法/推荐算法/CV/语音/NLP
- product_data_testing: AI产品经理/数据开发/数据分析/测试开发
- security: 网络安全/内容风控/AI安全

只输出 JSON，不要任何其他内容。"""


JOB_CATEGORY_CLASSIFY_PROMPT = """你是岗位分类器。只能从给定枚举中各选择一个 category 和 sub_category。
先依据岗位的主要职责判断，不要因偶然出现的技术关键词改变岗位类别；细分类必须属于所选类别。无法完全确定时选择最接近主要职责的一项。

## 允许值
engineering: 前端开发/后端开发/全栈开发/客户端开发/运维开发/AI Infra
algorithm: 大模型算法/Agent算法/推荐算法/CV算法/语音算法/NLP算法
product_data_testing: AI产品经理/数据开发/数据分析/测试开发
security: 网络安全/内容风控/AI安全

## 岗位信息
- 岗位名称：{job_title}
- 岗位描述：{jd_text}

只输出一行 category|sub_category，不要解释，不要 Markdown。"""


# ─── Agent 核心类 ────────────────────────────────────────────────────────

class JobParserAgent:
    """岗位解析 Agent"""

    # ─── 主入口：解析岗位 ─────────────────────────────────────────────

    @traced_node("job_parser.parse")
    async def parse(
        self,
        raw_input: str,
        input_type: str = "text",  # text / url / screenshot_text
    ) -> dict:
        """
        解析岗位信息

        Args:
            raw_input: 用户输入（链接、截图文字、或直接粘贴的岗位描述）
            input_type: 输入类型

        Returns:
            结构化的岗位信息 dict
        """
        logger.info(f"[JobParser] 开始解析岗位，输入类型={input_type}，长度={len(raw_input)}")

        # 1. 提取结构化信息
        job_info = await self._extract_job_info(raw_input)

        if not job_info or not job_info.get("company_name"):
            logger.warning("[JobParser] 未能提取到有效岗位信息")
            return {"error": "无法从输入中提取有效岗位信息，请确认内容包含公司名和岗位名"}

        # 2. 补充分类（如果 LLM 没有自动分类）
        if not job_info.get("job_category") or not job_info.get("sub_category"):
            category, sub = await self._classify_job(
                job_info.get("job_title", ""),
                job_info.get("job_description", "") or job_info.get("jd_raw_text", ""),
            )
            job_info["job_category"] = category
            job_info["sub_category"] = sub

        # 3. 标准化处理
        job_info = self._normalize(job_info, raw_input, input_type)

        logger.info(f"[JobParser] 解析完成：{job_info.get('company_name')} - {job_info.get('job_title')}")
        return job_info

    # ─── 提取岗位信息 ─────────────────────────────────────────────────

    async def _extract_job_info(self, raw_text: str) -> dict:
        """调用 LLM 提取结构化岗位信息"""
        prompt = JOB_EXTRACT_PROMPT.format(raw_text=raw_text[:8000])  # 限制长度

        messages = [
            {"role": "system", "content": "你是一个精确的 JSON 输出引擎。只输出 JSON，不输出任何解释。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat_primary(
                messages,
                temperature=0.1,
                max_tokens=1200,
                prompt_version=JOB_EXTRACT_PROMPT_VERSION,
                use_cache=True,
            )
            cleaned = self._clean_json(response)
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"[JobParser] JSON 解析失败: {e}")
            logger.debug(f"原始响应前500字: {response[:500] if 'response' in dir() else 'N/A'}")
            return {}
        except Exception as e:
            logger.error(f"[JobParser] 提取失败: {e}")
            return {}

    # ─── 岗位分类 ─────────────────────────────────────────────────────

    async def _classify_job(self, job_title: str, jd_text: str) -> tuple[str, str]:
        """对岗位进行分类"""
        prompt = JOB_CATEGORY_CLASSIFY_PROMPT.format(
            job_title=job_title,
            jd_text=jd_text[:2000],
        )

        messages = [
            {"role": "system", "content": "你是一个精确的分类器。只输出分类结果。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat_primary(
                messages,
                temperature=0.1,
                max_tokens=64,
                prompt_version=JOB_CLASSIFY_PROMPT_VERSION,
                use_cache=True,
            )
            result = response.strip()
            if "|" in result:
                parts = result.split("|")
                return parts[0].strip(), parts[1].strip() if len(parts) > 1 else "其他"
            return "engineering", "其他"
        except Exception as e:
            logger.error(f"[JobParser] 分类失败: {e}")
            return "engineering", "其他"

    # ─── 标准化 ───────────────────────────────────────────────────────

    def _normalize(self, job_info: dict, raw_input: str, input_type: str) -> dict:
        """标准化岗位信息"""
        # 确保薪资是整数
        for field in ["salary_min", "salary_max"]:
            val = job_info.get(field)
            if val is not None:
                try:
                    job_info[field] = int(val)
                except (ValueError, TypeError):
                    job_info[field] = None

        # 设置默认值
        job_info.setdefault("source_type", "user_input")
        job_info.setdefault("employment_type", "全职")
        job_info.setdefault("experience_required", "不限")
        job_info.setdefault("education_required", "不限")

        # 确保列表字段
        for field in ["requirements", "benefits", "tags"]:
            val = job_info.get(field)
            if val is None:
                job_info[field] = []
            elif isinstance(val, str):
                job_info[field] = [val]

        return job_info

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
job_parser = JobParserAgent()
