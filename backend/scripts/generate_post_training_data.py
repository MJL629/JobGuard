"""Generate deterministic SFT and preference datasets for JD extraction."""

from __future__ import annotations

import json
import random
from pathlib import Path


SYSTEM = "你是精确的岗位信息抽取器。只输出合法 JSON，不要解释，不要 Markdown。"
COMPANIES = ["星河科技", "云帆数据", "安盾网络", "智源机器人", "远景智能", "深蓝软件", "极光互联", "启明信息"]
JOBS = [
    ("大模型算法工程师", "algorithm", "大模型算法", ["Python", "PyTorch", "LoRA", "RAG"]),
    ("AI Infra工程师", "engineering", "AI Infra", ["Python", "CUDA", "vLLM", "Kubernetes"]),
    ("后端开发工程师", "engineering", "后端开发", ["Python", "FastAPI", "MySQL", "Redis"]),
    ("AI安全工程师", "security", "AI安全", ["Python", "红队评测", "提示词攻击", "内容安全"]),
]
LOCATIONS = ["北京海淀", "上海浦东", "深圳南山", "杭州余杭", "成都高新"]


def build(index: int) -> dict:
    company = COMPANIES[index % len(COMPANIES)]
    title, category, sub, skills = JOBS[(index // len(COMPANIES)) % len(JOBS)]
    location = LOCATIONS[index % len(LOCATIONS)]
    salary_min = 15000 + (index % 6) * 3000
    salary_max = salary_min + 10000
    experience = ["应届生", "1-3年", "3-5年"][index % 3]
    education = ["本科", "硕士", "不限"][index % 3]
    raw = (
        f"{company}招聘{title}，工作地点{location}，月薪{salary_min // 1000}K-"
        f"{salary_max // 1000}K，经验要求{experience}，学历{education}。"
        f"要求掌握{'、'.join(skills)}，全职，五险一金。"
    )
    output = {
        "company_name": company,
        "job_title": title,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_type": "月薪",
        "location": location,
        "experience_required": experience,
        "education_required": education,
        "job_category": category,
        "sub_category": sub,
        "requirements": skills,
        "benefits": ["五险一金"],
        "employment_type": "全职",
    }
    prompt = f"请从下面岗位描述中提取结构化字段：\n{raw}"
    return {"id": f"synthetic-{index:03d}", "system": SYSTEM, "prompt": prompt, "response": json.dumps(output, ensure_ascii=False)}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    rows = [build(index) for index in range(160)]
    random.Random(42).shuffle(rows)
    root = Path("data/post_training")
    write_jsonl(root / "sft_train.jsonl", rows[:120])
    write_jsonl(root / "sft_val.jsonl", rows[120:140])
    write_jsonl(root / "sft_test.jsonl", rows[140:])

    preferences = []
    for row in rows[:100]:
        correct = json.loads(row["response"])
        rejected = dict(correct)
        rejected.pop("company_name", None)
        rejected["job_category"] = "engineering" if correct["job_category"] != "engineering" else "algorithm"
        rejected["salary_min"] = str(correct["salary_min"] // 1000) + "K"
        preferences.append({
            "id": row["id"], "system": row["system"], "prompt": row["prompt"],
            "chosen": row["response"], "rejected": json.dumps(rejected, ensure_ascii=False),
        })
    write_jsonl(root / "preference_train.jsonl", preferences[:80])
    write_jsonl(root / "preference_test.jsonl", preferences[80:])
    print(json.dumps({"sft_train": 120, "sft_val": 20, "sft_test": 20, "preference_train": 80, "preference_test": 20}))


if __name__ == "__main__":
    main()
