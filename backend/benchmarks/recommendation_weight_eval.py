"""Evaluate JobGuard recommendation fusion weights.

This benchmark is intentionally offline and deterministic: it does not call an
LLM, a database, or Chroma.  Each scenario contains a hand-written profile, a
small candidate set, and graded relevance labels.  The goal is to compare
different rule/keyword/semantic fusion weights before changing production
defaults.

Run:
    python backend/benchmarks/recommendation_weight_eval.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.job_service import DEFAULT_RECOMMENDATION_WEIGHTS, JobService  # noqa: E402


WEIGHT_GRID = [
    {"name": "rule_50_keyword_25_semantic_25", "rule": 0.50, "keyword": 0.25, "semantic": 0.25},
    {"name": "rule_60_keyword_20_semantic_20", "rule": 0.60, "keyword": 0.20, "semantic": 0.20},
    {"name": "rule_55_keyword_25_semantic_20", "rule": 0.55, "keyword": 0.25, "semantic": 0.20},
    {"name": "rule_45_keyword_30_semantic_25", "rule": 0.45, "keyword": 0.30, "semantic": 0.25},
    {"name": "rule_40_keyword_30_semantic_30", "rule": 0.40, "keyword": 0.30, "semantic": 0.30},
    {"name": "rule_35_keyword_30_semantic_35", "rule": 0.35, "keyword": 0.30, "semantic": 0.35},
]


SCENARIOS = [
    {
        "id": "mjl_agent_rag",
        "description": "马嘉玲：优先大模型 Agent/RAG，广州，低薪可接受但不接受高强度",
        "profile": {
            "basic": {
                "expected_salary_min": 4000,
                "current_city": "广州",
                "resume_raw_text": "JobGuard 求职卫士，大模型 Agent，RAG，LangGraph，FastAPI，AI Infra",
            },
            "preferences": {
                "preferred_job_types": ["大模型应用", "Agent应用研发"],
                "preferred_locations": ["广州", "深圳"],
                "overtime_tolerance": "不接受",
                "labor_intensity": "排斥高强度",
            },
            "skills": [
                {"skill_name": "Python"},
                {"skill_name": "FastAPI"},
                {"skill_name": "RAG"},
                {"skill_name": "LangGraph"},
                {"skill_name": "MySQL"},
            ],
            "projects": [
                {
                    "project_name": "JobGuard",
                    "description": "基于 LangGraph 的多 Agent 求职分析和 RAG 推荐系统",
                    "tech_stack": ["LangGraph", "RAG", "FastAPI", "MySQL"],
                }
            ],
        },
        "jobs": [
            {
                "id": 1,
                "job_title": "算法开发实习生（RAG与Agent方向）",
                "company_name": "广州文基智能科技有限公司",
                "job_category": "algorithm",
                "sub_category": "大模型应用",
                "location": "广州",
                "salary_min": 4000,
                "salary_max": 6000,
                "requirements": ["Python", "RAG", "LangGraph", "FastAPI"],
                "jd_text": "负责大模型应用、智能体、知识库和检索增强生成系统开发",
                "source_type": "local_seed",
                "label": 3,
            },
            {
                "id": 2,
                "job_title": "AI Infra 实习生",
                "company_name": "深圳模型服务科技有限公司",
                "job_category": "algorithm",
                "sub_category": "AI基础设施",
                "location": "深圳",
                "salary_min": 5000,
                "salary_max": 8000,
                "requirements": ["Python", "vLLM", "Docker", "RAG"],
                "jd_text": "参与 vLLM 推理服务、模型 Serving、KV Cache 和知识库系统优化",
                "source_type": "official",
                "label": 3,
            },
            {
                "id": 3,
                "job_title": "Java后端开发工程师",
                "company_name": "广州业务系统公司",
                "job_category": "engineering",
                "sub_category": "后端开发",
                "location": "广州",
                "salary_min": 8000,
                "salary_max": 12000,
                "requirements": ["Java", "Spring Boot", "MySQL"],
                "jd_text": "负责业务后台接口开发",
                "source_type": "local_seed",
                "label": 1,
            },
            {
                "id": 4,
                "job_title": "前端开发实习生",
                "company_name": "北京前端科技",
                "job_category": "engineering",
                "sub_category": "前端开发",
                "location": "北京",
                "salary_min": 3000,
                "salary_max": 5000,
                "requirements": ["Vue", "JavaScript"],
                "jd_text": "负责管理后台页面开发",
                "source_type": "hf",
                "label": 0,
            },
            {
                "id": 5,
                "job_title": "大模型算法实习生",
                "company_name": "北京算法研究院",
                "job_category": "algorithm",
                "sub_category": "大模型算法",
                "location": "北京",
                "salary_min": 8000,
                "salary_max": 12000,
                "requirements": ["PyTorch", "LoRA", "SFT", "DPO"],
                "jd_text": "负责大模型训练、SFT、DPO 和模型评估",
                "source_type": "official",
                "label": 2,
            },
        ],
    },
    {
        "id": "backend_java_guangzhou",
        "description": "Java 后端：广州/深圳，薪资 15K+，技能硬命中更重要",
        "profile": {
            "basic": {"expected_salary_min": 15000},
            "preferences": {
                "preferred_job_types": ["后端开发"],
                "preferred_locations": ["广州", "深圳"],
                "weekend_preference": "必须双休",
            },
            "skills": [
                {"skill_name": "Java"},
                {"skill_name": "Spring Boot"},
                {"skill_name": "MySQL"},
                {"skill_name": "Redis"},
            ],
            "projects": [
                {"project_name": "订单中心", "description": "Spring Boot 微服务", "tech_stack": ["Java", "Spring Boot", "MySQL"]}
            ],
        },
        "jobs": [
            {
                "id": 11,
                "job_title": "Java后端开发工程师",
                "company_name": "广州云服务公司",
                "job_category": "engineering",
                "sub_category": "后端开发",
                "location": "广州",
                "salary_min": 16000,
                "salary_max": 23000,
                "requirements": ["Java", "Spring Boot", "MySQL", "Redis"],
                "jd_text": "负责 Spring Cloud 后端接口和缓存系统开发",
                "source_type": "local_seed",
                "label": 3,
            },
            {
                "id": 12,
                "job_title": "Python后端工程师",
                "company_name": "深圳平台技术公司",
                "job_category": "engineering",
                "sub_category": "后端开发",
                "location": "深圳",
                "salary_min": 17000,
                "salary_max": 24000,
                "requirements": ["Python", "FastAPI", "MySQL"],
                "jd_text": "负责平台服务端 API 开发",
                "source_type": "official",
                "label": 2,
            },
            {
                "id": 13,
                "job_title": "Java后端开发",
                "company_name": "北京高强度业务公司",
                "job_category": "engineering",
                "sub_category": "后端开发",
                "location": "北京",
                "salary_min": 25000,
                "salary_max": 35000,
                "requirements": ["Java", "Spring Boot"],
                "jd_text": "业务增长快，大小周，长期加班，需要抗压能力",
                "source_type": "local_seed",
                "label": 0,
            },
            {
                "id": 14,
                "job_title": "视觉设计师",
                "company_name": "广州设计公司",
                "job_category": "design",
                "sub_category": "视觉设计",
                "location": "广州",
                "salary_min": 12000,
                "salary_max": 18000,
                "requirements": ["Figma", "Photoshop"],
                "jd_text": "负责视觉设计和品牌物料",
                "source_type": "local_seed",
                "label": 0,
            },
        ],
    },
    {
        "id": "front_end_semantic",
        "description": "前端用户：语义相近的 Web/Vue/React 岗位应靠前，但地点不能忽略",
        "profile": {
            "basic": {"expected_salary_min": 10000},
            "preferences": {
                "preferred_job_types": ["前端开发"],
                "preferred_locations": ["杭州"],
            },
            "skills": [
                {"skill_name": "Vue"},
                {"skill_name": "React"},
                {"skill_name": "TypeScript"},
                {"skill_name": "Vite"},
            ],
            "projects": [
                {"project_name": "数据看板", "description": "Vue3 + Vite 可视化平台", "tech_stack": ["Vue", "TypeScript", "Vite"]}
            ],
        },
        "jobs": [
            {
                "id": 21,
                "job_title": "Web前端开发工程师",
                "company_name": "杭州 SaaS 公司",
                "job_category": "engineering",
                "sub_category": "前端开发",
                "location": "杭州",
                "salary_min": 12000,
                "salary_max": 18000,
                "requirements": ["Vue", "TypeScript", "Vite"],
                "jd_text": "负责 Web 前端工程化和管理后台开发",
                "source_type": "official",
                "label": 3,
            },
            {
                "id": 22,
                "job_title": "React前端实习生",
                "company_name": "上海前端团队",
                "job_category": "engineering",
                "sub_category": "前端开发",
                "location": "上海",
                "salary_min": 10000,
                "salary_max": 15000,
                "requirements": ["React", "TypeScript"],
                "jd_text": "负责 Web 页面组件开发",
                "source_type": "official",
                "label": 2,
            },
            {
                "id": 23,
                "job_title": "后端开发工程师",
                "company_name": "杭州服务端公司",
                "job_category": "engineering",
                "sub_category": "后端开发",
                "location": "杭州",
                "salary_min": 12000,
                "salary_max": 20000,
                "requirements": ["Java", "MySQL"],
                "jd_text": "负责接口和数据库开发",
                "source_type": "local_seed",
                "label": 0,
            },
            {
                "id": 24,
                "job_title": "数据分析师",
                "company_name": "杭州数据公司",
                "job_category": "data",
                "sub_category": "数据分析",
                "location": "杭州",
                "salary_min": 10000,
                "salary_max": 16000,
                "requirements": ["SQL", "Tableau"],
                "jd_text": "负责指标分析和报表搭建",
                "source_type": "local_seed",
                "label": 0,
            },
        ],
    },
    {
        "id": "hard_constraint_vs_semantic",
        "description": "边界样例：语义很像但地点/强度冲突时，规则权重过低会误排",
        "profile": {
            "basic": {"expected_salary_min": 6000, "resume_raw_text": "RAG Agent LangGraph FastAPI 求职项目"},
            "preferences": {
                "preferred_job_types": ["Agent应用研发", "大模型应用"],
                "preferred_locations": ["广州"],
                "weekend_preference": "必须双休",
                "labor_intensity": "排斥高强度",
            },
            "skills": [
                {"skill_name": "Python"},
                {"skill_name": "RAG"},
                {"skill_name": "LangGraph"},
                {"skill_name": "FastAPI"},
            ],
            "projects": [
                {"project_name": "JobGuard", "description": "Agent RAG 岗位推荐", "tech_stack": ["RAG", "LangGraph", "FastAPI"]}
            ],
        },
        "jobs": [
            {
                "id": 31,
                "job_title": "大模型Agent开发实习生",
                "company_name": "北京高强度AI公司",
                "job_category": "algorithm",
                "sub_category": "大模型应用",
                "location": "北京",
                "salary_min": 10000,
                "salary_max": 15000,
                "requirements": ["Python", "RAG", "LangGraph", "FastAPI"],
                "jd_text": "负责智能体和知识库系统，业务高速增长，大小周，长期加班，需要强抗压",
                "source_type": "official",
                "label": 1,
            },
            {
                "id": 32,
                "job_title": "AI应用开发实习生",
                "company_name": "广州稳态智能科技",
                "job_category": "algorithm",
                "sub_category": "大模型应用",
                "location": "广州",
                "salary_min": 6000,
                "salary_max": 9000,
                "requirements": ["Python", "FastAPI", "RAG"],
                "jd_text": "参与大模型应用、知识库问答和 Agent 工具调用开发，双休，导师带教",
                "source_type": "local_seed",
                "label": 3,
            },
            {
                "id": 33,
                "job_title": "Python后端实习生",
                "company_name": "广州平台服务公司",
                "job_category": "engineering",
                "sub_category": "后端开发",
                "location": "广州",
                "salary_min": 6000,
                "salary_max": 8000,
                "requirements": ["Python", "FastAPI", "MySQL"],
                "jd_text": "负责后端接口开发，偶尔接触 AI 应用接口",
                "source_type": "local_seed",
                "label": 2,
            },
        ],
    },
    {
        "id": "keyword_trap",
        "description": "边界样例：技能关键词命中很多，但岗位方向明显不是目标方向",
        "profile": {
            "basic": {"expected_salary_min": 12000, "resume_raw_text": "Java Spring Boot MySQL Redis 后端微服务"},
            "preferences": {
                "preferred_job_types": ["后端开发"],
                "preferred_locations": ["深圳"],
            },
            "skills": [
                {"skill_name": "Java"},
                {"skill_name": "Spring Boot"},
                {"skill_name": "MySQL"},
                {"skill_name": "Redis"},
                {"skill_name": "Vue"},
            ],
            "projects": [
                {"project_name": "订单中心", "description": "Java 微服务订单系统", "tech_stack": ["Java", "Spring Boot", "MySQL", "Redis"]}
            ],
        },
        "jobs": [
            {
                "id": 41,
                "job_title": "Java后端开发工程师",
                "company_name": "深圳交易系统公司",
                "job_category": "engineering",
                "sub_category": "后端开发",
                "location": "深圳",
                "salary_min": 15000,
                "salary_max": 22000,
                "requirements": ["Java", "Spring Boot", "MySQL", "Redis"],
                "jd_text": "负责交易系统后端服务、缓存和数据库优化",
                "source_type": "official",
                "label": 3,
            },
            {
                "id": 42,
                "job_title": "低代码平台实施顾问",
                "company_name": "深圳企业服务公司",
                "job_category": "product_data_testing",
                "sub_category": "实施顾问",
                "location": "深圳",
                "salary_min": 12000,
                "salary_max": 18000,
                "requirements": ["Java", "MySQL", "Vue"],
                "jd_text": "负责客户实施、需求沟通、低代码页面配置，少量脚本开发",
                "source_type": "official",
                "label": 1,
            },
            {
                "id": 43,
                "job_title": "后端开发工程师",
                "company_name": "广州云计算公司",
                "job_category": "engineering",
                "sub_category": "后端开发",
                "location": "广州",
                "salary_min": 16000,
                "salary_max": 23000,
                "requirements": ["Java", "Spring Boot", "Redis"],
                "jd_text": "负责云平台后端服务开发",
                "source_type": "local_seed",
                "label": 2,
            },
        ],
    },
]


def dcg(labels: list[int]) -> float:
    return sum((2**rel - 1) / math.log2(index + 2) for index, rel in enumerate(labels))


def ndcg_at_k(labels: list[int], k: int) -> float:
    actual = dcg(labels[:k])
    ideal = dcg(sorted(labels, reverse=True)[:k])
    return 0.0 if ideal == 0 else actual / ideal


def reciprocal_rank(labels: list[int]) -> float:
    for index, rel in enumerate(labels, start=1):
        if rel >= 2:
            return 1.0 / index
    return 0.0


def evaluate_weights(weights: dict[str, float]) -> dict:
    scenario_reports = []
    score_gaps = []
    for scenario in SCENARIOS:
        ranked = []
        for job in scenario["jobs"]:
            scored = JobService._score_job(scenario["profile"], job, weights=weights)
            ranked.append({
                "id": job["id"],
                "title": job["job_title"],
                "label": job["label"],
                "match_score": scored["match_score"] if scored["match_score"] is not None else -1,
                "breakdown": {
                    "rule": scored["score_breakdown"]["rule_recall"]["score"],
                    "keyword": scored["score_breakdown"]["keyword_recall"]["score"],
                    "semantic": scored["score_breakdown"]["semantic_recall"]["score"],
                },
            })
        ranked.sort(key=lambda item: item["match_score"], reverse=True)
        labels = [item["label"] for item in ranked]
        best_label = max(labels) if labels else 0
        best_scores = [item["match_score"] for item in ranked if item["label"] == best_label]
        distractor_scores = [item["match_score"] for item in ranked if item["label"] < best_label]
        score_gap = (max(best_scores) - max(distractor_scores)) if best_scores and distractor_scores else 0
        score_gaps.append(score_gap)
        scenario_reports.append({
            "id": scenario["id"],
            "description": scenario["description"],
            "ndcg_at_3": round(ndcg_at_k(labels, 3), 4),
            "mrr": round(reciprocal_rank(labels), 4),
            "top1_relevance": labels[0] if labels else 0,
            "best_vs_distractor_score_gap": round(score_gap, 2),
            "ranking": ranked,
        })

    return {
        "weights": {k: weights[k] for k in ("rule", "keyword", "semantic")},
        "avg_ndcg_at_3": round(mean(item["ndcg_at_3"] for item in scenario_reports), 4),
        "avg_mrr": round(mean(item["mrr"] for item in scenario_reports), 4),
        "top1_hit_rate": round(mean(1 if item["top1_relevance"] >= 2 else 0 for item in scenario_reports), 4),
        "avg_best_vs_distractor_gap": round(mean(score_gaps), 2),
        "scenarios": scenario_reports,
    }


def main() -> None:
    reports = [evaluate_weights(weights) for weights in WEIGHT_GRID]
    reports.sort(
        key=lambda item: (
            item["avg_ndcg_at_3"],
            item["avg_mrr"],
            item["top1_hit_rate"],
            item["avg_best_vs_distractor_gap"],
        ),
        reverse=True,
    )

    output = {
        "benchmark": "jobguard_recommendation_weight_eval",
        "default_weights": DEFAULT_RECOMMENDATION_WEIGHTS,
        "metric_note": {
            "label": "0=不推荐，1=弱相关，2=可考虑，3=强推荐",
            "ndcg_at_3": "衡量前三名排序质量，越接近 1 越好",
            "mrr": "第一个可考虑/强推荐岗位越靠前，分数越高",
            "top1_hit_rate": "第一名是否至少达到可考虑",
        },
        "best": reports[0],
        "all_results": reports,
    }

    out_path = ROOT / "benchmarks" / "recommendation_weight_eval_report.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Recommendation weight evaluation")
    print("================================")
    for report in reports:
        weights = report["weights"]
        print(
            f"{weights['rule']:.2f}/{weights['keyword']:.2f}/{weights['semantic']:.2f} "
            f"NDCG@3={report['avg_ndcg_at_3']:.4f} "
            f"MRR={report['avg_mrr']:.4f} "
            f"Top1={report['top1_hit_rate']:.4f} "
            f"Gap={report['avg_best_vs_distractor_gap']:.2f}"
        )
    print(f"\nBest: {reports[0]['weights']}")
    print(f"Report written to: {out_path}")


if __name__ == "__main__":
    main()
