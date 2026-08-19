"""
Job Matcher Agent

Matches user profile against job database to recommend suitable positions.
"""

import asyncio
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session
from app.config import settings
from app.llm.gateway import llm_gateway

logger = logging.getLogger(__name__)

MATCH_SYSTEM_PROMPT = """You are a job matching expert. Evaluate how well a candidate fits a job.
## Match Dimensions (score each 0-100)
1. Skill match: How well do candidate skills match requirements?
2. Experience match: Is project experience relevant?
3. Salary match: Is salary within candidate's expected range?
4. Location match: Is location acceptable?
5. Intensity match: Does work schedule match preferences?

## Output
```json
{{
  "skill_match": 0-100,
  "experience_match": 0-100,
  "salary_match": 0-100,
  "location_match": 0-100,
  "intensity_match": 0-100,
  "overall_score": 0-100 (weighted: skills 35%, experience 25%, salary 15%, location 10%, intensity 15%),
  "match_level": "excellent/good/fair/poor",
  "match_reasons": ["reason 1", "reason 2"],
  "concerns": ["concern 1 (if any)"],
  "recommendation": "strongly_recommend/recommend/consider/skip"
}}
```
Only output JSON."""

MATCH_USER_PROMPT = """## Candidate Profile
{user_profile}

## Job
- Company: {company_name}
- Title: {job_title}
- Category: {category}
- Requirements: {requirements}
- Salary: {salary_min}-{salary_max}
- Location: {location}
- JD Summary: {jd_summary}"""

MATCH_PROMPT = MATCH_SYSTEM_PROMPT + "\n\n" + MATCH_USER_PROMPT


class JobMatcherAgent:
    """Job Matcher Agent"""

    async def match_single(
        self, user_profile: dict, job: dict
    ) -> dict:
        """Match a single job against user profile"""
        basic = user_profile.get("basic", {})
        prefs = user_profile.get("preferences", {})
        skills = user_profile.get("skills", [])

        profile_text = json.dumps({
            "degree": basic.get("degree"),
            "major": basic.get("major"),
            "school": basic.get("school"),
            "experience_years": basic.get("years_of_experience", 0),
            "skills": [s.get("skill_name") for s in (skills or [])[:15]],
            "expected_salary": f"{basic.get('expected_salary_min', 0)}-{basic.get('expected_salary_max', 0)}",
            "preferred_locations": prefs.get("preferred_locations", []),
            "weekend_preference": prefs.get("weekend_preference"),
            "overtime_tolerance": prefs.get("overtime_tolerance"),
        }, ensure_ascii=False)

        requirements = job.get("requirements", [])
        if isinstance(requirements, str):
            requirements = [requirements]

        prompt = MATCH_USER_PROMPT.format(
            user_profile=profile_text,
            company_name=job.get("company_name", ""),
            job_title=job.get("job_title", ""),
            category=job.get("sub_category", job.get("job_category", "")),
            requirements=json.dumps(requirements[:10], ensure_ascii=False),
            salary_min=job.get("salary_min", "?"),
            salary_max=job.get("salary_max", "?"),
            location=job.get("location", ""),
            jd_summary=(job.get("jd_text", "") or "")[:500],
        )

        messages = [
            {"role": "system", "content": MATCH_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await llm_gateway.chat(
                messages,
                provider="zhipu",
                temperature=0.2,
                metadata={"agent_name": "job_matcher"},
            )
            return json.loads(self._clean_json(response))
        except Exception as e:
            logger.error(f"[JobMatcher] Match failed: {e}")
            return {
                "overall_score": 50,
                "match_level": "fair",
                "match_reasons": ["Unable to evaluate"],
                "recommendation": "consider",
            }

    async def match_batch(
        self, user_profile: dict, jobs: list[dict], top_k: int = 10
    ) -> list[dict]:
        """Match multiple jobs and return top matches (with concurrency limit)"""
        concurrency = max(1, settings.job_match_llm_concurrency)
        semaphore = asyncio.Semaphore(concurrency)
        
        async def match_one(job):
            try:
                async with semaphore:
                    match = await self.match_single(user_profile, job)
            except Exception as exc:
                # Unexpected single-item failures degrade in place so callers keep
                # an explicit job/result mapping and the batch cardinality is stable.
                logger.error(
                    "[JobMatcher] Batch match item failed (job_id=%s, error_type=%s)",
                    job.get("id"),
                    type(exc).__name__,
                )
                match = {
                    "overall_score": 0,
                    "match_level": "poor",
                    "match_reasons": ["该岗位匹配暂时失败"],
                    "concerns": ["模型调用失败，请稍后重试"],
                    "recommendation": "skip",
                    "degraded": True,
                    "error_type": type(exc).__name__,
                }
            return {
                "job": {
                    "id": job.get("id"),
                    "company_name": job.get("company_name"),
                    "job_title": job.get("job_title"),
                    "salary_min": job.get("salary_min"),
                    "salary_max": job.get("salary_max"),
                    "location": job.get("location"),
                    "sub_category": job.get("sub_category"),
                },
                "match": match,
            }
        
        tasks = [match_one(job) for job in jobs[:top_k]]
        valid_results = await asyncio.gather(*tasks)

        # Sort by overall score descending
        valid_results.sort(key=lambda x: x["match"].get("overall_score", 0), reverse=True)
        return valid_results[:top_k]

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


job_matcher = JobMatcherAgent()
