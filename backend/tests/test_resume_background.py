import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import profile as profile_api
from app.models.base import Base
from app.models.resume import UserResume


@pytest.mark.asyncio
async def test_background_resume_parse_persists_terminal_status(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    session = Session()
    try:
        resume = UserResume(
            user_id=7,
            original_name="resume.txt",
            stored_path="data/uploads/7/resume.txt",
            sha256="a" * 64,
            media_type="text/plain",
            parser="text-decoder",
            extracted_text="姓名：测试用户\n学校：测试大学\n技能：Python",
            extracted_chars=28,
            parse_status="pending",
        )
        session.add(resume)
        session.commit()
        resume_id = resume.id

        monkeypatch.setattr(profile_api, "SessionLocal", Session)

        async def fake_process_resume(db, user_id, resume_text, **kwargs):
            assert user_id == 7
            assert "测试大学" in resume_text
            return {
                "parsed": {
                    "school": "测试大学",
                    "projects": [],
                    "skills": [{"skill_name": "Python"}],
                },
                "completeness": 30,
                "missing_fields": [],
            }

        monkeypatch.setattr(
            profile_api.profile_service, "process_resume", fake_process_resume
        )

        await profile_api._process_resume_background(resume_id, 7)

        session.expire_all()
        updated = session.get(UserResume, resume_id)
        assert updated.parse_status == "parsed"
        assert updated.parse_error is None
        assert updated.structured_data["school"] == "测试大学"
    finally:
        session.close()
        engine.dispose()

