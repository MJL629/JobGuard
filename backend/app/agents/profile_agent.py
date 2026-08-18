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
import re
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
7. **真实经历**：即使用户没有简历，也要继续询问课程设计、个人/开源项目、实习、工作、比赛、科研、论文或社团实践。
8. **经历深挖**：对每段经历逐步询问目标、用户角色、本人采取的行动、使用的工具/技术和可核验成果；没有量化结果时允许留空，禁止诱导编造数字。

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


PROFILE_EXTRACT_PROMPT = """从以下对话中提取用户最新的画像信息变更。结合已有画像理解省略、指代和纠正，但只输出最新一轮中用户新提供或明确修改的字段，已有且未修改的字段不输出。

重要语义规则：
- “不接受高强度/长期/频繁加班”只表示排斥高强度，不等于“不接受任何加班”。此时填写 labor_intensity，不要填写 overtime_tolerance。
- 只有用户明确说“不接受任何加班/完全不接受加班”时，overtime_tolerance 才能填写“不接受”。
- “偶尔正常加班可以，但不接受高强度加班”应同时填写 overtime_tolerance=偶尔、labor_intensity=排斥高强度。
- 不要输出字符串 "null"、"unknown" 或 "未提及"；未提及字段使用真正的 JSON null。

## 已有画像
{existing_info}

## 对话内容
{dialogue}

## 输出格式
```json
{{
  "job_direction": "用户想找的岗位类型（如：后端开发），未提及填null",
  "degree": "最高学历（大专/本科/硕士/博士），未提及填null",
  "major": "专业名称，未提及填null",
  "school": "学校名称，未提及填null",
  "graduation_year": 毕业年份（整数），未提及填null,
  "current_city": "当前所在城市，未提及填null",
  "years_of_experience": 工作年限（整数，应届生为0），未提及填null,
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


EXPERIENCE_EXTRACT_PROMPT = """从用户原话中提取一段真实求职经历。只有用户明确说自己做过、参加过或负责过时才提取；不要根据常识补全，不要编造数字。

用户原话：{text}

输出 JSON：
{{
  "experience_type": "project/internship/competition/research/work/credential/award/leadership/other",
  "title": "经历名称",
  "organization": "组织或单位，没有则为 null",
  "role": "本人角色，没有则为 null",
  "description": "背景或目标，没有则为 null",
  "actions": "本人做了什么，没有则为 null",
  "achievements": "原话中明确出现的结果，没有则为 null",
  "tech_stack": ["原话明确提到的技术或工具"]
}}
只输出 JSON。"""


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
        "experience",          # 项目/实习/比赛/科研/工作
        "experience_detail",   # 角色、行动与成果
    ]

    DEEP_INTERVIEW_DIMENSIONS = [
        (
            "experience_inventory",
            "除了简历里已经写的内容，你还做过哪些课程设计、个人或开源项目、兼职实践？先选一段你投入最多但还没写进简历的经历。",
        ),
        (
            "internship_work",
            "你是否有过实习、兼职、校内岗位或真实用户参与的实践？当时负责什么，最终交付了什么？没有也可以直接说没有。",
        ),
        (
            "competition_awards",
            "你参加过哪些比赛、竞赛、奖学金或评优？请说清名称、你的角色和真实结果；没有获奖也可以写参赛经历。",
        ),
        (
            "research_publication",
            "你是否参与过科研、论文、实验室任务或数据分析？你亲自完成了哪一部分，用了什么方法或工具？",
        ),
        (
            "credentials_language",
            "你取得过哪些证书或语言成绩，例如软考、计算机等级、英语四六级或云厂商认证？请只说可核验的结果。",
        ),
        (
            "leadership_collaboration",
            "有没有一段能体现协作、推进或解决冲突的经历？当时遇到了什么阻碍，你具体怎样推动事情完成？",
        ),
        (
            "star_story",
            "请从最有代表性的一段经历里选一个难题，按“背景—目标—你的行动—结果”讲一遍。没有量化数字也没关系，真实最重要。",
        ),
        (
            "learning_goal",
            "针对目标岗位，你觉得自己目前最欠缺的知识或项目证据是什么？我可以据此给出学习资源和下一步作品建议。",
        ),
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

        fallback = self._parse_resume_fallback(resume_text)
        try:
            response = await llm_gateway.chat(messages, provider="zhipu", temperature=0.1)
            if not response or response.lstrip().startswith("[Mock]"):
                logger.warning("[ProfileAgent] 模型不可用，使用可核验的本地规则解析简历")
                return fallback
            result = json.loads(self._clean_json(response))
            if not isinstance(result, dict):
                raise ValueError("模型返回的简历结构不是 JSON 对象")
            result = self._merge_resume_results(result, fallback)
            logger.info(
                "[ProfileAgent] 简历解析成功，提取到 %s 个项目",
                len(result.get("projects", [])),
            )
            return result
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("[ProfileAgent] 模型返回格式无效，使用本地规则结果: %s", exc)
            return fallback
        except Exception as exc:
            logger.error("[ProfileAgent] 简历模型解析失败，使用本地规则结果: %s", exc)
            return fallback

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
            if not response or response.lstrip().startswith("[Mock]"):
                return self._fallback_question(missing)
            return response.strip()
        except Exception as e:
            logger.error(f"[ProfileAgent] 生成追问失败: {e}")
            return self._fallback_question(missing)

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

        latest_user_message = next(
            (msg.get("content", "") for msg in reversed(dialogue) if msg.get("role") == "user"),
            "",
        )
        rule_updates = self._extract_rule_based_updates(latest_user_message)

        prompt = PROFILE_EXTRACT_PROMPT.format(
            dialogue=dialogue_text,
            existing_info=json.dumps(existing_info or {}, ensure_ascii=False, indent=2),
        )

        messages = [
            {"role": "system", "content": "你是一个精确的 JSON 输出引擎。只输出 JSON。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat(messages, provider="zhipu", temperature=0.1)
            if not response or response.lstrip().startswith("[Mock]"):
                logger.warning("[ProfileAgent] LLM 处于 Mock 模式，跳过画像字段提取")
                return rule_updates
            cleaned = self._clean_json(response)
            updates = self._normalize_updates(json.loads(cleaned))
            updates.update(rule_updates)
            previous_assistant_message = next(
                (
                    msg.get("content", "")
                    for msg in reversed(dialogue[:-1])
                    if msg.get("role") == "assistant"
                ),
                "",
            )
            updates = self._ground_updates_in_latest_turn(
                latest_user_message,
                previous_assistant_message,
                updates,
                rule_updates,
            )
            updates = self._apply_semantic_guards(
                latest_user_message, updates, existing_info or {}
            )
            logger.info(f"[ProfileAgent] 提取到画像更新: {list(updates.keys())}")
            return updates
        except Exception as e:
            logger.error(f"[ProfileAgent] 信息提取失败: {e}")
            return self._apply_semantic_guards(
                latest_user_message, rule_updates, existing_info or {}
            )

    async def extract_experience_candidate(self, text: str) -> dict | None:
        """Extract one explicitly stated experience and retain the raw evidence."""
        if not text or not re.search(
            r"(?:我|本人).{0,12}(?:做过|参加过|负责|实习|工作|开发|研究|比赛|竞赛|科研|论文|课程设计|开源|考过|通过|获得|拿到|担任|组织)",
            text,
        ):
            return None
        prompt = EXPERIENCE_EXTRACT_PROMPT.format(text=text[:3000])
        try:
            response = await llm_gateway.chat(
                [
                    {"role": "system", "content": "你是严格的事实抽取器，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                provider="zhipu",
                temperature=0.1,
            )
            if not response or response.lstrip().startswith("[Mock]"):
                return self._fallback_experience(text)
            item = json.loads(self._clean_json(response))
            title = str(item.get("title") or "").strip()
            if not title:
                return self._fallback_experience(text)
            item["title"] = title[:200]
            item["experience_type"] = item.get("experience_type") or "other"
            item["tech_stack"] = item.get("tech_stack") or []
            item["evidence_text"] = text[:2000]
            item["verification_status"] = "user_confirmed"
            return item
        except Exception as exc:
            logger.warning("[ProfileAgent] 经历抽取失败，使用本地兜底: %s", exc)
            return self._fallback_experience(text)

    @staticmethod
    def _fallback_experience(text: str) -> dict:
        experience_type = "other"
        for keyword, label in (
            ("实习", "internship"), ("比赛", "competition"), ("竞赛", "competition"),
            ("科研", "research"), ("论文", "research"), ("工作", "work"),
            ("项目", "project"), ("开发", "project"), ("课程设计", "project"),
            ("证书", "credential"), ("认证", "credential"), ("四六级", "credential"),
            ("获奖", "award"), ("奖学金", "award"), ("担任", "leadership"),
        ):
            if keyword in text:
                experience_type = label
                break
        title = re.split(r"[，。；;！!？?\n]", text.strip())[0][:80]
        return {
            "experience_type": experience_type,
            "title": title or "待补充名称的经历",
            "description": text[:1000],
            "actions": text[:1000],
            "achievements": None,
            "tech_stack": [],
            "evidence_text": text[:2000],
            "verification_status": "user_confirmed",
        }

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
        experiences = profile.get("experiences", [])
        if projects:
            score = min(100, score + min(len(projects) * 3, 15))
        elif experiences:
            score = min(100, score + min(len(experiences) * 3, 15))

        # 技能是加分项
        skills = profile.get("skills", [])
        if skills:
            score = min(100, score + min(len(skills) * 2, 10))

        return {
            "completeness": min(100, score),
            "missing": missing,
            "ready": score >= 60 and bool(projects or experiences) and bool(skills),
        }

    def next_deep_interview_question(self, profile: dict, memory: dict | None = None) -> dict:
        """Choose one deterministic deep-dive question and return persistent state."""
        state = dict(memory or {})
        explored = list(dict.fromkeys(state.get("explored_dimensions") or []))
        skipped = list(dict.fromkeys(state.get("skipped_dimensions") or []))
        completed = set(explored) | set(skipped)

        next_item = next(
            (item for item in self.DEEP_INTERVIEW_DIMENSIONS if item[0] not in completed),
            None,
        )
        if not next_item:
            state.update({
                "phase": "completed",
                "last_dimension": None,
                "explored_dimensions": explored,
                "skipped_dimensions": skipped,
                "depth_score": 100,
            })
            return {"complete": True, "question": None, "state": state}

        dimension, question = next_item
        total = len(self.DEEP_INTERVIEW_DIMENSIONS)
        state.update({
            "phase": "deep_interview",
            "last_dimension": dimension,
            "explored_dimensions": explored,
            "skipped_dimensions": skipped,
            "depth_score": round(len(completed) / total * 100),
        })
        return {
            "complete": False,
            "dimension": dimension,
            "question": question,
            "state": state,
        }

    def record_deep_interview_answer(self, memory: dict | None, answer: str) -> dict:
        """Mark the last asked dimension explored or explicitly skipped."""
        state = dict(memory or {})
        dimension = state.get("last_dimension")
        if not dimension:
            return state
        explored = list(state.get("explored_dimensions") or [])
        skipped = list(state.get("skipped_dimensions") or [])
        if re.fullmatch(r"\s*(?:没有|无|暂时没有|跳过|不知道|不清楚)[。！!？?\s]*", answer or ""):
            if dimension not in skipped:
                skipped.append(dimension)
        elif not re.fullmatch(r"\s*(?:继续|继续问|追问我|深挖|开始)[。！!？?\s]*", answer or ""):
            if dimension not in explored:
                explored.append(dimension)
        state["explored_dimensions"] = explored
        state["skipped_dimensions"] = skipped
        state["last_dimension"] = None
        return state

    def resume_follow_up_questions(self, profile: dict, parsed: dict | None = None) -> list[str]:
        """Create actionable questions that connect resume parsing to profile discovery."""
        parsed = parsed or {}
        questions: list[str] = []
        projects = parsed.get("projects") or []
        if projects:
            first = projects[0]
            name = first.get("project_name") or "简历中的第一个项目"
            questions.append(f"在“{name}”中，哪一部分是你亲自完成的？遇到的最大难题和解决过程是什么？")
            if not first.get("highlights"):
                questions.append(f"“{name}”有没有可核验的结果，例如交付物、功能范围、测试结果或用户反馈？没有量化数字也可以。")
        else:
            questions.append("这份简历没有识别到项目。你做过哪些课程设计、个人项目、比赛或科研实践？")
        experience_types = {item.get("experience_type") for item in profile.get("experiences") or []}
        if not ({"internship", "work"} & experience_types):
            questions.append("简历中没有识别到实习或工作实践；你是否还有兼职、校内岗位、证书、比赛或奖项尚未写进这份简历？")
        else:
            questions.append("还有哪些证书、比赛、奖项或经历尚未写进这份简历？")
        return questions[:3]

    # ─── 工具方法 ─────────────────────────────────────────────────────

    def _get_missing_fields(self, collected: dict) -> list[str]:
        """获取缺失的字段名（按优先级排序）"""
        missing = []

        # 求职方向
        if not collected.get("preferred_job_types") and not collected.get("job_direction"):
            missing.append("求职方向")

        if not all(collected.get(field) for field in ("degree", "major", "school", "graduation_year")):
            missing.append("教育背景")

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

        experiences = collected.get("experiences") or []
        projects = collected.get("projects") or []
        if not experiences and not projects:
            missing.append("可用于求职的真实经历")
        elif experiences and any(
            not (item.get("actions") or item.get("description"))
            or not item.get("role")
            for item in experiences
        ):
            missing.append("经历中的角色、行动与成果")

        if not collected.get("skills"):
            missing.append("掌握的技能和工具")

        return missing

    @staticmethod
    def _fallback_question(missing: list[str]) -> str:
        """LLM 不可用时仍给出可继续填写的中文问题。"""
        question_map = {
            "求职方向": "你目前最想找哪一类岗位？例如后端开发、前端开发或 AI 算法。",
            "教育背景": "如果你没有简历也没关系：请告诉我你的最高学历、学校、专业和毕业年份。",
            "期望薪资范围": "你的期望月薪范围是多少？例如 15K-25K。",
            "希望工作的城市": "你希望在哪些城市工作？可以填写多个城市。",
            "对单休/双休的要求": "你对休息制度有什么要求：必须双休，还是可以接受单休？",
            "对加班的接受程度": "你对加班的接受程度是怎样的：不接受、偶尔可以，还是可以接受？",
            "对公司的规模偏好": "你更偏好大厂、中型公司、初创公司，还是都可以？",
            "是否接受远程办公": "你是否接受远程或混合办公？",
            "可用于求职的真实经历": "即使没有简历也没关系。你做过哪些课程设计、个人或开源项目、实习、比赛、科研、论文或社团实践？先选一段最能代表你的经历来说。",
            "经历中的角色、行动与成果": "针对刚才那段经历，你的具体角色是什么、亲自做了哪些事？如果有真实结果可以补充；没有量化结果也可以直接说没有。",
            "掌握的技能和工具": "这段经历中你实际使用过哪些语言、框架、软件或工具？只填写真正用过的即可。",
        }
        target = missing[0] if missing else ""
        return question_map.get(target, "请继续补充你的求职方向、期望薪资或工作城市。")

    @staticmethod
    def _extract_rule_based_updates(text: str) -> dict:
        """提取高确定性的中文画像字段，作为 LLM 抽取的稳定兜底。"""
        if not text:
            return {}

        updates: dict = {}
        lowered = text.lower()

        salary_match = re.search(
            r"(\d+(?:\.\d+)?)\s*([kK千]?)\s*(?:-|~|到|至)\s*(\d+(?:\.\d+)?)\s*([kK千]?)",
            text,
        )
        if salary_match:
            min_value = float(salary_match.group(1))
            max_value = float(salary_match.group(3))
            min_unit = salary_match.group(2)
            max_unit = salary_match.group(4)
            if min_unit or max_unit:
                min_value *= 1000
                max_value *= 1000
            updates["expected_salary_min"] = int(min_value)
            updates["expected_salary_max"] = int(max_value)

        cities = [
            "北京", "上海", "广州", "深圳", "杭州", "南京", "苏州", "成都",
            "重庆", "武汉", "西安", "长沙", "厦门", "天津", "青岛", "郑州",
            "合肥", "佛山", "东莞", "珠海", "无锡", "宁波",
        ]
        selected_cities = [
            city for city in cities
            if city in text and not re.search(rf"(?:不想去|不去|排除|不要)\s*{city}", text)
        ]
        if selected_cities:
            updates["preferred_locations"] = selected_cities

        directions = [
            ("后端", "后端开发"), ("前端", "前端开发"), ("全栈", "全栈开发"),
            ("AI算法", "AI算法"), ("ai 算法", "AI算法"), ("算法", "算法"),
            ("产品经理", "产品经理"), ("数据分析", "数据分析"),
            ("测试", "测试开发"), ("运维", "运维开发"),
        ]
        selected_directions = []
        for keyword, label in directions:
            if keyword.lower() in lowered and label not in selected_directions:
                selected_directions.append(label)
        if selected_directions:
            updates["preferred_job_types"] = selected_directions
        if any(keyword in lowered for keyword in ("agent", "智能体", "大模型应用")):
            updates["preferred_job_types"] = ["Agent应用研发"]

        degree_match = re.search(r"(?:最高学历(?:是|为)?\s*)?(大专|专科|本科|硕士|博士|高中)", text)
        if degree_match:
            updates["degree"] = "大专" if degree_match.group(1) == "专科" else degree_match.group(1)
        school_match = re.search(
            r"(?:学校(?:是|为)?|就读于?)\s*([\u4e00-\u9fa5A-Za-z0-9·]{2,30}(?:大学|学院|学校))",
            text,
        ) or re.search(r"([\u4e00-\u9fa5A-Za-z0-9·]{2,30}(?:大学|学院))", text)
        if school_match:
            updates["school"] = school_match.group(1)
        major_match = re.search(
            r"(?:专业(?:是|为)?\s*|就读)([\u4e00-\u9fa5A-Za-z0-9+.#·]{2,30}?)(?:专业|，|。|；|;|\s|$)",
            text,
        ) or re.search(r"([\u4e00-\u9fa5A-Za-z0-9+.#·]{2,20})专业", text)
        if major_match:
            updates["major"] = major_match.group(1).strip()
        graduation_match = re.search(r"(19\d{2}|20\d{2}|21\d{2})\s*年(?:毕业|应届)", text)
        if graduation_match:
            updates["graduation_year"] = int(graduation_match.group(1))
        if "应届" in text or "没有工作经验" in text:
            updates["years_of_experience"] = 0
        experience_years = re.search(r"(\d{1,2})\s*年(?:工作|开发|从业)经验", text)
        if experience_years:
            updates["years_of_experience"] = int(experience_years.group(1))

        if "必须双休" in text or ("双休" in text and "单休" not in text):
            updates["weekend_preference"] = "必须双休"
        elif "可接受单休" in text or "接受单休" in text:
            updates["weekend_preference"] = "可接受单休"

        if re.search(r"(?:完全不接受|任何(?:形式的)?加班都不接受|一点加班都不接受)", text):
            updates["overtime_tolerance"] = "不接受"
        elif re.search(r"(?:不接受|不能|拒绝|不想)加班", text):
            updates["overtime_tolerance"] = "不接受"
        elif re.search(r"(?:偶尔(?:正常)?加班|偶尔可以加班|可以接受偶尔(?:正常)?加班)", text):
            updates["overtime_tolerance"] = "偶尔"
        elif "接受加班" in text or "可以加班" in text:
            updates["overtime_tolerance"] = "接受"

        if "排斥高强度" in text or "不接受高强度" in text:
            updates["labor_intensity"] = "排斥高强度"
        elif "接受中等强度" in text:
            updates["labor_intensity"] = "接受中等"

        if "大厂" in text:
            updates["company_scale_pref"] = "大厂"
        elif "中型公司" in text or "中型企业" in text:
            updates["company_scale_pref"] = "中型"
        elif "初创" in text or "创业公司" in text:
            updates["company_scale_pref"] = "初创"
        elif re.search(r"(?:公司|规模).{0,8}(?:都行|都可以|无所谓|不限|没有要求)", text):
            updates["company_scale_pref"] = "无所谓"

        if re.search(r"(?:不接受|不要|拒绝)远程", text):
            updates["remote_work"] = "不接受"
        elif "完全远程" in text or "全远程" in text:
            updates["remote_work"] = "完全远程"
        elif "混合办公" in text or "混合工作" in text:
            updates["remote_work"] = "混合"
        elif "接受远程" in text or "可以远程" in text:
            updates["remote_work"] = "接受"

        return updates

    @staticmethod
    def _normalize_updates(updates: dict) -> dict:
        """过滤模型常见的伪空值，避免字符串 null 被持久化。"""
        invalid = {"", "null", "none", "unknown", "未提及", "未知", "n/a"}
        normalized = {}
        for key, value in (updates or {}).items():
            if value is None:
                continue
            if isinstance(value, str) and value.strip().lower() in invalid:
                continue
            if isinstance(value, list):
                value = [
                    item for item in value
                    if item is not None
                    and not (isinstance(item, str) and item.strip().lower() in invalid)
                ]
                if not value:
                    continue
            normalized[key] = value
        return normalized

    @staticmethod
    def _ground_updates_in_latest_turn(
        latest_user_message: str,
        previous_assistant_message: str,
        updates: dict,
        rule_updates: dict | None = None,
    ) -> dict:
        """只保留能由当前用户回复或紧邻问题支持的字段。

        历史消息只用于理解“都行”“改成上海”这类省略表达，不能让模型把数轮前
        已确认的加班、城市等字段重新当成本轮变更。
        """
        latest = latest_user_message or ""
        question = previous_assistant_message or ""
        question_is_confirmation = bool(re.search(
            r"为了避免误解|这个理解正确吗|回复[“\"']?正确|已确认并保存",
            question,
        ))
        anchored = set((rule_updates or {}).keys())
        evidence_patterns = {
            "job_direction": r"岗位|职位|方向|后端|前端|算法|测试|运维|产品|数据|agent|智能体|大模型",
            "preferred_job_types": r"岗位|职位|方向|后端|前端|算法|测试|运维|产品|数据|agent|智能体|大模型",
            "degree": r"学历|大专|专科|本科|硕士|博士|高中",
            "major": r"专业|计算机|软件工程|人工智能|电子信息|自动化",
            "school": r"学校|大学|学院",
            "graduation_year": r"毕业|应届|届|(?:19|20|21)\d{2}",
            "current_city": r"当前|目前|现在|所在.{0,4}(?:城市|地区)",
            "years_of_experience": r"工作年限|工作经验|开发经验|从业|应届|\d+\s*年",
            "expected_salary_min": r"薪资|工资|月薪|期望|\d+\s*[kK千]|\d+\s*万",
            "expected_salary_max": r"薪资|工资|月薪|期望|\d+\s*[kK千]|\d+\s*万",
            "preferred_locations": r"城市|地点|地区|北京|上海|广州|深圳|杭州|南京|苏州|成都|重庆|武汉|西安|长沙|厦门|天津|青岛|郑州|合肥|佛山|东莞|珠海|无锡|宁波",
            "weekend_preference": r"双休|单休|大小周|周末|休息",
            "overtime_tolerance": r"加班|工时|下班|996|995",
            "labor_intensity": r"加班|强度|内卷|工作量|996|995",
            "company_scale_pref": r"公司|企业|规模|大厂|中型|初创|创业|都行|都可以|无所谓|不限",
            "remote_work": r"远程|居家|混合办公|线下办公",
        }
        for field, pattern in evidence_patterns.items():
            if re.search(pattern, latest, flags=re.IGNORECASE):
                anchored.add(field)
                continue
            # A short answer may rely on the immediately preceding focused question.
            if (
                not question_is_confirmation
                and len(latest.strip()) <= 40
                and re.search(pattern, question, flags=re.IGNORECASE)
            ):
                anchored.add(field)

        return {
            key: value
            for key, value in (updates or {}).items()
            if key in anchored
        }

    @staticmethod
    def build_turn_acknowledgement(updates: dict, experience: dict | None = None) -> str:
        """Generate a concise acknowledgement tied to evidence from this turn."""
        items: list[str] = []
        directions = updates.get("preferred_job_types") or []
        if isinstance(directions, str):
            directions = [directions]
        if directions:
            items.append(f"目标方向为{'/'.join(directions)}")
        locations = updates.get("preferred_locations") or []
        if isinstance(locations, str):
            locations = [locations]
        if locations:
            items.append(f"意向城市为{'/'.join(locations)}")
        if updates.get("company_scale_pref"):
            label = updates["company_scale_pref"]
            items.append("公司规模不设限制" if label == "无所谓" else f"公司规模偏好为{label}")
        salary_min = updates.get("expected_salary_min")
        salary_max = updates.get("expected_salary_max")
        if salary_min and salary_max:
            items.append(f"期望月薪为{salary_min // 1000}K-{salary_max // 1000}K")
        if updates.get("degree"):
            items.append(f"最高学历为{updates['degree']}")
        if updates.get("remote_work"):
            items.append(f"远程办公偏好为{updates['remote_work']}")
        if updates.get("weekend_preference"):
            items.append(f"休息制度偏好为{updates['weekend_preference']}")
        if experience and experience.get("title"):
            items.append(f"新增经历“{experience['title']}”")
        if not items:
            return ""
        acknowledgement = "明白，已记录：" + "；".join(items) + "。"
        if directions and updates.get("company_scale_pref") == "无所谓":
            acknowledgement += " 后续会优先判断岗位内容是否真正对口，而不是按公司规模筛选。"
        return acknowledgement

    @staticmethod
    def _apply_semantic_guards(text: str, updates: dict, existing_info: dict) -> dict:
        """防止带范围限定的强度偏好被泛化为拒绝所有加班。"""
        guarded = dict(updates or {})
        rejects_high_intensity = bool(re.search(
            r"(?:不接受|不能接受|拒绝|排斥|不想要).{0,5}"
            r"(?:高强度|长期|经常|频繁|无休止).{0,5}加班",
            text,
        ))
        rejects_all_overtime = bool(re.search(
            r"(?:完全不接受加班|任何(?:形式的)?加班都不接受|一点加班都不接受|完全不能加班)",
            text,
        ))
        accepts_occasional = bool(re.search(
            r"(?:偶尔(?:正常)?加班(?:可以|能接受)?|可以接受偶尔(?:正常)?加班)",
            text,
        ))

        if rejects_high_intensity:
            guarded["labor_intensity"] = "排斥高强度"
            if rejects_all_overtime:
                guarded["overtime_tolerance"] = "不接受"
            elif accepts_occasional:
                guarded["overtime_tolerance"] = "偶尔"
            else:
                # 用户没有改变加班频率，只限定了不可接受的强度。
                guarded.pop("overtime_tolerance", None)
        return ProfileAgent._normalize_updates(guarded)

    @staticmethod
    def build_constraint_confirmation(
        user_message: str,
        updates: dict,
        existing_info: dict,
    ) -> Optional[dict]:
        """对会影响岗位硬过滤的工作强度偏好生成确认卡片数据。"""
        if updates.get("labor_intensity") != "排斥高强度":
            return None
        overtime = updates.get("overtime_tolerance") or existing_info.get("overtime_tolerance")
        if overtime == "偶尔":
            interpretation = "你可以接受偶尔、短期的正常加班，但不接受长期或高强度加班"
        elif overtime == "不接受":
            interpretation = "你不接受加班，并且明确排斥长期或高强度工作"
        elif overtime == "接受":
            interpretation = "你可以接受一般加班，但不接受长期或高强度加班"
        else:
            interpretation = "你不接受长期或高强度加班；对于偶尔正常加班是否可以，目前尚未确认"
        return {
            "raw_evidence": user_message,
            "updates": updates,
            "interpretation": interpretation,
            "message": f"为了避免误解，我的理解是：{interpretation}。这个理解正确吗？你可以回复“正确”，或直接说明需要修改的部分。",
        }

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
        intensity = info.get("labor_intensity", "")
        if overtime or intensity:
            if overtime == "偶尔" and intensity == "排斥高强度":
                workload = "可接受偶尔、短期的正常加班；不接受长期或高强度加班"
            elif overtime == "接受" and intensity == "排斥高强度":
                workload = "可接受一般加班；不接受长期或高强度加班"
            elif overtime == "不接受":
                workload = "不接受加班"
                if intensity == "排斥高强度":
                    workload += "（同时明确排斥高强度工作）"
            else:
                parts = []
                if overtime:
                    parts.append(f"加班频率：{overtime}")
                if intensity:
                    parts.append(f"工作强度：{intensity}")
                workload = "；".join(parts)
            lines.append(f"⏰ 工作强度偏好：{workload}")

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
        text = text.strip()
        # 模型偶尔会在 JSON 前后补一句解释，只截取最外层对象。
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
        return re.sub(r",\s*([}\]])", r"\1", text).strip()

    @staticmethod
    def _merge_resume_results(primary: dict, fallback: dict) -> dict:
        """本地规则只补模型遗漏的明确事实，不覆盖模型已经提取的内容。"""
        merged = dict(primary)
        for key, value in fallback.items():
            if not merged.get(key) and value:
                merged[key] = value
        merged.setdefault("education_list", [])
        merged.setdefault("projects", [])
        merged.setdefault("skills", [])
        return merged

    @staticmethod
    def _parse_resume_fallback(resume_text: str) -> dict:
        """模型不可用时，仅用原文中明确出现的内容生成最小画像。"""
        text = resume_text.strip()
        result: dict = {"education_list": [], "projects": [], "skills": []}

        def capture(pattern: str, flags: int = re.IGNORECASE) -> Optional[str]:
            match = re.search(pattern, text, flags)
            return match.group(1).strip() if match else None

        full_name = capture(r"(?:姓名|Name)\s*[:：]\s*([\u4e00-\u9fff·]{2,12}|[A-Za-z][A-Za-z .'-]{1,40})")
        if full_name:
            result["full_name"] = full_name

        degree_order = ["博士", "硕士", "本科", "大专", "专科"]
        degree = next((item for item in degree_order if item in text), None)
        if degree:
            result["degree"] = "大专" if degree == "专科" else degree

        school = capture(
            r"(?:学校|毕业院校|院校)\s*[:：]\s*([^\n，,；;]{2,40}(?:大学|学院)?)"
        )
        if not school:
            school = capture(r"^\s*([^\n]{2,30}(?:大学|学院))\s*$", re.MULTILINE)
        if school:
            result["school"] = school

        major = capture(r"(?:专业|Major)\s*[:：]\s*([^\n，,；;]{2,40})")
        if major:
            result["major"] = major

        graduation_year = capture(r"(?:毕业(?:时间|年份)?|Graduation)\s*[:：]?\s*((?:19|20)\d{2})")
        if graduation_year:
            result["graduation_year"] = int(graduation_year)

        current_city = capture(r"(?:现居|所在城市|当前城市)\s*[:：]\s*([\u4e00-\u9fff]{2,12})")
        if current_city:
            result["current_city"] = current_city

        years = capture(r"(\d{1,2})\s*年(?:以上)?工作经验")
        if years:
            result["years_of_experience"] = int(years)
        elif re.search(r"应届(?:生|毕业生)", text):
            result["years_of_experience"] = 0

        if school or major or degree:
            result["education_list"].append({
                "school": school or "",
                "major": major or "",
                "degree": result.get("degree", ""),
                "end_year": result.get("graduation_year"),
            })

        skill_catalog = {
            "Python": "编程语言", "Java": "编程语言", "JavaScript": "编程语言",
            "TypeScript": "编程语言", "C++": "编程语言", "Go": "编程语言",
            "Vue": "框架", "React": "框架", "FastAPI": "框架",
            "Django": "框架", "Spring Boot": "框架", "LangGraph": "框架",
            "MySQL": "数据库", "PostgreSQL": "数据库", "Redis": "数据库",
            "Docker": "工具", "Git": "工具", "Linux": "工具",
            "PyTorch": "框架", "TensorFlow": "框架", "SQL": "数据库",
        }
        for skill_name, category in skill_catalog.items():
            if re.search(rf"(?<![A-Za-z]){re.escape(skill_name)}(?![A-Za-z])", text, re.IGNORECASE):
                result["skills"].append({
                    "skill_name": skill_name,
                    "proficiency": "未标注",
                    "category": category,
                })

        project_names = re.findall(
            r"(?:项目名称|项目)\s*[:：]\s*([^\n，,；;]{2,60})", text
        )
        for project_name in dict.fromkeys(name.strip() for name in project_names):
            result["projects"].append({
                "project_name": project_name,
                "role": None,
                "description": None,
                "tech_stack": [],
                "highlights": None,
            })

        meaningful = any(
            result.get(key)
            for key in ("full_name", "degree", "school", "major", "graduation_year", "skills", "projects")
        )
        return result if meaningful else {}


# 全局单例
profile_agent = ProfileAgent()
