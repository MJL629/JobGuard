"""
Resume Generator Agent

Responsibilities:
1. RAG retrieve user projects from knowledge base, filtered by target job
2. Select and rank top 2-3 most relevant projects
3. Rewrite project descriptions tailored to job direction
4. Inject matching skill keywords naturally
5. Generate self-evaluation paragraph
6. Assemble full resume in Markdown
7. Generate greeting message for job application
"""

import json
import logging
from typing import Optional

from app.llm.gateway import llm_gateway
from app.rag.user_kb import user_kb

logger = logging.getLogger(__name__)


# ─── 事实核查 Prompt ────────────────────────────────────────────────

FACT_CHECK_PROMPT = """你是一位严格的简历审核员。请检查以下简历内容是否存在事实编造。

## 用户真实画像
{user_profile}

## 生成的简历内容
{resume_text}

## 检查规则
1. **技能编造**: 简历中提到的技能是否在用户画像中存在？不存在的标注[推断/编造]
2. **学历造假**: 学校、专业、学位是否与画像一致？
3. **经历夸大**: 项目描述是否超出了原始项目范围？是否有凭空添加的成果？
4. **数字编造**: 简历中的量化数据（如"提升50%"）是否有原始依据？

## 输出格式
```json
{{
  "has_fabrications": true/false,
  "fabrications": [
    {{
      "type": "skill_fabrication/education_fabrication/experience_exaggeration/number_fabrication",
      "original": "编造的内容",
      "fact": "真实情况",
      "severity": "critical/high/medium/low",
      "suggestion": "修改建议"
    }}
  ],
  "confidence_score": 0-100 (简历可信度),
  "summary": "核查总结"
}}
```

只输出 JSON。"""


RESUME_SAFEGUARD_PROMPT = """你是一位专业的简历优化师。请根据事实核查结果修正简历。

## 原始简历
{resume_text}

## 事实核查结果
{fact_check_result}

## 修正规则
1. 删除所有编造的技能（标注为 skill_fabrication 的）
2. 将夸大的描述改回真实水平（标注为 experience_exaggeration 的）
3. 修正不实的学历信息（标注为 education_fabrication 的）
4. 将无依据的数字改为定性描述或删除（标注为 number_fabrication 的）
5. 保留所有真实内容不变
6. 在简历末尾添加注释标记哪些内容经过核查

## 输出
直接输出修正后的完整简历 Markdown，不要 JSON。"""



# ─── Prompts ───────────────────────────────────────────────────────────

PROJECT_SELECTION_PROMPT = """You are a resume optimization expert. Select the most relevant projects for a job application.

## Target Job
- Company: {company_name}
- Title: {job_title}
- Category: {job_category} / {sub_category}
- Requirements: {requirements}
- JD Summary: {jd_summary}

## Candidate's Projects
{projects_text}

## Task
Select the 2-3 most relevant projects. For each selected project, explain:
1. Why it matches the job (relevance)
2. What angle to emphasize (e.g. backend: highlight system design; algorithm: highlight model performance)

## Output Format
```json
{{
  "selected_projects": [
    {{
      "project_index": 0-based index from the list above,
      "project_name": "name",
      "relevance_reason": "why this project matches",
      "emphasis_angle": "what to highlight",
      "relevance_score": 0.0-1.0
    }}
  ]
}}
```
Only output JSON."""


PROJECT_REWRITE_PROMPT = """You are a professional resume writer. Rewrite a project description for a specific job application.

## Target Job
- Title: {job_title}
- Category: {job_category}
- JD Requirements: {requirements}

## Original Project
- Name: {project_name}
- Role: {role}
- Description: {description}
- Tech Stack: {tech_stack}
- Highlights: {highlights}

## Emphasis Angle
{emphasis_angle}

## Rewriting Rules
1. Use STAR method (Situation, Task, Action, Result) implicitly
2. Include quantifiable results (numbers, percentages)
3. Use strong action verbs (Designed, Implemented, Optimized, Led, Built)
4. Naturally incorporate matching keywords from JD requirements
5. Keep each bullet point 1-2 lines, total 3-5 bullet points
6. Tailor the description to the emphasis angle

## Output Format
```json
{{
  "project_name": "name",
  "rewritten_description": "3-5 bullet points, each starting with a strong verb, containing quantifiable results",
  "tech_tags": ["tech1", "tech2"]
}}
```
Only output JSON."""


SELF_EVALUATION_PROMPT = """You are a resume expert. Write a self-evaluation / career summary for a candidate.

## Candidate Info
- Degree: {degree}
- Major: {major}
- School: {school}
- Years of Experience: {years_of_experience}
- Skills: {skills}

## Target Job
- Company: {company_name}
- Title: {job_title}
- JD Summary: {jd_summary}

## Requirements
- 2-3 sentences
- Highlight the candidate's most relevant strengths for this job
- Match the tone of the target company
- Include 1-2 specific skills or achievements
- Do NOT use cliches like "hardworking", "team player", "detail-oriented"
- Be specific and authentic

Output only the self-evaluation text, no JSON, no quotes."""


RESUME_ASSEMBLY_PROMPT = """You are a professional resume formatter. Assemble a complete resume in clean Markdown.

## Candidate Information
{profile_info}

## Selected Projects (already rewritten)
{selected_projects}

## Self Evaluation
{self_evaluation}

## Target Job
{job_info}

## Output Format
```markdown
# {Full Name}

{Contact Info line: City | Phone | Email}

## Job Target
**{Job Title}**

## Self Evaluation
{Self evaluation text}

## Education
{Education entries}

## Skills
{Skills grouped by category}

## Project Experience
### {Project Name}
*{Role}* | {Time Period}

{3-5 bullet points of rewritten description}

**Tech Stack:** {tech tags}

### {Project Name 2}
...
```

## Rules
- Use clean, professional formatting
- Keep it to 1 page worth of content (be selective)
- Education section: only list the highest degree if multiple
- Skills section: group by category, max 10-12 skills
- Project section: most relevant project first

Output the complete resume in Markdown. No extra commentary."""


GREETING_PROMPT = """You are helping a job seeker write a short greeting message for a job application.

## Candidate Info
- Degree: {degree}
- School: {school}
- Key Strengths: {key_strengths}

## Target Job
- Company: {company_name}
- Title: {job_title}

## Requirements
- 3-5 sentences max
- Polite and professional
- Mention 1-2 specific reasons why you're a good fit
- Include a call to action (e.g. "looking forward to discussing further")
- Match Chinese workplace communication style

Output only the greeting text, no JSON, no quotes."""


# ─── Agent ─────────────────────────────────────────────────────────────

class ResumeGeneratorAgent:
    """Resume Generator Agent"""

    async def generate(
        self,
        user_profile: dict,
        job_info: dict,
        max_projects: int = 3,
    ) -> dict:
        """
        Generate a tailored resume and greeting for a job.

        Args:
            user_profile: Full user profile from profile_service
            job_info: Structured job info from job_parser
            max_projects: Max projects to include

        Returns:
            {resume_markdown, greeting, selected_projects, self_evaluation}
        """
        company_name = job_info.get("company_name", "Target Company")
        job_title = job_info.get("job_title", "Target Position")
        logger.info(f"[ResumeGen] Generating resume for {company_name} - {job_title}")

        # 1. RAG retrieve user projects
        projects = await self._retrieve_projects(user_profile, job_info)

        if not projects:
            logger.warning("[ResumeGen] No projects found for user")
            return {
                "error": "No project experience found. Please add projects to your profile first.",
                "resume_markdown": "",
                "greeting": "",
            }

        # 2. Select and rank projects
        selected = await self._select_projects(projects, job_info, max_projects)
        logger.info(f"[ResumeGen] Selected {len(selected)} projects")

        # 3. Rewrite each project description
        rewritten = []
        for proj in selected:
            rw = await self._rewrite_project(proj, job_info)
            rewritten.append(rw)

        # 4. Generate self evaluation
        self_eval = await self._generate_self_evaluation(user_profile, job_info)

        # 5. Assemble resume
        resume_md = await self._assemble_resume(user_profile, job_info, rewritten, self_eval)

        # 6. Generate greeting
        greeting = await self._generate_greeting(user_profile, job_info, rewritten)

        return {
            "resume_markdown": resume_md,
            "greeting": greeting,
            "selected_projects": [
                {"project_name": p.get("project_name"), "relevance_score": p.get("relevance_score")}
                for p in selected
            ],
            "self_evaluation": self_eval,
        }

    # ─── RAG Retrieve Projects ─────────────────────────────────────

    async def _retrieve_projects(self, user_profile: dict, job_info: dict) -> list[dict]:
        """Retrieve user projects from RAG knowledge base, filtered by job relevance"""
        user_id = str(user_profile.get("user_id", "1"))

        # Build search query from job requirements
        requirements = job_info.get("requirements", [])
        job_title = job_info.get("job_title", "")
        sub_category = job_info.get("sub_category", "")

        query_parts = [job_title, sub_category] + (requirements[:5] if requirements else [])
        query = " ".join(query_parts)

        try:
            # Try RAG first
            results = await user_kb.search(
                user_id, query, top_k=10,
                filter_metadata={"type": "project"},
            )

            if results:
                logger.info(f"[ResumeGen] RAG retrieved {len(results)} projects")
                return [
                    {"content": r["content"], "metadata": r.get("metadata", {}), "source": "rag"}
                    for r in results
                ]
        except Exception as e:
            logger.warning(f"[ResumeGen] RAG search failed: {e}")

        # Fallback: use projects from user_profile directly
        projects = user_profile.get("projects", [])
        if projects:
            logger.info(f"[ResumeGen] Using {len(projects)} projects from profile (fallback)")
            return [
                {
                    "content": self._project_to_text(p),
                    "metadata": {"project_name": p.get("project_name", ""), "type": "project"},
                    "source": "profile",
                }
                for p in projects
            ]

        return []

    # ─── Select Projects ───────────────────────────────────────────

    async def _select_projects(
        self, projects: list[dict], job_info: dict, max_count: int
    ) -> list[dict]:
        """Select top projects using LLM"""
        if len(projects) <= max_count:
            # If few projects, add relevance_score=1.0 and return all
            return [{**p, "relevance_score": 1.0} for p in projects]

        # Format projects for LLM
        projects_text = ""
        for i, p in enumerate(projects):
            projects_text += f"\n[{i}] {p['content'][:300]}\n"

        jd_text = job_info.get("jd_raw_text", "") or job_info.get("job_description", "")
        requirements = job_info.get("requirements", [])

        prompt = PROJECT_SELECTION_PROMPT.format(
            company_name=job_info.get("company_name", ""),
            job_title=job_info.get("job_title", ""),
            job_category=job_info.get("job_category", ""),
            sub_category=job_info.get("sub_category", ""),
            requirements=json.dumps(requirements[:10], ensure_ascii=False),
            jd_summary=jd_text[:500],
            projects_text=projects_text,
        )

        messages = [
            {"role": "system", "content": "You are a JSON output engine."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat(messages, provider="zhipu", temperature=0.2)
            result = json.loads(self._clean_json(response))
            selected_indices = result.get("selected_projects", [])

            # Map back to original projects
            selected = []
            for sel in selected_indices[:max_count]:
                idx = sel.get("project_index", 0)
                if 0 <= idx < len(projects):
                    selected.append({
                        **projects[idx],
                        "emphasis_angle": sel.get("emphasis_angle", ""),
                        "relevance_reason": sel.get("relevance_reason", ""),
                        "relevance_score": sel.get("relevance_score", 0.8),
                    })

            return selected if selected else projects[:max_count]

        except Exception as e:
            logger.error(f"[ResumeGen] Project selection failed: {e}")
            return projects[:max_count]

    # ─── Rewrite Project ───────────────────────────────────────────

    async def _rewrite_project(self, project: dict, job_info: dict) -> dict:
        """Rewrite a single project description"""
        content = project.get("content", "")
        metadata = project.get("metadata", {})

        # Parse project info from content or metadata
        project_name = metadata.get("project_name", "") or self._extract_field(content, "project_name")
        role = metadata.get("role", "") or self._extract_field(content, "role")
        description = content
        tech_stack_str = metadata.get("tech_stack", "[]")

        try:
            tech_stack = json.loads(tech_stack_str) if isinstance(tech_stack_str, str) else tech_stack_str
        except (json.JSONDecodeError, TypeError):
            tech_stack = []

        prompt = PROJECT_REWRITE_PROMPT.format(
            job_title=job_info.get("job_title", ""),
            job_category=job_info.get("job_category", ""),
            requirements=json.dumps(job_info.get("requirements", [])[:5], ensure_ascii=False),
            project_name=project_name,
            role=role,
            description=description[:1000],
            tech_stack=json.dumps(tech_stack, ensure_ascii=False) if tech_stack else "[]",
            highlights=project.get("highlights", ""),
            emphasis_angle=project.get("emphasis_angle", "General match"),
        )

        messages = [
            {"role": "system", "content": "You are a JSON output engine."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat(messages, provider="zhipu", temperature=0.5)
            return json.loads(self._clean_json(response))
        except Exception as e:
            logger.error(f"[ResumeGen] Project rewrite failed: {e}")
            return {
                "project_name": project_name,
                "rewritten_description": description[:500],
                "tech_tags": tech_stack if isinstance(tech_stack, list) else [],
            }

    # ─── Self Evaluation ────────────────────────────────────────────

    async def _generate_self_evaluation(self, user_profile: dict, job_info: dict) -> str:
        """Generate self evaluation paragraph"""
        basic = user_profile.get("basic", {})
        skills_list = user_profile.get("skills", [])

        skills_text = ", ".join(
            f"{s.get('skill_name', '')}" for s in (skills_list or [])[:8]
        ) if skills_list else "Various technical skills"

        jd_text = job_info.get("jd_raw_text", "") or job_info.get("job_description", "")

        prompt = SELF_EVALUATION_PROMPT.format(
            degree=basic.get("degree", ""),
            major=basic.get("major", ""),
            school=basic.get("school", ""),
            years_of_experience=basic.get("years_of_experience", 0),
            skills=skills_text,
            company_name=job_info.get("company_name", ""),
            job_title=job_info.get("job_title", ""),
            jd_summary=jd_text[:500],
        )

        messages = [
            {"role": "system", "content": "You are a professional resume writer."},
            {"role": "user", "content": prompt},
        ]

        try:
            return await llm_gateway.chat(messages, provider="zhipu", temperature=0.6)
        except Exception as e:
            logger.error(f"[ResumeGen] Self evaluation failed: {e}")
            return "Experienced developer with strong technical skills and a passion for building impactful products."

    # ─── Assemble Resume ────────────────────────────────────────────

    async def _assemble_resume(
        self,
        user_profile: dict,
        job_info: dict,
        rewritten_projects: list[dict],
        self_eval: str,
    ) -> str:
        """Assemble full resume in Markdown"""
        basic = user_profile.get("basic", {})
        education = user_profile.get("education", [])
        skills = user_profile.get("skills", [])

        # Format profile info
        profile_info = {
            "full_name": basic.get("full_name", "Your Name"),
            "city": basic.get("current_city", ""),
            "phone": basic.get("phone", ""),
            "email": basic.get("email", ""),
            "degree": basic.get("degree", ""),
            "school": basic.get("school", ""),
            "major": basic.get("major", ""),
            "years": basic.get("years_of_experience", 0),
            "skills": skills,
            "education": education,
        }

        prompt = RESUME_ASSEMBLY_PROMPT.format(
            profile_info=json.dumps(profile_info, ensure_ascii=False, indent=2),
            selected_projects=json.dumps(rewritten_projects, ensure_ascii=False, indent=2),
            self_evaluation=self_eval,
            job_info=json.dumps({
                "title": job_info.get("job_title", ""),
                "company": job_info.get("company_name", ""),
            }, ensure_ascii=False),
        )

        messages = [
            {"role": "system", "content": "You are a professional resume formatter. Output clean Markdown."},
            {"role": "user", "content": prompt},
        ]

        try:
            return await llm_gateway.chat(messages, provider="zhipu", temperature=0.3)
        except Exception as e:
            logger.error(f"[ResumeGen] Assembly failed: {e}")
            return self._build_fallback_resume(user_profile, job_info, rewritten_projects, self_eval)

    def _build_fallback_resume(
        self, user_profile: dict, job_info: dict, projects: list[dict], self_eval: str
    ) -> str:
        """Build a basic resume when LLM is unavailable"""
        basic = user_profile.get("basic", {})
        skills = user_profile.get("skills", [])
        education = user_profile.get("education", [])

        lines = []
        lines.append(f"# {basic.get('full_name', 'Your Name')}")
        lines.append("")
        lines.append(f"{basic.get('current_city', '')} | {basic.get('email', '')}")
        lines.append("")
        lines.append(f"## Job Target")
        lines.append(f"**{job_info.get('job_title', 'Target Position')}**")
        lines.append("")
        lines.append("## Self Evaluation")
        lines.append(self_eval)
        lines.append("")

        if education:
            lines.append("## Education")
            for edu in education[:1]:
                lines.append(f"- {edu.get('degree', '')} in {edu.get('major', '')}, {edu.get('school', '')}")
            lines.append("")

        if skills:
            lines.append("## Skills")
            skill_names = [s.get("skill_name", "") for s in skills[:10]]
            lines.append(", ".join(skill_names))
            lines.append("")

        lines.append("## Project Experience")
        for i, proj in enumerate(projects):
            lines.append(f"### {proj.get('project_name', f'Project {i+1}')}")
            desc = proj.get("rewritten_description", "")
            lines.append(desc)
            tags = proj.get("tech_tags", [])
            if tags:
                lines.append(f"**Tech Stack:** {', '.join(tags)}")
            lines.append("")

        return "\n".join(lines)

    # ─── Greeting ───────────────────────────────────────────────────

    async def _generate_greeting(
        self, user_profile: dict, job_info: dict, rewritten_projects: list[dict]
    ) -> str:
        """Generate greeting message for job application"""
        basic = user_profile.get("basic", {})

        # Extract key strengths from rewritten projects
        key_strengths = []
        for proj in rewritten_projects[:2]:
            name = proj.get("project_name", "")
            desc = proj.get("rewritten_description", "")[:100]
            if name:
                key_strengths.append(f"{name}: {desc}")

        prompt = GREETING_PROMPT.format(
            degree=basic.get("degree", ""),
            school=basic.get("school", ""),
            key_strengths="\n".join(key_strengths) if key_strengths else "Relevant project experience",
            company_name=job_info.get("company_name", ""),
            job_title=job_info.get("job_title", ""),
        )

        messages = [
            {"role": "system", "content": "You are a helpful career assistant."},
            {"role": "user", "content": prompt},
        ]

        try:
            return await llm_gateway.chat(messages, provider="zhipu", temperature=0.5)
        except Exception as e:
            logger.error(f"[ResumeGen] Greeting failed: {e}")
            return (
                f"Hello! I'm interested in the {job_info.get('job_title', '')} position "
                f"at {job_info.get('company_name', 'your company')}. "
                f"My background in {basic.get('major', 'computer science')} and "
                f"relevant project experience make me a strong fit. "
                f"Looking forward to discussing further!"
            )

    # ─── Utils ──────────────────────────────────────────────────────

    @staticmethod
    def _project_to_text(project: dict) -> str:
        """Convert project dict to searchable text"""
        parts = []
        for key in ["project_name", "role", "description", "highlights"]:
            val = project.get(key, "")
            if val:
                parts.append(f"{key}: {val}")
        tech = project.get("tech_stack", [])
        if tech:
            parts.append(f"tech_stack: {', '.join(tech) if isinstance(tech, list) else str(tech)}")
        return "\n".join(parts)

    @staticmethod
    def _extract_field(text: str, field: str) -> str:
        """Extract field value from structured text"""
        for line in text.split("\n"):
            if line.lower().startswith(f"{field}:"):
                return line.split(":", 1)[1].strip()
        return ""

    @staticmethod
    def _clean_json(text: str) -> str:
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()


    # ─── 事实核查 ────────────────────────────────────────────────

    async def fact_check_resume(
        self, user_profile: dict, resume_text: str
    ) -> dict:
        """
        对生成的简历进行事实核查，防止编造

        Args:
            user_profile: 用户真实画像
            resume_text: 生成��简历 Markdown

        Returns:
            核查结果 dict
        """
        basic = user_profile.get("basic", {})
        skills = user_profile.get("skills", [])
        projects = user_profile.get("projects", [])

        profile_summary = {
            "学历": {
                "学校": basic.get("school"),
                "专业": basic.get("major"),
                "学位": basic.get("degree"),
                "毕业年份": basic.get("graduation_year"),
            },
            "真实技能": [s.get("skill_name") for s in (skills or [])[:20]],
            "真实项目": [
                {
                    "名称": p.get("project_name"),
                    "角色": p.get("role"),
                    "描述": (p.get("description") or "")[:200],
                    "技术栈": p.get("tech_stack", []),
                    "亮点": p.get("highlights", ""),
                }
                for p in (projects or [])[:5]
            ],
            "工作年限": basic.get("years_of_experience", 0),
        }

        prompt = FACT_CHECK_PROMPT.format(
            user_profile=json.dumps(profile_summary, ensure_ascii=False, indent=2),
            resume_text=resume_text[:5000],
        )

        messages = [
            {"role": "system", "content": "你是一个严格的简历审核员。只输出 JSON。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat(messages, provider="zhipu", temperature=0.1)
            result = json.loads(self._clean_json(response))
            logger.info(
                f"[ResumeGen] Fact check: has_fabrications={result.get('has_fabrications')}, "
                f"confidence={result.get('confidence_score')}"
            )
            return result
        except Exception as e:
            logger.error(f"[ResumeGen] Fact check failed: {e}")
            return {
                "has_fabrications": False,
                "fabrications": [],
                "confidence_score": 80,
                "summary": "事实核查未能完成，请人工审核简历内容",
            }

    async def safeguard_resume(
        self, user_profile: dict, resume_text: str, fact_check: dict
    ) -> str:
        """
        根据事实核查结果修正简历，移除编造内容

        Returns:
            修正后的简历 Markdown
        """
        if not fact_check.get("has_fabrications"):
            return resume_text

        prompt = RESUME_SAFEGUARD_PROMPT.format(
            resume_text=resume_text,
            fact_check_result=json.dumps(fact_check, ensure_ascii=False, indent=2),
        )

        messages = [
            {"role": "system", "content": "你是一位专业的简历优化师。输出修正后的 Markdown 简历。"},
            {"role": "user", "content": prompt},
        ]

        try:
            corrected = await llm_gateway.chat(messages, provider="zhipu", temperature=0.3)
            logger.info("[ResumeGen] Resume safeguarded - fabrications removed")
            return corrected
        except Exception as e:
            logger.error(f"[ResumeGen] Safeguard failed: {e}")
            return resume_text  # 返回原文，不做修改


# Global singleton
resume_generator = ResumeGeneratorAgent()
