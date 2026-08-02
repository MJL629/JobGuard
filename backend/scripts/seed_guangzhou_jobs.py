"""
导入广州计算机岗位数据（2026-07-26 真实数据）

数据来源：多平台（BOSS直聘、猎聘、拉勾等）
Batch 1: 21 条 + Batch 2: 50 条 = 共 71 条
"""

import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.base import SessionLocal
from app.models.job import Job


def load_json(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        # 尝试找 jobs/items/data 等 key
        for key in ["jobs", "items", "data", "results"]:
            if key in data:
                return data[key]
        # 如果只有一层包装，尝试第一个 list value
        for v in data.values():
            if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                return v
        raise ValueError(f"无法从 dict 中提取岗位列表，keys: {list(data.keys())}")
    return data


def normalize_salary(salary_min, salary_max, salary_unit: str = "元/月") -> tuple[int | None, int | None]:
    """
    统一薪资为月薪（整数，单位：元）
    - 元/天 → × 22 天（实习日薪转月薪）
    - 元/月 → 不变
    - K/月 → × 1000
    - 万/年 → ÷ 12 × 10000
    """
    if salary_min is None and salary_max is None:
        return None, None

    unit = (salary_unit or "元/月").strip()

    def convert(val):
        if val is None:
            return None
        try:
            v = float(val)
        except (ValueError, TypeError):
            return None

        if "天" in unit:
            v = v * 22  # 日薪 → 月薪（22 工作日）
        elif "K" in unit or "k" in unit:
            v = v * 1000
        elif "万" in unit:
            if "年" in unit:
                v = v * 10000 / 12
            else:
                v = v * 10000

        return int(v)

    return convert(salary_min), convert(salary_max)


def insert_jobs(file_path: str, source_label: str) -> int:
    """导入单个 JSON 文件中的岗位"""
    jobs_data = load_json(file_path)
    db = SessionLocal()
    inserted = 0
    skipped = 0

    for item in jobs_data:
        company_name = (item.get("company_name") or "").strip()
        job_title = (item.get("job_title") or "").strip()

        if not company_name or not job_title:
            skipped += 1
            continue

        # 检查是否已存在（同公司同岗位）
        existing = (
            db.query(Job)
            .filter(
                Job.company_name == company_name,
                Job.job_title == job_title,
                Job.is_active == 1,
            )
            .first()
        )
        if existing:
            skipped += 1
            continue

        salary_min, salary_max = normalize_salary(
            item.get("salary_min"),
            item.get("salary_max"),
            item.get("salary_unit", "元/月"),
        )

        # 岗位分类映射
        category = item.get("job_category", "engineering")
        cat_map = {
            "工程": "engineering",
            "算法": "algorithm",
            "产品/数据/测试": "product_data_testing",
            "安全": "security",
            "engineering": "engineering",
            "algorithm": "algorithm",
            "product_data_testing": "product_data_testing",
            "security": "security",
        }
        job_category = cat_map.get(category, "engineering")

        job = Job(
            company_name=company_name,
            job_title=job_title,
            job_category=job_category,
            sub_category=item.get("sub_category"),
            salary_min=salary_min,
            salary_max=salary_max,
            location=item.get("location"),
            jd_text=item.get("jd_text"),
            requirements=item.get("requirements", []),
            benefits=item.get("benefits", []),
            source_url=item.get("source_url") or item.get("url"),
            source_type=item.get("source_type") or item.get("source") or source_label,
            posted_at=datetime.utcnow(),
            is_active=1,
        )
        db.add(job)
        inserted += 1

    db.commit()
    db.close()
    return inserted


if __name__ == "__main__":
    files = [
        ("/tmp/jobs_batch1.json", "广州多平台_batch1"),
        ("/tmp/jobs_batch2.json", "广州多平台_batch2"),
    ]

    total = 0
    for path, label in files:
        if not os.path.exists(path):
            print(f"[SKIP] 文件不存在: {path}")
            continue
        count = insert_jobs(path, label)
        print(f"[OK] {label}: 导入 {count} 条岗位")
        total += count

    # 验证
    db = SessionLocal()
    total_db = db.query(Job).filter(Job.is_active == 1).count()
    guangzhou_count = db.query(Job).filter(
        Job.is_active == 1,
        Job.location.contains("广州"),
    ).count()
    db.close()

    print(f"\n导入完成！")
    print(f"  数据库总岗位数: {total_db}")
    print(f"  广州地区岗位数: {guangzhou_count}")
