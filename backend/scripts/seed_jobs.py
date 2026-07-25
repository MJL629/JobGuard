"""
岗位种子数据灌入脚本
读取 data/seed_jobs.json，写入 MySQL 和 Chroma 公司知识库
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
from app.llm.gateway import llm_gateway


def load_jobs() -> list[dict]:
    path = os.path.join(os.path.dirname(__file__), "..", "data", "seed_jobs.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def salary_to_monthly(salary_min: int, salary_max: int, unit: str) -> tuple[int, int]:
    """把日薪转成月薪（按22天/月），保留原始单位"""
    if unit == "元/天":
        return salary_min * 22, salary_max * 22
    return salary_min, salary_max


def seed_jobs(db: Session):
    jobs = load_jobs()
    print(f"准备灌入 {len(jobs)} 条岗位数据...")

    created_companies = set()

    for item in jobs:
        company_name = item["company_name"]
        job_title = item["job_title"]
        source_url = item["source_url"]

        # 1. 创建或更新 Company
        company = db.query(Company).filter(Company.name == company_name).first()
        if not company:
            company = Company(
                name=company_name,
                industry=item.get("company_industry"),
                scale=item.get("company_size"),
                address=item.get("location"),
                risk_score=0.0,
                data_source="seed_data",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(company)
            db.flush()
            created_companies.add(company_name)

        # 2. 创建或更新 Job
        job = db.query(Job).filter(Job.source_url == source_url).first()
        if not job:
            job = Job()
            db.add(job)

        salary_min_monthly, salary_max_monthly = salary_to_monthly(
            item["salary_min"], item["salary_max"], item.get("salary_unit", "元/天")
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
        print(f"  ✅ {company_name} - {job_title} (id={job.id})")

    db.commit()
    print(f"\nMySQL 灌入完成：新增公司 {len(created_companies)} 家，岗位 {len(jobs)} 条")
    return jobs


async def seed_company_kb(jobs: list[dict]):
    """把岗位分析文本写入公司知识库"""
    print("\n开始写入 Chroma 公司知识库...")
    for item in jobs:
        analysis_text = (
            f"公司：{item['company_name']}\n"
            f"行业：{item.get('company_industry', '未知')}\n"
            f"规模：{item.get('company_size', '未知')}\n"
            f"融资阶段：{item.get('company_financing', '未知')}\n"
            f"岗位：{item['job_title']}\n"
            f"薪资：{item['salary_min']}-{item['salary_max']}{item.get('salary_unit', '元/天')}\n"
            f"地点：{item.get('location', '未知')}\n"
            f"JD：{item.get('jd_text', '')[:500]}\n"
            f"福利：{', '.join(item.get('benefits', []))}\n"
        )
        try:
            await company_kb.add_analysis(
                company_name=item["company_name"],
                job_title=item["job_title"],
                analysis_text=analysis_text,
                metadata={
                    "salary_min": item["salary_min"],
                    "salary_max": item["salary_max"],
                    "location": item.get("location"),
                    "sub_category": item.get("sub_category"),
                    "company_size": item.get("company_size"),
                    "company_financing": item.get("company_financing"),
                },
            )
        except Exception as e:
            print(f"  ⚠️ 写入知识库失败 {item['company_name']}: {e}")
    print("Chroma 公司知识库写入完成")


async def main():
    # 初始化表（如果不存在）
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        jobs = seed_jobs(db)
        await seed_company_kb(jobs)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
