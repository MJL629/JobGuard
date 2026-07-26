"""
批量岗位种子数据灌入脚本
读取 data/seed_jobs_batch4.json，写入 MySQL
"""
import json
import os
import sys
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.orm import Session
from app.models.base import SessionLocal, engine, Base
from app.models.job import Job
from app.models.company import Company
from app.rag.company_kb import company_kb


def load_jobs() -> list[dict]:
    path = os.path.join(os.path.dirname(__file__), "..", "data", "seed_jobs_batch4.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def salary_to_monthly(salary_min: int, salary_max: int, unit: str) -> tuple[int, int]:
    if unit == "元/天":
        return salary_min * 22, salary_max * 22
    return salary_min, salary_max


def seed_jobs(db: Session):
    jobs = load_jobs()
    print(f"准备灌入 {len(jobs)} 条岗位数据 (Batch 4)...")

    created_companies = set()
    created_jobs = 0

    for item in jobs:
        company_name = item["company_name"]
        job_title = item["job_title"]
        source_url = item.get("source_url", f"batch4_{company_name}_{job_title}")

        company = db.query(Company).filter(Company.name == company_name).first()
        if not company:
            company = Company(
                name=company_name,
                industry=item.get("company_industry"),
                scale=item.get("company_size"),
                address=item.get("location"),
                risk_score=0.0,
                data_source="seed_data_batch4",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(company)
            db.flush()
            created_companies.add(company_name)

        job = db.query(Job).filter(Job.source_url == source_url).first()
        if not job:
            job = Job()
            db.add(job)
            created_jobs += 1

        salary_min_monthly, salary_max_monthly = salary_to_monthly(
            item["salary_min"], item["salary_max"], item.get("salary_unit", "元/月")
        )

        job.company_name = company_name
        job.company_id = company.id
        job.job_title = job_title
        job.job_category = item.get("job_category", "工程")
        job.sub_category = item.get("sub_category")
        job.salary_min = salary_min_monthly
        job.salary_max = salary_max_monthly
        job.location = item.get("location")
        job.jd_text = item.get("jd_text")
        job.requirements = item.get("requirements", [])
        job.benefits = item.get("benefits", [])
        job.source_url = source_url
        job.source_type = item.get("source_type", "BOSS直聘")
        job.posted_at = datetime.utcnow()
        job.is_active = 1

        db.flush()
        print(f"  ✅ {company_name} - {job_title} (id={job.id}, salary={salary_min_monthly}-{salary_max_monthly}元/月)")

    db.commit()
    print(f"\nMySQL 灌入完成：新增公司 {len(created_companies)} 家，新增岗位 {created_jobs} 条")
    print(f"  跳过重复岗位: {len(jobs) - created_jobs} 条")
    return jobs


async def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_jobs(db)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
