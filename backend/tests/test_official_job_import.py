from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.job import Job
from app.services.official_job_import_service import OfficialJobImportService


def test_beijing_open_data_record_is_normalized_with_provenance():
    result = OfficialJobImportService().normalize_record({
        "单位名称": "北京示例科技有限公司",
        "岗位名称": "Python 后端开发工程师",
        "招聘岗位id": "BJ-10086",
        "最低月薪": "15K",
        "最高月薪": "25K",
        "工作地点": "北京市海淀区",
        "文化程度": "本科",
        "岗位描述": "负责 FastAPI 服务开发；熟悉 MySQL；要求良好沟通能力",
        "发布日期": "2026-07-02",
    })

    assert result["company_name"] == "北京示例科技有限公司"
    assert result["job_title"] == "Python 后端开发工程师"
    assert result["salary_min"] == 15000
    assert result["salary_max"] == 25000
    assert result["source_type"] == "beijing_hr_open_data"
    assert result["source_url"].endswith("#job-BJ-10086")
    assert result["requirements"][0] == "学历要求：本科"


def test_missing_company_or_title_is_not_imported_as_fake_job():
    service = OfficialJobImportService()
    assert service.normalize_record({"岗位名称": "后端工程师"}) is None
    assert service.normalize_record({"单位名称": "示例公司"}) is None


def test_source_fingerprint_is_stable_when_dataset_has_no_job_id():
    service = OfficialJobImportService()
    record = {
        "单位名称": "示例公司",
        "岗位名称": "数据分析师",
        "工作地点": "北京",
    }
    first = service.normalize_record(record)
    second = service.normalize_record(record)
    assert first["source_url"] == second["source_url"]


def test_salary_parser_rejects_implausible_values():
    assert OfficialJobImportService._money("1.5万") == 15000
    assert OfficialJobImportService._money("15K") == 15000
    assert OfficialJobImportService._money("9999999元") is None


def test_combined_monthly_and_annual_salary_ranges_are_normalized():
    service = OfficialJobImportService()
    assert service._salary_range("月薪(元):8000-10000") == (8000, 10000)
    assert service._salary_range("年薪(元):120000-240000") == (10000, 20000)
    assert service._salary_range("时薪(元):30-50") == (None, None)


def test_preview_schema_salary_range_is_supported():
    result = OfficialJobImportService().normalize_record({
        "企业名称": "北京示例科技有限公司",
        "岗位名称": "软件测试工程师",
        "招聘岗位id": "API-001",
        "薪资范围": "月薪(元):12000-18000",
        "用工形式": "全职",
        "招聘人数": "2",
        "岗位要求": "熟悉自动化测试和 Python",
    })
    assert result["salary_min"] == 12000
    assert result["salary_max"] == 18000
    assert "用工形式：全职" in result["jd_text"]


def test_frontend_title_is_not_misclassified_as_backend():
    assert OfficialJobImportService._classify("Vue 前端开发工程师") == (
        "engineering", "前端开发"
    )


def test_official_registration_dates_and_external_id_are_mapped():
    observed_at = datetime(2026, 8, 2, 9, 30)
    result = OfficialJobImportService().normalize_record(
        {
            "企业名称": "北京示例科技有限公司",
            "岗位名称": "数据工程师",
            "招聘岗位id": "BJ-2026-42",
            "登记开始时间": "2/7/2026",
            "登记结束时间": "31/8/2026",
        },
        observed_at=observed_at,
    )

    assert result["source_external_id"] == "BJ-2026-42"
    assert result["source_published_at"] == datetime(2026, 7, 2)
    assert result["posted_at"] == datetime(2026, 7, 2)
    assert result["expires_at"] == datetime(2026, 8, 31, 23, 59, 59)
    assert result["last_seen_at"] == observed_at


def test_beijing_csv_dates_are_day_first_not_month_first():
    service = OfficialJobImportService()
    assert service._date("9/6/2026") == datetime(2026, 6, 9)
    assert service._date("15/5/2026") == datetime(2026, 5, 15)


def test_missing_or_invalid_source_dates_are_not_replaced_with_current_time():
    result = OfficialJobImportService().normalize_record({
        "企业名称": "北京示例科技有限公司",
        "岗位名称": "数据工程师",
        "招聘岗位id": "BJ-2026-43",
        "登记开始时间": "未知",
    })

    assert result["source_published_at"] is None
    assert result["posted_at"] is None
    assert result["expires_at"] is None


def test_fallback_external_id_is_stable_without_official_job_id():
    service = OfficialJobImportService()
    record = {
        "企业名称": "北京示例科技有限公司",
        "岗位名称": "数据工程师",
        "工作地点": "北京市海淀区",
    }

    first = service.normalize_record(record)
    second = service.normalize_record(record)

    assert first["source_external_id"] == second["source_external_id"]
    assert len(first["source_external_id"]) == 20


def test_import_deduplicates_by_external_id_and_does_not_deactivate_unseen_by_default():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    source_url = "https://example.test/jobs"
    try:
        session.add_all([
            Job(
                id=92001,
                company_name="旧名称",
                job_title="旧岗位名",
                job_category="other",
                source_type="beijing_hr_open_data",
                source_external_id="BJ-42",
                source_url=f"{source_url}#job-BJ-42",
                is_active=1,
            ),
            Job(
                id=92002,
                company_name="仍在数据库的公司",
                job_title="本批次未见岗位",
                job_category="other",
                source_type="beijing_hr_open_data",
                source_external_id="BJ-UNSEEN",
                source_url=f"{source_url}#job-BJ-UNSEEN",
                is_active=1,
            ),
        ])
        session.commit()
        records = [
            {"企业名称": "新名称", "岗位名称": "新岗位名", "招聘岗位id": "BJ-42"},
            {"企业名称": "重复行", "岗位名称": "重复岗位", "招聘岗位id": "BJ-42"},
        ]

        summary = OfficialJobImportService().import_records(
            session,
            records,
            source_url=source_url,
        )

        assert summary.updated == 1
        assert summary.inserted == 0
        assert summary.skipped == 1
        assert session.get(Job, 92001).company_name == "新名称"
        assert session.get(Job, 92001).last_seen_at is not None
        assert session.get(Job, 92002).is_active == 1

        OfficialJobImportService().import_records(
            session,
            records,
            source_url=source_url,
            deactivate_unseen=True,
        )
        assert session.get(Job, 92002).is_active == 0

        expired_record = [{
            "企业名称": "新名称",
            "岗位名称": "新岗位名",
            "招聘岗位id": "BJ-42",
            "登记结束时间": "1/1/2020",
        }]
        OfficialJobImportService().import_records(
            session,
            expired_record,
            source_url=source_url,
            deactivate_expired=True,
        )
        assert session.get(Job, 92001).is_active == 0
    finally:
        session.close()
        engine.dispose()
