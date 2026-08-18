import pytest

from app.agents.resume_generator import RESUME_ASSEMBLY_PROMPT, resume_generator


def test_resume_assembly_prompt_formats_without_treating_markdown_examples_as_fields():
    prompt = RESUME_ASSEMBLY_PROMPT.format(
        profile_info="{}",
        selected_projects="[]",
        self_evaluation="真实自评",
        job_info="{}",
    )

    assert "# [Full Name]" in prompt
    assert "[Project Name]" in prompt


def test_ungrounded_resume_numbers_are_detected_without_using_database_ids():
    profile = {
        "user_id": 99,
        "completeness": 80,
        "basic": {"graduation_year": 2024},
        "projects": [{"id": 123, "description": "接口耗时降低 20%"}],
    }

    issues = resume_generator._find_ungrounded_numbers(
        profile,
        "2024 年毕业，接口耗时降低 20%，服务 99 名用户，项目编号 123。",
    )

    assert {item["original"] for item in issues} == {"99", "123"}


def test_profile_grounded_numbers_are_allowed():
    profile = {
        "basic": {"graduation_year": 2024},
        "projects": [{"description": "并发用户 500，接口耗时降低 20%"}],
    }

    assert resume_generator._find_ungrounded_numbers(
        profile,
        "2024 年毕业；支持 500 并发用户；接口耗时降低 20%。",
    ) == []


@pytest.mark.asyncio
async def test_generate_discards_fabricated_draft_and_uses_grounded_fallback(monkeypatch):
    async def retrieve(*args, **kwargs):
        return [{"content": "真实项目没有量化结果", "metadata": {"project_name": "真实项目"}}]

    async def select(projects, job_info, max_projects):
        return [{**projects[0], "relevance_score": 1.0}]

    async def rewrite(*args, **kwargs):
        return {"project_name": "真实项目", "rewritten_description": "性能提升 99%", "tech_tags": []}

    async def self_evaluation(*args, **kwargs):
        return "基于真实画像"

    async def assemble(*args, **kwargs):
        return "# 用户\n\n项目性能提升 99%"

    async def greeting(*args, **kwargs):
        return "您好"

    async def fact_check(*args, **kwargs):
        return {
            "verification_status": "completed",
            "has_fabrications": False,
            "fabrications": [],
        }

    async def cannot_safeguard(*args, **kwargs):
        return None

    monkeypatch.setattr(resume_generator, "_retrieve_projects", retrieve)
    monkeypatch.setattr(resume_generator, "_select_projects", select)
    monkeypatch.setattr(resume_generator, "_rewrite_project", rewrite)
    monkeypatch.setattr(resume_generator, "_generate_self_evaluation", self_evaluation)
    monkeypatch.setattr(resume_generator, "_assemble_resume", assemble)
    monkeypatch.setattr(resume_generator, "_generate_greeting", greeting)
    monkeypatch.setattr(resume_generator, "fact_check_resume", fact_check)
    monkeypatch.setattr(resume_generator, "safeguard_resume", cannot_safeguard)

    result = await resume_generator.generate(
        user_profile={"basic": {}, "projects": [{"project_name": "真实项目"}]},
        job_info={"job_title": "后端开发", "company_name": "目标公司"},
    )

    assert "error" not in result
    assert "99%" not in result["resume_markdown"]
    assert result["fact_check"]["verification_status"] == "deterministic_grounded"


@pytest.mark.asyncio
async def test_generate_returns_text_only_fallback_when_profile_has_no_projects(monkeypatch):
    async def retrieve(*args, **kwargs):
        return []

    monkeypatch.setattr(resume_generator, "_retrieve_projects", retrieve)

    result = await resume_generator.generate(
        user_profile={
            "basic": {"full_name": "小明", "major": "计算机科学与技术", "current_city": "广州"},
            "skills": [{"skill_name": "Python"}, {"skill_name": "FastAPI"}],
            "projects": [],
        },
        job_info={"job_title": "后端开发工程师", "company_name": "目标公司"},
    )

    assert "error" not in result
    assert result["output_mode"] == "text_only"
    assert result["fact_check"]["verification_status"] == "text_only_fallback"
    assert "后端开发工程师" in result["resume_markdown"]
    assert "打招呼" not in result["resume_markdown"]
    assert result["greeting"]
