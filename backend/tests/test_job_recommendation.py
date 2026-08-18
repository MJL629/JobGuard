from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.job import Job
from app.services.job_service import job_service


def test_profile_matching_job_receives_explainable_high_score():
    profile = {
        "basic": {
            "expected_salary_min": 15000,
            "expected_salary_max": 22000,
        },
        "preferences": {
            "preferred_job_types": ["后端开发"],
            "preferred_locations": ["广州", "深圳"],
        },
        "skills": [
            {"skill_name": "Java"},
            {"skill_name": "MySQL"},
            {"skill_name": "Spring Boot"},
        ],
    }
    job = {
        "job_title": "Java 后端开发工程师",
        "job_category": "技术",
        "sub_category": "后端开发",
        "location": "广州",
        "salary_min": 16000,
        "salary_max": 23000,
        "requirements": ["Java", "MySQL", "Spring Boot"],
    }

    result = job_service._score_job(profile, job)

    assert result["match_score"] == 100
    assert result["evidence_coverage"] == 100
    assert result["score_breakdown"]["direction"]["score"] == 25
    assert result["score_breakdown"]["skills"]["score"] == 35
    assert any("方向" in reason for reason in result["match_reasons"])
    assert any("3/3" in reason for reason in result["match_reasons"])
    assert result["match_concerns"] == []
    assert result["hard_constraint_status"] == "clear"


def test_profile_mismatch_is_not_reported_as_a_recommendation_match():
    profile = {
        "basic": {
            "expected_salary_min": 20000,
            "expected_salary_max": 25000,
        },
        "preferences": {
            "preferred_job_types": ["后端开发"],
            "preferred_locations": ["广州"],
        },
        "skills": [{"skill_name": "Java"}],
    }
    job = {
        "job_title": "视觉设计师",
        "job_category": "设计",
        "sub_category": "视觉设计",
        "location": "北京",
        "salary_min": 8000,
        "salary_max": 12000,
        "requirements": ["Figma", "Photoshop"],
    }

    result = job_service._score_job(profile, job)

    assert result["match_score"] == 0
    assert result["match_reasons"] == []
    assert result["evidence_coverage"] == 100
    assert len(result["hard_conflicts"]) == 3
    assert any("技能缺口" in item for item in result["match_concerns"])


def test_missing_profile_fields_do_not_receive_neutral_scores():
    result = job_service._score_job(
        {"basic": {}, "preferences": {}, "skills": []},
        {
            "job_title": "测试工程师",
            "job_category": "技术",
            "sub_category": "软件测试",
            "location": "杭州",
            "salary_min": 10000,
            "salary_max": 15000,
            "requirements": ["Python"],
        },
    )

    assert result["match_score"] is None
    assert result["evidence_coverage"] == 0
    assert result["match_reasons"] == []
    assert all(item["score"] is None for item in result["score_breakdown"].values())
    assert "暂不显示" in result["match_concerns"][0]


def test_hard_workload_conflict_is_reported_and_caps_score():
    profile = {
        "basic": {"expected_salary_min": 15000},
        "preferences": {
            "preferred_job_types": ["后端开发"],
            "preferred_locations": ["广州"],
            "weekend_preference": "必须双休",
            "labor_intensity": "排斥高强度",
        },
        "skills": [{"skill_name": "Python"}],
    }
    job = {
        "job_title": "Python后端工程师",
        "location": "广州",
        "salary_min": 18000,
        "salary_max": 25000,
        "requirements": ["Python"],
        "jd_text": "团队目前大小周，业务高峰期可能长期加班",
    }

    result = job_service._score_job(profile, job)

    assert result["match_score"] == 49
    assert result["hard_constraint_status"] == "conflict"
    assert len(result["hard_conflicts"]) == 2


def test_less_than_half_evidence_is_not_shown_as_percentage():
    result = job_service._score_job(
        {
            "basic": {},
            "preferences": {
                "preferred_job_types": ["后端开发"],
                "preferred_locations": ["广州"],
            },
            "skills": [],
        },
        {"job_title": "Java后端工程师", "location": "广州"},
    )
    assert result["evidence_coverage"] == 45
    assert result["match_score"] is None


def test_agent_application_direction_matches_agent_and_rag_jobs():
    assert job_service._direction_matches(
        "Agent应用研发", "AI应用与Agent工程实习生 大模型应用"
    )
    assert job_service._direction_matches(
        "Agent应用研发", "算法开发实习生（RAG与Agent方向） AI算法"
    )
    assert not job_service._direction_matches(
        "Agent应用研发", "Java后端开发工程师 后端开发"
    )


def test_analyzing_existing_job_reuses_row_without_overwriting_source():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        original = Job(
            id=92001,
            company_name="官方示例公司",
            job_title="原始岗位",
            job_category="engineering",
            source_type="official_source",
            source_url="https://example.gov.cn/job/92001",
            jd_text="官方原始岗位内容",
            is_active=1,
        )
        session.add(original)
        session.flush()

        result = job_service._upsert_job(
            session,
            {
                "company_name": "用户粘贴公司",
                "job_title": "用户粘贴岗位",
                "jd_raw_text": "用户编辑后的内容",
            },
            company_id=None,
            existing_job_id=92001,
        )

        assert result.id == 92001
        assert session.query(Job).count() == 1
        assert original.company_name == "官方示例公司"
        assert original.jd_text == "官方原始岗位内容"
    finally:
        session.close()
        engine.dispose()


def test_list_jobs_excludes_expired_jobs_by_default():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    now = datetime.utcnow()
    try:
        session.add_all([
            Job(
                id=91001,
                company_name="示例公司",
                job_title="仍有效岗位",
                job_category="other",
                is_active=1,
                expires_at=now + timedelta(days=1),
            ),
            Job(
                id=91002,
                company_name="示例公司",
                job_title="无截止日期岗位",
                job_category="other",
                is_active=1,
                expires_at=None,
            ),
            Job(
                id=91003,
                company_name="示例公司",
                job_title="已过期岗位",
                job_category="other",
                is_active=1,
                expires_at=now - timedelta(days=1),
            ),
        ])
        session.commit()

        result = job_service.list_jobs(session)

        assert result["total"] == 2
        assert {item["id"] for item in result["items"]} == {91001, 91002}
    finally:
        session.close()
        engine.dispose()


def test_list_jobs_deduplicates_same_company_title_and_city_with_provenance():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add_all([
            Job(
                id=93001,
                company_name="广州示例智能科技有限公司",
                job_title="Agent应用研发工程师",
                job_category="algorithm",
                location="广州·天河区",
                source_type="job_board",
                source_url="https://example.test/jobs/93001",
                jd_text="Python LangGraph",
                is_active=1,
            ),
            Job(
                id=93002,
                company_name="广州示例智能科技有限公司",
                job_title="Agent应用研发工程师",
                job_category="algorithm",
                location="广州市海珠区",
                source_type="other",
                source_url=None,
                jd_text="Python LangGraph",
                is_active=1,
            ),
            Job(
                id=93003,
                company_name="广州示例智能科技有限公司",
                job_title="Agent应用研发工程师",
                job_category="algorithm",
                location="深圳市南山区",
                source_type="job_board",
                source_url="https://example.test/jobs/93003",
                is_active=1,
            ),
        ])
        session.commit()

        result = job_service.list_jobs(session, page_size=20)

        assert result["source_record_total"] == 3
        assert result["total"] == 2
        guangzhou = next(item for item in result["items"] if "广州" in item["location"])
        assert guangzhou["id"] == 93001
        assert guangzhou["duplicate_count"] == 2
        assert set(guangzhou["merged_job_ids"]) == {93001, 93002}
    finally:
        session.close()
        engine.dispose()


def test_upsert_job_reuses_same_identity_when_source_url_is_missing():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        existing = Job(
            id=94001,
            company_name="复用示例公司",
            job_title="后端开发工程师",
            job_category="engineering",
            location="广州·天河区",
            source_type="job_board",
            source_url="https://example.test/jobs/94001",
            jd_text="官方来源内容",
            is_active=1,
        )
        session.add(existing)
        session.flush()

        result = job_service._upsert_job(
            session,
            {
                "company_name": "复用示例公司",
                "job_title": "后端开发工程师",
                "location": "广州市海珠区",
                "jd_raw_text": "用户再次粘贴的内容",
            },
            company_id=None,
        )

        assert result.id == 94001
        assert session.query(Job).count() == 1
        assert existing.jd_text == "官方来源内容"
    finally:
        session.close()
        engine.dispose()
