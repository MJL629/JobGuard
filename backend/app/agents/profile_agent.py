"""
用户画像 Agent

职责：
1. 解析用户上传的简历，提取结构化信息
2. 通过多轮对话追问缺失的画像信息
3. 将所有信息输出为结构化 JSON，供后续存储

设计原则：
- 每次只问 1-2 个问题，不一次性轰炸
- 先收集硬性条件（薪资/地点/岗位方向），再收集软性偏好（强度/文化）
- 支持「跳过」和「不知道」
"""

import json
import logging
from typing import Optional

from app.llm.gateway import llm_gateway

logger = logging.getLogger(__name__)

# ─── Prompt 模板 ─────────────────────────────────────────────────────────

RESUME_PARSE_PROMPT = """你是一位专业的简历解析专家。请从以下简历文本中提取所有可用信息，输出 JSON 格式。

## 简历文本
{resume_text}

## 提取要求
请提取以下字段（如果简历中没有，填 null）：

```json
{{
  "full_name": "姓名",
  "gender": "性别（男/女）",
  "birth_year": 出生年份（整数）,
  "degree": "最高学历（大专/本科/硕士/博士）",
  "major": "专业名称",
  "school": "毕业院校",
  "graduation_year": 毕业年份（整数）,
  "current_city": "当前所在城市",
  "years_of_experience": 工作年限（整数，应届生填0）,
  "education_list": [
    {{
      "school": "学校名称",
      "major": "专业",
      "degree": "学历",
      "start_year": 入学年份,
      "end_year": 毕业年份,
      "gpa": "GPA或排名（如有）",
      "honors": "荣誉奖项（如有）"
    }}
  ],
  "projects": [
    {{
      "project_name": "项目名称",
      "role": "担任角色",
      "description": "项目描述",
      "tech_stack": ["技术1", "技术2"],
      "start_date": "开始时间",
      "end_date": "结束时间",
      "highlights": "项目亮点/量化成果",
      "project_url": "项目链接（如有）"
    }}
  ],
  "skills": [
    {{
      "skill_name": "技能名称",
      "proficiency": "掌握/熟悉/了解",
      "category": "编程语言/框架/数据库/工具/其他"
    }}
  ]
}}
```

只输出 JSON，不要任何其他内容。"""


PROFILE_DIALOGUE_SYSTEM = """你是一位专业的求职顾问，正在帮助用户建立求职画像。

## 你的任务
通过友好的对话，逐步收集用户以下信息。每次只问 1-2 个问题，不要一次性问太多。

## 需要收集的信息（按优先级排序）
1. **求职方向**：想找什么类型的岗位？（如：后端开发、前端开发、AI算法等）
2. **期望薪资**：期望的月薪范围？（如：10K-15K）
3. **工作城市**：希望在哪些城市工作？（可多个）
4. **工作强度偏好**：
   - 接受单休还是必须双休？
   - 是否接受加班？
   - 是否排斥高强度工作？
5. **公司规模偏好**：想去大厂、中型公司、还是创业公司？
6. **远程工作**：是否接受远程办公？

## 对话规则
- 根据已有信息，智能判断下一步该问什么
- 如果用户已经提供了某些信息，不要重复问
- 用户说「不知道」「随便」「都行」时，标记为「不限」，继续下一个问题
- 当所有核心信息都收集完毕（至少：求职方向、期望薪资、工作城市），告诉用户画像已完善

## 已收集的信息
{collected_info}

## 缺失的信息
{missing_fields}

请用友好的语气和用户对话，引导用户补充缺失的信息。"""


PROFILE_EXTRACT_PROMPT = """从以下对话中提取用户最新的画像信息变更。只提取本轮对话中用户新提供或修改的信息，已有且未修改的字段不输出。

## 对话内容
{dialogue}

## 输出格式
```json
{{
  "job_direction": "用户想找的岗位类型（如：后端开发），未提及填null",
  "expected_salary_min": 期望最低月薪（整数，单位元），未提及填null,
  "expected_salary_max": 期望最高月薪（整数，单位元），未提及填null,
  "preferred_locations": ["城市1", "城市2"] 或 null,
  "overtime_tolerance": "接受/偶尔/不接受/null",
  "weekend_preference": "必须双休/可接受单休/null",
  "labor_intensity": "排斥高强度/接受中等/无所谓/null",
  "company_scale_pref": "大厂/中型/初创/无所谓/null",
  "remote_work": "不接受/混合/完全远程/null"
}}
```

只输出 JSON，不要任何其他内容。"""


# ─── Agent 核心类 ────────────────────────────────────────────────────────

class ProfileAgent:
    """用户画像 Agent"""

    # 画像必填字段（用于判断完整度）
    REQUIRED_FIELDS = [
        "degree", "major", "school", "graduation_year",
        "expected_salary_min", "expected_salary_max",
        "preferred_locations", "preferred_job_types",
    ]

    # 对话追问顺序
    QUESTION_ORDER = [
        "job_direction",       # 求职方向
        "expected_salary",     # 期望薪资
        "preferred_locations", # 工作城市
        "weekend_preference",  # 单双休
        "overtime_tolerance",  # 加班接受度
        "company_scale_pref",  # 公司规模
        "remote_work",         # 远程工作
    ]

    # ─── 简历解析 ─────────────────────────────────────────────────────

    async def parse_resume(self, resume_text: str) -> dict:
        """
        解析简历文本，提取结构化信息

        Args:
            resume_text: 简历全文

        Returns:
            结构化的简历信息 dict
        """
        prompt = RESUME_PARSE_PROMPT.format(resume_text=resume_text[:15000])  # 限制长度

        messages = [
            {"role": "system", "content": "你是一个精确的 JSON 输出引擎。只输出 JSON，不输出任何解释。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat(messages, provider="zhipu", temperature=0.1)
            # 清理可能的 markdown 代码块包裹
            cleaned = self._clean_json(response)
            result = json.loads(cleaned)
            logger.info(f"[ProfileAgent] 简历解析成功，提取到 {len(result.get('projects', []))} 个项目")
            return result
        except json.JSONDecodeError as e:
            logger.error(f"[ProfileAgent] 简历解析 JSON 解析失败: {e}")
            logger.debug(f"原始响应: {response[:500]}")
            return {}
        except Exception as e:
            logger.error(f"[ProfileAgent] 简历解析失败: {e}")
            return {}

    # ─── 对话追问 ─────────────────────────────────────────────────────

    async def generate_question(
        self,
        collected_info: dict,
        conversation_history: list[dict],
    ) -> str:
        """
        根据已收集的信息，生成下一轮追问

        Args:
            collected_info: 已收集的画像信息
            conversation_history: 对话历史

        Returns:
            下一轮追问文本
        """
        # 判断缺失字段
        missing = self._get_missing_fields(collected_info)

        if not missing:
            return self._build_completion_message(collected_info)

        # 格式化已收集信息
        collected_str = json.dumps(collected_info, ensure_ascii=False, indent=2)
        missing_str = ", ".join(missing[:3])  # 最多提示 3 个缺失项

        system_prompt = PROFILE_DIALOGUE_SYSTEM.format(
            collected_info=collected_str,
            missing_fields=missing_str,
        )

        # 构建消息（最近 10 轮对话）
        messages = [{"role": "system", "content": system_prompt}]
        recent_history = conversation_history[-20:]  # 最近 10 轮
        for msg in recent_history:
            messages.append(msg)

        try:
            response = await llm_gateway.chat(messages, provider="zhipu", temperature=0.7)
            return response.strip()
        except Exception as e:
            logger.error(f"[ProfileAgent] 生成追问失败: {e}")
            return f"我还需要了解一些信息。请问你{missing[0] if missing else '还有什么要补充的'}？"

    # ─── 信息提取 ─────────────────────────────────────────────────────

    async def extract_updates(
        self,
        dialogue: list[dict],
        existing_info: dict,
    ) -> dict:
        """
        从对话中提取用户新提供/修改的画像信息

        Args:
            dialogue: 最近几轮对话
            existing_info: 已有的画像信息

        Returns:
            变更的字段 dict
        """
        # 格式化对话
        dialogue_text = ""
        for msg in dialogue[-10:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            dialogue_text += f"[{role}]: {content}\n"

        prompt = PROFILE_EXTRACT_PROMPT.format(dialogue=dialogue_text)

        messages = [
            {"role": "system", "content": "你是一个精确的 JSON 输出引擎。只输出 JSON。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat(messages, provider="zhipu", temperature=0.1)
            cleaned = self._clean_json(response)
            updates = json.loads(cleaned)
            # 过滤掉 null 值
            updates = {k: v for k, v in updates.items() if v is not None}
            logger.info(f"[ProfileAgent] 提取到画像更新: {list(updates.keys())}")
            return updates
        except Exception as e:
            logger.error(f"[ProfileAgent] 信息提取失败: {e}")
            return {}

    # ─── 画像完整性检查 ───────────────────────────────────────────────

    def check_completeness(self, profile: dict) -> dict:
        """
        检查画像完整度

        Returns:
            {"completeness": 0-100, "missing": [...], "ready": bool}
        """
        weights = {
            # 基本信息 40%
            "degree": 8, "major": 8, "school": 8, "graduation_year": 4,
            "full_name": 4, "current_city": 4, "years_of_experience": 4,
            # 求职偏好 30%
            "expected_salary_min": 8, "expected_salary_max": 8,
            "preferred_locations": 8, "preferred_job_types": 6,
            # 工作强度偏好 15%
            "weekend_preference": 5, "overtime_tolerance": 5,
            "labor_intensity": 5,
            # 其他偏好 15%
            "company_scale_pref": 4, "remote_work": 4,
            "preferred_industries": 4, "preferred_sub_categories": 3,
        }

        score = 0
        missing = []

        for field, weight in weights.items():
            value = profile.get(field)
            if value and value != "unknown" and value != []:
                score += weight
            else:
                missing.append(field)

        # 项目经历是加分项
        projects = profile.get("projects", [])
        if projects:
            score = min(100, score + min(len(projects) * 3, 15))

        # 技能是加分项
        skills = profile.get("skills", [])
        if skills:
            score = min(100, score + min(len(skills) * 2, 10))

        return {
            "completeness": min(100, score),
            "missing": missing,
            "ready": score >= 60,  # 60 分即可开始使用
        }

    # ─── 工具方法 ─────────────────────────────────────────────────────

    def _get_missing_fields(self, collected: dict) -> list[str]:
        """获取缺失的字段名（按优先级排序）"""
        missing = []

        # 求职方向
        if not collected.get("preferred_job_types") and not collected.get("job_direction"):
            missing.append("求职方向")

        # 期望薪资
        if not collected.get("expected_salary_min") and not collected.get("expected_salary_max"):
            missing.append("期望薪资范围")

        # 工作城市
        if not collected.get("preferred_locations"):
            missing.append("希望工作的城市")

        # 单双休
        if not collected.get("weekend_preference"):
            missing.append("对单休/双休的要求")

        # 加班
        if not collected.get("overtime_tolerance"):
            missing.append("对加班的接受程度")

        # 公司规模
        if not collected.get("company_scale_pref"):
            missing.append("对公司的规模偏好")

        # 远程
        if not collected.get("remote_work"):
            missing.append("是否接受远程办公")

        return missing

    def _build_completion_message(self, info: dict) -> str:
        """画像收集完成时的提示信息"""
        lines = ["太好了！你的求职画像已经基本完善，让我帮你总结一下：", ""]

        if info.get("preferred_job_types"):
            lines.append(f"📌 求职方向：{'/'.join(info['preferred_job_types'])}")
        elif info.get("job_direction"):
            lines.append(f"📌 求职方向：{info['job_direction']}")

        salary_min = info.get("expected_salary_min")
        salary_max = info.get("expected_salary_max")
        if salary_min and salary_max:
            lines.append(f"💰 期望薪资：{salary_min/1000:.0f}K - {salary_max/1000:.0f}K")

        locations = info.get("preferred_locations")
        if locations:
            lines.append(f"📍 工作城市：{'/'.join(locations)}")

        weekend = info.get("weekend_preference", "")
        if weekend:
            lines.append(f"📅 休息制度：{weekend}")

        overtime = info.get("overtime_tolerance", "")
        if overtime:
            lines.append(f"⏰ 加班接受度：{overtime}")

        lines.append("")
        lines.append("现在你可以：")
        lines.append("• 粘贴岗位链接让我帮你分析是否值得投递")
        lines.append("• 让我帮你推荐适合的岗位")
        lines.append("• 随时更新你的画像信息")
        lines.append("")
        lines.append("你想先做什么？")

        return "\n".join(lines)

    @staticmethod
    def _clean_json(text: str) -> str:
        """清理 LLM 返回的 JSON 文本"""
        text = text.strip()
        # 去掉 markdown 代码块标记
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()


# 全局单例
profile_agent = ProfileAgent()
