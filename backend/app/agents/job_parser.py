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
import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.llm.gateway import llm_gateway
from app.services.job_fetch_service import JobFetchError, job_fetch_service

logger = logging.getLogger(__name__)

# ─── Prompt 模板 ─────────────────────────────────────────────────────────

JOB_EXTRACT_PROMPT = """你是一位专业的招聘信息分析专家。请从以下岗位信息中提取结构化字段。

## 岗位信息原文
{raw_text}

## 提取要求
请提取以下字段（如果原文中没有，填 null）：

```json
{{
  "company_name": "公司全称",
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


JOB_CATEGORY_CLASSIFY_PROMPT = """根据以下岗位信息，判断岗位分类。

## 岗位信息
- 岗位名称：{job_title}
- 岗位描述：{jd_text}

## 分类选项
1. engineering - 工程开发（前端/后端/全栈/客户端/运维/AI Infra）
2. algorithm - 算法研发（大模型/Agent/推荐/CV/语音/NLP）
3. product_data_testing - 产品/数据/测试（AI产品/数据开发/数据分析/测试）
4. security - 安全（网络/内容/风控/AI安全）

## 细分选项
engineering: 前端开发/后端开发/全栈开发/客户端开发/运维开发/AI Infra
algorithm: 大模型算法/Agent算法/推荐算法/CV算法/语音算法/NLP算法
product_data_testing: AI产品经理/数据开发/数据分析/测试开发
security: 网络安全/内容风控/AI安全

只输出：category|sub_category（如：engineering|后端开发）"""

JOB_EXTRACT_SYSTEM_PROMPT = JOB_EXTRACT_PROMPT.replace(
    "\n## 岗位信息原文\n{raw_text}\n", "\n"
)
JOB_EXTRACT_USER_PROMPT = "## 岗位信息原文\n{raw_text}"
JOB_CATEGORY_SYSTEM_PROMPT = JOB_CATEGORY_CLASSIFY_PROMPT.replace(
    "\n## 岗位信息\n- 岗位名称：{job_title}\n- 岗位描述：{jd_text}\n",
    "\n",
)
JOB_CATEGORY_USER_PROMPT = """## 岗位信息
- 岗位名称：{job_title}
- 岗位描述：{jd_text}"""


# ─── Agent 核心类 ────────────────────────────────────────────────────────

class JobParserAgent:
    """岗位解析 Agent"""

    # ─── 主入口：解析岗位 ─────────────────────────────────────────────

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

        stripped_input = raw_input.strip()
        source_url = None
        source_evidence = None
        structured_job = {}
        if stripped_input.startswith(("http://", "https://")) and "\n" not in stripped_input:
            try:
                page = await job_fetch_service.fetch(stripped_input)
            except JobFetchError as exc:
                return {"error": exc.message, "error_code": exc.code}
            source_url = page.final_url
            source_evidence = page.evidence()
            structured_job = self._structured_to_job_info(page.structured_job)
            raw_input = (
                f"来源链接：{page.final_url}\n"
                f"网页标题：{page.title}\n"
                f"岗位网页正文：\n{page.text}"
            )
            input_type = "url"

        # 1. 提取结构化信息
        job_info = await self._extract_job_info(raw_input)
        fallback = self._extract_job_info_fallback(raw_input)
        job_info = job_info if isinstance(job_info, dict) else {}
        for key, value in {**fallback, **structured_job}.items():
            if value not in (None, "", []) and not job_info.get(key):
                job_info[key] = value

        if source_url:
            job_info["source_url"] = source_url
            job_info["source_type"] = self._source_type_from_url(source_url)
            job_info["source_evidence"] = source_evidence

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

    @staticmethod
    def _structured_to_job_info(posting: dict) -> dict:
        if not posting:
            return {}
        organization = posting.get("hiringOrganization") or {}
        location = posting.get("jobLocation") or {}
        if isinstance(location, list):
            location = location[0] if location else {}
        address = location.get("address") if isinstance(location, dict) else {}
        if isinstance(address, str):
            location_text = address
        else:
            address = address or {}
            location_text = "".join(
                str(address.get(key) or "")
                for key in ("addressRegion", "addressLocality", "streetAddress")
            )
        base_salary = posting.get("baseSalary") or {}
        value = base_salary.get("value") if isinstance(base_salary, dict) else {}
        if isinstance(value, (int, float)):
            salary_min = salary_max = int(value)
        else:
            value = value or {}
            salary_min = value.get("minValue") or value.get("value")
            salary_max = value.get("maxValue") or value.get("value")
        description = BeautifulSoup(str(posting.get("description") or ""), "html.parser").get_text("\n", strip=True)
        qualifications = posting.get("qualifications") or posting.get("skills") or []
        if isinstance(qualifications, str):
            qualifications = [item.strip() for item in re.split(r"[\n；;]", qualifications) if item.strip()]
        return {
            "company_name": organization.get("name") if isinstance(organization, dict) else None,
            "job_title": posting.get("title"),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "location": location_text or posting.get("jobLocationType"),
            "experience_required": posting.get("experienceRequirements"),
            "education_required": posting.get("educationRequirements"),
            "employment_type": posting.get("employmentType"),
            "job_description": description,
            "jd_raw_text": description,
            "requirements": qualifications,
            "source_url": posting.get("url"),
        }

    @staticmethod
    def _extract_job_info_fallback(raw_text: str) -> dict:
        """仅提取带标签的明确字段，供模型不可用时兜底。"""
        def capture(pattern: str):
            match = re.search(pattern, raw_text, re.IGNORECASE)
            return match.group(1).strip() if match else None

        company = capture(r"(?:公司(?:名称)?|企业)\s*[:：]\s*([^\n；;]{2,80})")
        title = capture(r"(?:岗位(?:名称)?|职位(?:名称)?|招聘职位)\s*[:：]\s*([^\n；;]{2,80})")
        location = capture(r"(?:工作地点|地点|城市)\s*[:：]\s*([^\n；;]{2,80})")
        salary_match = re.search(
            r"(?:薪资|月薪)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*([kK千万]?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*([kK千万]?)",
            raw_text,
        )
        salary_min = salary_max = None
        if salary_match:
            values = [float(salary_match.group(1)), float(salary_match.group(3))]
            units = [salary_match.group(2), salary_match.group(4)]
            for index, unit in enumerate(units):
                if unit.lower() == "k" or unit == "千":
                    values[index] *= 1000
                elif unit == "万":
                    values[index] *= 10000
            salary_min, salary_max = map(int, values)
        return {
            key: value for key, value in {
                "company_name": company,
                "job_title": title,
                "location": location,
                "salary_min": salary_min,
                "salary_max": salary_max,
            }.items() if value not in (None, "")
        }

    @staticmethod
    def _source_type_from_url(url: str) -> str:
        hostname = (urlparse(url).hostname or "").lower()
        mappings = {
            "zhipin.com": "boss_zhipin",
            "lagou.com": "lagou",
            "51job.com": "51job",
            "liepin.com": "liepin",
        }
        return next((source for domain, source in mappings.items() if hostname.endswith(domain)), "public_web")

    # ─── 提取岗位信息 ─────────────────────────────────────────────────

    async def _extract_job_info(self, raw_text: str) -> dict:
        """调用 LLM 提取结构化岗位信息"""
        prompt = JOB_EXTRACT_USER_PROMPT.format(raw_text=raw_text[:8000])

        messages = [
            {"role": "system", "content": JOB_EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat(
                messages, provider="zhipu", temperature=0.1,
                metadata={"agent_name": "job_parser.extract"},
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
        prompt = JOB_CATEGORY_USER_PROMPT.format(
            job_title=job_title,
            jd_text=jd_text[:2000],
        )

        messages = [
            {"role": "system", "content": JOB_CATEGORY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat(
                messages, provider="zhipu", temperature=0.1,
                metadata={"agent_name": "job_parser.classify"},
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
