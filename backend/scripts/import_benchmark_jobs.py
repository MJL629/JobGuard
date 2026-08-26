"""把公开评测样本补充到演示岗位库，最多补到指定总量；不删除现有岗位。"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from app.models.base import SessionLocal
from app.models.job import Job


def infer_category(title: str, skills: list[str]) -> tuple[str, str]:
    text = f"{title} {' '.join(skills)}".lower()
    rules = [
        (("security", "安全", "渗透"), ("security", "网络与信息安全")),
        (("frontend", "前端", "react", "vue"), ("engineering", "前端开发")),
        (("backend", "后端", "java", "golang", "spring"), ("engineering", "后端开发")),
        (("devops", "sre", "运维", "kubernetes"), ("engineering", "运维开发")),
        (("data", "数据", "analyst", "sql"), ("product_data_testing", "数据分析")),
        (("machine learning", "ai", "算法", "llm", "人工智能"), ("algorithm", "人工智能算法")),
        (("test", "测试", "qa"), ("product_data_testing", "测试开发")),
        (("product", "产品"), ("product_data_testing", "产品经理")),
    ]
    for keys, result in rules:
        if any(key in text for key in keys):
            return result
    return "engineering", "软件研发"


def parse_salary(value) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    text = str(value).replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*[-~—至]\s*(\d+(?:\.\d+)?)\s*[kK]", text)
    if match:
        return int(float(match.group(1)) * 1000), int(float(match.group(2)) * 1000)
    return None, None


def main(target_total: int) -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "eval" / "jobguard_benchmark" / "benchmark.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda item: item.get("label_quality") != "gold")
    db = SessionLocal()
    try:
        active_count = db.query(Job).filter(Job.is_active == 1).count()
        needed = max(0, target_total - active_count)
        added = 0
        for item in rows:
            if added >= needed:
                break
            source_url = f"benchmark://{item['id']}"
            if db.query(Job.id).filter(Job.source_url == source_url).first():
                continue
            skills = item.get("skills") or []
            category, sub_category = infer_category(item.get("position") or "", skills)
            salary_min, salary_max = parse_salary(item.get("salary"))
            db.add(Job(
                company_name=item.get("expected_company") or "公开数据岗位",
                job_title=item.get("position") or "待确认岗位",
                job_category=category,
                sub_category=sub_category,
                salary_min=salary_min,
                salary_max=salary_max,
                location=item.get("location"),
                jd_text=item.get("jd_text"),
                requirements=skills,
                benefits=[],
                source_url=source_url,
                source_type="公开评测数据",
                posted_at=datetime.utcnow(),
                is_active=1,
            ))
            added += 1
        db.commit()
        final_count = db.query(Job).filter(Job.is_active == 1).count()
        print(f"新增 {added} 条，当前有效岗位 {final_count} 条。")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-total", type=int, default=500)
    args = parser.parse_args()
    main(args.target_total)
