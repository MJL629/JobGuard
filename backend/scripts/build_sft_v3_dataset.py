"""Build JobGuard SFT v3 multi-task dataset.

The builder is deterministic and does not call any LLM.  It converts existing
JobGuard seed jobs and public Beijing job CSV rows into instruction-tuning
examples for:

1. JD structured extraction
2. job classification
3. risk wording detection
4. skill normalization

Gold labels can be reviewed later in the generated ``gold_review_candidates``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
DEFAULT_OUT = ROOT / "finetune" / "jobguard_sft_v3" / "dataset"
RANDOM_SEED = 20260901

TECH_ALIASES = {
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "vue": "Vue",
    "react": "React",
    "python": "Python",
    "java": "Java",
    "spring": "Spring",
    "springboot": "Spring Boot",
    "spring boot": "Spring Boot",
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "redis": "Redis",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "rag": "RAG",
    "llm": "LLM",
    "agent": "Agent",
    "langgraph": "LangGraph",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "sft": "SFT",
    "lora": "LoRA",
    "dpo": "DPO",
    "mcp": "MCP",
    "fastapi": "FastAPI",
}

CATEGORY_RULES = [
    ("大模型应用", ["大模型", "llm", "agent", "智能体", "rag", "langgraph", "提示工程"]),
    ("算法", ["算法", "机器学习", "深度学习", "pytorch", "tensorflow", "推荐系统"]),
    ("后端开发", ["后端", "java", "spring", "go", "python", "服务端", "接口"]),
    ("前端开发", ["前端", "vue", "react", "javascript", "typescript", "html", "css"]),
    ("数据分析", ["数据分析", "bi", "sql", "tableau", "powerbi", "数据挖掘"]),
    ("测试运维", ["测试", "运维", "devops", "sre", "自动化测试"]),
]

RISK_RULES = {
    "薪资范围异常": ["上不封顶", "面议", "4k-30k", "薪资无责", "综合薪资"],
    "加班强度暗示": ["996", "大小周", "单休", "抗压", "加班", "奋斗者"],
    "培训引流风险": ["培训", "缴费", "贷款", "就业班", "包就业"],
    "KPI/销售伪装": ["邀约", "拉新", "地推", "电销", "获客", "转化"],
    "经验要求矛盾": ["应届", "3年以上", "5年以上", "专家"],
}


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_seed_jobs() -> list[dict]:
    rows: list[dict] = []
    for path in sorted((ROOT / "data").glob("seed_jobs*.json")):
        for index, item in enumerate(read_json(path)):
            rows.append(normalize_job({
                **item,
                "source_file": path.name,
                "source_row": index,
            }))
    return rows


def load_beijing_csv(limit: int | None = None) -> list[dict]:
    path = PROJECT_ROOT / "data" / "北京市人力资源和社会保障局-单位招聘岗位信息.csv"
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="gb18030", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            title = first(row, "岗位名称", "招聘岗位", "职位名称")
            jd = first(row, "岗位要求", "岗位描述", "职位描述", "招聘条件")
            if not title or not jd:
                continue
            rows.append(normalize_job({
                "company_name": first(row, "企业名称", "单位名称", "招聘单位"),
                "job_title": title,
                "jd_text": jd,
                "location": first(row, "工作地点", "单位地址", "登记机关"),
                "salary_text": first(row, "薪资范围", "薪资待遇", "工资待遇"),
                "source_type": "beijing_hr_open_data",
                "source_url": "https://data.beijing.gov.cn/",
                "source_file": path.name,
                "source_row": index,
            }))
            if limit and len(rows) >= limit:
                break
    return rows


def first(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def normalize_job(item: dict) -> dict:
    title = str(item.get("job_title") or "").strip()
    jd = str(item.get("jd_text") or "").strip()
    text = f"{title}\n{jd}"
    category, sub_category, evidence = classify(text, item)
    salary_min, salary_max, salary_unit = parse_salary(item)
    skills = normalize_skills([*(item.get("requirements") or []), *extract_skills(text)])
    risk_flags, risk_level, phrases = detect_risks(text)
    return {
        "id": stable_id("job", item.get("source_file", ""), item.get("source_row", ""), title, jd[:80]),
        "company_name": str(item.get("company_name") or "").strip(),
        "job_title": title,
        "job_category": item.get("job_category") or category,
        "sub_category": item.get("sub_category") or sub_category,
        "location": str(item.get("location") or "").strip(),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_unit": salary_unit,
        "degree_requirement": str(item.get("degree_requirement") or infer_degree(text)),
        "experience_requirement": infer_experience(text),
        "jd_text": jd,
        "required_skills": skills,
        "benefits": [str(x).strip() for x in item.get("benefits") or [] if str(x).strip()],
        "risk_flags": risk_flags,
        "risk_level": risk_level,
        "risk_evidence_phrases": phrases,
        "classification_evidence": evidence,
        "source_type": str(item.get("source_type") or "seed").strip(),
        "source_url": str(item.get("source_url") or "").strip(),
    }


def classify(text: str, item: dict | None = None) -> tuple[str, str, list[str]]:
    lowered = text.lower()
    for category, keywords in CATEGORY_RULES:
        hits = [kw for kw in keywords if kw.lower() in lowered]
        if hits:
            return "技术", category, hits[:5]
    raw_category = str((item or {}).get("job_category") or "").strip()
    raw_sub = str((item or {}).get("sub_category") or "").strip()
    return raw_category or "其他", raw_sub or "其他", []


def parse_salary(item: dict) -> tuple[int | None, int | None, str]:
    if item.get("salary_min") is not None or item.get("salary_max") is not None:
        return item.get("salary_min"), item.get("salary_max"), str(item.get("salary_unit") or "")
    text = str(item.get("salary_text") or "")
    numbers = [int(value) for value in re.findall(r"\d+", text)]
    if len(numbers) >= 2:
        return numbers[0], numbers[1], "元/月" if "月" in text else ""
    if len(numbers) == 1:
        return numbers[0], numbers[0], "元/月" if "月" in text else ""
    return None, None, ""


def infer_degree(text: str) -> str:
    for degree in ["博士", "硕士", "本科", "大专", "不限"]:
        if degree in text:
            return degree
    return ""


def infer_experience(text: str) -> str:
    match = re.search(r"(\d+)\s*年(?:以上)?", text)
    if match:
        return f"{match.group(1)}年以上"
    if "应届" in text:
        return "应届"
    if "不限经验" in text or "经验不限" in text:
        return "不限"
    return ""


def extract_skills(text: str) -> list[str]:
    lowered = text.lower()
    skills = []
    for alias, canonical in TECH_ALIASES.items():
        if alias in lowered:
            skills.append(canonical)
    return skills


def normalize_skills(values: list[Any]) -> list[str]:
    normalized = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        canonical = TECH_ALIASES.get(raw.lower(), raw)
        normalized.append(canonical)
    return list(dict.fromkeys(normalized))[:20]


def detect_risks(text: str) -> tuple[list[str], str, list[str]]:
    lowered = text.lower()
    flags = []
    phrases = []
    for label, keywords in RISK_RULES.items():
        hits = [kw for kw in keywords if kw.lower() in lowered]
        if hits:
            flags.append(label)
            phrases.extend(hits[:2])
    if any(flag in flags for flag in ["培训引流风险", "KPI/销售伪装"]):
        level = "high"
    elif len(flags) >= 2:
        level = "medium"
    else:
        level = "low"
    return flags, level, list(dict.fromkeys(phrases))[:8]


def make_messages(task: str, instruction: str, output: dict) -> dict:
    return {
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 JobGuard 求职决策系统中的结构化信息抽取模型。"
                    "请只输出合法 JSON，不要输出解释、Markdown 或无法核验的推断。"
                ),
            },
            {"role": "user", "content": instruction},
            {"role": "assistant", "content": json.dumps(output, ensure_ascii=False, separators=(",", ":"))},
        ],
        "task": task,
    }


def build_examples(job: dict) -> list[dict]:
    jd_context = "\n".join([
        f"公司：{job['company_name']}",
        f"岗位：{job['job_title']}",
        f"地点：{job['location']}",
        f"薪资：{job['salary_min']}-{job['salary_max']}{job['salary_unit']}",
        f"JD：{job['jd_text']}",
    ])
    extract_output = {
        "company_name": job["company_name"],
        "job_title": job["job_title"],
        "job_category": job["job_category"],
        "sub_category": job["sub_category"],
        "location": job["location"],
        "salary_min": job["salary_min"],
        "salary_max": job["salary_max"],
        "salary_unit": job["salary_unit"],
        "degree_requirement": job["degree_requirement"],
        "experience_requirement": job["experience_requirement"],
        "required_skills": job["required_skills"],
        "benefits": job["benefits"],
        "risk_flags": job["risk_flags"],
    }
    classify_output = {
        "job_category": job["job_category"],
        "sub_category": job["sub_category"],
        "confidence": 0.9 if job["classification_evidence"] else 0.6,
        "evidence_keywords": job["classification_evidence"],
    }
    risk_output = {
        "risk_level": job["risk_level"],
        "risk_flags": job["risk_flags"],
        "evidence_phrases": job["risk_evidence_phrases"],
        "unknown_fields": ["社保人数", "劳动仲裁数量", "工商异常"] if job["company_name"] else ["企业全称", "社保人数", "劳动仲裁数量", "工商异常"],
    }
    skill_output = {
        "normalized_skills": job["required_skills"],
        "skill_groups": group_skills(job["required_skills"]),
    }
    return [
        make_messages("jd_extract", f"请抽取以下 JD 的结构化字段：\n{jd_context}", extract_output),
        make_messages("job_classify", f"请判断岗位大类和细分方向，并给出证据关键词：\n{jd_context}", classify_output),
        make_messages("risk_label", f"请识别以下 JD 中的风险话术。不能根据常识编造企业社保、仲裁或口碑数据：\n{jd_context}", risk_output),
        make_messages("skill_normalize", f"请标准化以下 JD 中出现的技术技能词：\n{jd_context}", skill_output),
    ]


def group_skills(skills: list[str]) -> dict[str, list[str]]:
    groups = {"大模型与RAG": [], "后端工程": [], "前端工程": [], "数据与算法": [], "工程工具": []}
    for skill in skills:
        lowered = skill.lower()
        if skill in {"LLM", "Agent", "RAG", "LangGraph", "LoRA", "SFT", "DPO", "MCP"}:
            groups["大模型与RAG"].append(skill)
        elif skill in {"Java", "Python", "Spring", "Spring Boot", "FastAPI", "MySQL", "PostgreSQL", "Redis"}:
            groups["后端工程"].append(skill)
        elif skill in {"JavaScript", "TypeScript", "Vue", "React"} or lowered in {"html", "css"}:
            groups["前端工程"].append(skill)
        elif skill in {"PyTorch", "TensorFlow"}:
            groups["数据与算法"].append(skill)
        elif skill in {"Docker", "Kubernetes"}:
            groups["工程工具"].append(skill)
    return {key: value for key, value in groups.items() if value}


def split_jobs(jobs: list[dict]) -> dict[str, list[dict]]:
    rng = random.Random(RANDOM_SEED)
    shuffled = list(jobs)
    rng.shuffle(shuffled)
    n = len(shuffled)
    train_n = int(n * 0.7)
    val_n = int(n * 0.15)
    return {
        "train": shuffled[:train_n],
        "val": shuffled[train_n:train_n + val_n],
        "test": shuffled[train_n + val_n:],
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_dataset(out_dir: Path, max_jobs: int) -> dict:
    jobs_by_id = {}
    for job in [*load_seed_jobs(), *load_beijing_csv()]:
        if not job["job_title"] or not job["jd_text"]:
            continue
        key = (job["company_name"], job["job_title"], job["jd_text"][:120])
        jobs_by_id[key] = job
        if len(jobs_by_id) >= max_jobs:
            break
    jobs = list(jobs_by_id.values())
    splits = split_jobs(jobs)
    task_counts: dict[str, int] = {}
    split_counts: dict[str, int] = {}
    for split, split_jobs_ in splits.items():
        rows = []
        for job in split_jobs_:
            for example in build_examples(job):
                row = {
                    "id": stable_id("sftv3", split, job["id"], example["task"]),
                    "source_job_id": job["id"],
                    "label_quality": "gold_seed" if job["source_type"] != "beijing_hr_open_data" else "silver_rule",
                    "source_type": job["source_type"],
                    **example,
                }
                rows.append(row)
                task_counts[row["task"]] = task_counts.get(row["task"], 0) + 1
        write_jsonl(out_dir / f"{split}.jsonl", rows)
        split_counts[split] = len(rows)

    gold_candidates = [
        {
            "source_job_id": job["id"],
            "company_name": job["company_name"],
            "job_title": job["job_title"],
            "source_type": job["source_type"],
            "tasks": ["jd_extract", "job_classify", "risk_label", "skill_normalize"],
            "review_priority": review_priority(job),
            "jd_text": job["jd_text"][:3000],
        }
        for job in sorted(jobs, key=review_priority, reverse=True)[:100]
    ]
    write_jsonl(out_dir / "gold_review_candidates.jsonl", gold_candidates)
    manifest = {
        "name": "jobguard_sft_v3_multitask",
        "version": "0.3.0",
        "random_seed": RANDOM_SEED,
        "source_jobs": len(jobs),
        "examples": sum(split_counts.values()),
        "split_examples": split_counts,
        "task_counts": task_counts,
        "split_policy": "70/15/15 by deterministic shuffle",
        "tasks": ["jd_extract", "job_classify", "risk_label", "skill_normalize"],
        "label_quality": {
            "gold_seed": "人工种子岗位或项目内高质量种子数据",
            "silver_rule": "公开岗位 CSV 经规则归一化生成，需要后续人工复核",
        },
        "human_review": {
            "required": True,
            "file": "gold_review_candidates.jsonl",
            "recommendation": "优先复核 100 条高风险/大模型/边界岗位，升级为 gold label 后再训练正式模型。",
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def review_priority(job: dict) -> int:
    text = f"{job['job_title']} {job['jd_text']}".lower()
    score = 0
    score += 5 * len(job["risk_flags"])
    score += 8 if any(kw in text for kw in ["大模型", "llm", "agent", "rag", "智能体"]) else 0
    score += 3 if not job["required_skills"] else 0
    score += 2 if not job["salary_min"] else 0
    return score


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-jobs", type=int, default=500)
    args = parser.parse_args()
    manifest = build_dataset(args.out, args.max_jobs)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
