"""
批量背调脚本 — 对所有种子岗位运行 BackgroundCheckAgent

用法:
    cd backend
    python scripts/batch_background_check.py                    # 全部岗位
    python scripts/batch_background_check.py --limit 5          # 仅前5个
    python scripts/batch_background_check.py --risk-only        # 仅高风险岗位
    python scripts/batch_background_check.py --output report.json  # 指定输出文件

输出:
    data/batch_background_check_results.json  — 结构化结果
    data/batch_background_check_summary.md    — 汇总报告
"""

import asyncio
import json
import os
import sys
import time
import argparse
from datetime import datetime, timezone

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agents.background_check import background_check
from app.llm.gateway import llm_gateway

# ─── 配置 ───────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
JOB_FILES = [
    "seed_jobs.json",
    "seed_jobs_batch2.json",
    "seed_jobs_batch3.json",
    "seed_jobs_batch4.json",
]

# 测试用户画像（用于个性化评估）
TEST_USER = {
    "basic": {
        "full_name": "测试用户",
        "degree": "本科",
        "major": "计算机科学与技术",
        "expected_salary_min": 8000,
        "expected_salary_max": 15000,
    },
    "preferences": {
        "preferred_locations": ["广州", "深圳", "成都"],
        "weekend_preference": "双休",
        "overtime_tolerance": "偶尔加班",
        "labor_intensity": "中等",
    },
}

# 已知的高风险岗位（来自数据洞察报告）
HIGH_RISK_COMPANIES = [
    "成都探真科技有限公司",
    "深圳市杭灏科技有限公司",
    "源世界科技",
    "泰普思琳",
    "艾联科",
]


def load_all_jobs():
    """加载所有种子岗位"""
    all_jobs = []
    for fname in JOB_FILES:
        fpath = os.path.join(DATA_DIR, fname)
        if not os.path.exists(fpath):
            print(f"  ⚠️  文件不存在: {fpath}")
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            jobs = json.load(f)
            for job in jobs:
                job["_source_file"] = fname
            all_jobs.extend(jobs)
    return all_jobs


def is_high_risk(job: dict) -> bool:
    """判断是否为已知高风险岗位"""
    company = job.get("company_name", "")
    for name in HIGH_RISK_COMPANIES:
        if name in company:
            return True

    # 检查风险信号关键词
    jd = job.get("jd_text", "") or job.get("jd_raw_text", "") or job.get("job_description", "")
    risk_keywords = ["7天/周", "大小周", "单休", "996", "弹性工作制=无偿加班", "强制加班"]
    for kw in risk_keywords:
        if kw in jd:
            return True

    # 薪资范围过大（可能虚假）
    salary_min = job.get("salary_min", 0)
    salary_max = job.get("salary_max", 0)
    if salary_max > 0 and salary_min > 0:
        if salary_max / max(salary_min, 1) >= 3:
            return True

    return False


async def run_background_check(job: dict, index: int, total: int) -> dict:
    """对单个岗位运行背调"""
    company = job.get("company_name", "未知")
    title = job.get("job_title", "未知")
    source = job.get("_source_file", "?")

    print(f"  [{index}/{total}] {company} — {title} ({source})", end=" ", flush=True)

    try:
        start = time.time()

        # 构造 job_info
        job_info = {
            "company_name": company,
            "job_title": title,
            "salary_min": job.get("salary_min", 0),
            "salary_max": job.get("salary_max", 0),
            "location": job.get("location", "未知"),
            "job_category": job.get("job_category", ""),
            "sub_category": job.get("sub_category", ""),
            "jd_raw_text": job.get("jd_text", "") or job.get("jd_raw_text", "") or job.get("job_description", ""),
            "jd_text": job.get("jd_text", "") or job.get("jd_raw_text", "") or job.get("job_description", ""),
            "requirements": job.get("requirements", []),
            "benefits": job.get("benefits", []),
            "company_size": job.get("company_size", ""),
            "company_financing": job.get("company_financing", ""),
            "company_industry": job.get("company_industry", ""),
            "degree_requirement": job.get("degree_requirement", ""),
            "work_days": job.get("work_days", ""),
            "duration": job.get("duration", ""),
        }

        report = await background_check.investigate(
            job_info=job_info,
            user_profile=TEST_USER,
        )

        elapsed = time.time() - start

        risk_level = report.get("risk_level", "unknown")
        score = report.get("overall_score", "N/A")
        rec_index = report.get("recommendation_index", "N/A")

        # 风险图标
        risk_icon = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(risk_level, "⚪")

        print(f"→ {risk_icon} {risk_level} | 评分:{score} | 推荐:{rec_index}/5 | {elapsed:.1f}s")

        return {
            "company_name": company,
            "job_title": title,
            "location": job.get("location", ""),
            "source_file": source,
            "risk_level": risk_level,
            "recommendation_index": rec_index,
            "overall_score": score,
            "recommendation_text": report.get("recommendation_text", ""),
            "summary": report.get("summary", ""),
            "red_flags": report.get("red_flags", []),
            "positive_points": report.get("positive_points", []),
            "advice": report.get("advice", ""),
            "dimensions": report.get("dimensions", {}),
            "elapsed_seconds": round(elapsed, 1),
            "error": None,
        }

    except Exception as e:
        print(f"→ ❌ 失败: {e}")
        return {
            "company_name": company,
            "job_title": title,
            "location": job.get("location", ""),
            "source_file": source,
            "risk_level": "error",
            "recommendation_index": 0,
            "overall_score": 0,
            "recommendation_text": "",
            "summary": f"分析失败: {str(e)}",
            "red_flags": [],
            "positive_points": [],
            "advice": "",
            "dimensions": {},
            "elapsed_seconds": 0,
            "error": str(e),
        }


def generate_summary(results: list[dict], output_dir: str) -> str:
    """生成汇总报告"""
    total = len(results)
    succeeded = sum(1 for r in results if r.get("risk_level") != "error")
    failed = total - succeeded

    # 风险分布
    risk_dist = {}
    for r in results:
        level = r.get("risk_level", "unknown")
        risk_dist[level] = risk_dist.get(level, 0) + 1

    # 高风险岗位
    high_risk = [r for r in results if r.get("risk_level") in ("high", "critical")]
    # 推荐岗位
    recommended = [r for r in results if r.get("recommendation_index", 0) >= 4]
    # 不推荐
    not_recommended = [r for r in results if r.get("recommendation_index", 5) <= 2]

    # 平均评分
    scores = [r.get("overall_score", 0) for r in results if r.get("risk_level") != "error"]
    avg_score = sum(scores) / len(scores) if scores else 0

    lines = [
        "# JobGuard 批量背调分析报告",
        f"\n**生成时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**分析岗位数**: {total} | **成功**: {succeeded} | **失败**: {failed}",
        "",
        "## 📊 总览",
        "",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 总岗位数 | {total} |",
        f"| 成功分析 | {succeeded} |",
        f"| 失败 | {failed} |",
        f"| 平均安全评分 (0=最安全) | {avg_score:.1f} |",
        f"| 高风险岗位 | {risk_dist.get('high', 0) + risk_dist.get('critical', 0)} |",
        f"| 推荐投递 (>=4/5) | {len(recommended)} |",
        f"| 不推荐 (<=2/5) | {len(not_recommended)} |",
        "",
        "## 🎯 风险分布",
        "",
        "| 风险等级 | 数量 | 占比 |",
        "|----------|------|------|",
    ]

    for level in ["critical", "high", "medium", "low", "error"]:
        count = risk_dist.get(level, 0)
        pct = f"{count / total * 100:.1f}%" if total else "0%"
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "error": "❌"}.get(level, "⚪")
        lines.append(f"| {icon} {level} | {count} | {pct} |")

    lines += [
        "",
        "## 🔴 高风险岗位 (需警惕)",
        "",
    ]

    if high_risk:
        lines.append("| 公司 | 岗位 | 风险等级 | 评分 | 红旗信号 |")
        lines.append("|------|------|----------|------|----------|")
        for r in high_risk:
            flags = ", ".join(r.get("red_flags", [])[:3]) or "—"
            lines.append(
                f"| {r['company_name']} | {r['job_title']} | {r['risk_level']} | {r['overall_score']} | {flags} |"
            )
    else:
        lines.append("✅ 无高风险岗位")

    lines += [
        "",
        "## 🟢 推荐投递岗位",
        "",
    ]

    if recommended:
        lines.append("| 公司 | 岗位 | 推荐指数 | 亮点 |")
        lines.append("|------|------|----------|------|")
        for r in recommended[:20]:  # 最多显示 20 个
            highlights = ", ".join(r.get("positive_points", [])[:2]) or "—"
            lines.append(
                f"| {r['company_name']} | {r['job_title']} | {r['recommendation_index']}/5 | {highlights} |"
            )
    else:
        lines.append("⚠️ 无推荐投递岗位")

    lines += [
        "",
        "## ❌ 不推荐岗位",
        "",
    ]

    if not_recommended:
        lines.append("| 公司 | 岗位 | 推荐指数 | 原因 |")
        lines.append("|------|------|----------|------|")
        for r in not_recommended[:20]:
            reason = r.get("summary", "")[:50] or "—"
            lines.append(
                f"| {r['company_name']} | {r['job_title']} | {r['recommendation_index']}/5 | {reason} |"
            )
    else:
        lines.append("✅ 无不推荐岗位")

    lines += [
        "",
        "## 📋 全部岗位排名 (按安全评分排序)",
        "",
        "| # | 公司 | 岗位 | 风险 | 评分 | 推荐 |",
        "|--|------|------|------|------|------|",
    ]

    # 按 overall_score 排序（0=最安全）
    sorted_results = sorted(
        [r for r in results if r.get("risk_level") != "error"],
        key=lambda x: (x.get("overall_score", 99), -(x.get("recommendation_index", 0))),
    )

    for i, r in enumerate(sorted_results, 1):
        risk_icon = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(r.get("risk_level", ""), "⚪")
        lines.append(
            f"| {i} | {r['company_name'][:15]} | {r['job_title'][:20]} | {risk_icon} {r['risk_level']} | {r['overall_score']} | {r['recommendation_index']}/5 |"
        )

    report_text = "\n".join(lines)

    # 写入文件
    report_path = os.path.join(output_dir, "batch_background_check_summary.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    return report_text


async def main():
    parser = argparse.ArgumentParser(description="批量背调分析")
    parser.add_argument("--limit", type=int, default=0, help="限制分析数量（0=全部）")
    parser.add_argument("--risk-only", action="store_true", help="仅分析高风险岗位")
    parser.add_argument("--output", type=str, default="data/batch_background_check_results.json", help="结果输出路径")
    parser.add_argument("--delay", type=float, default=1.0, help="每次请求间隔（秒），避免 API 限流")
    args = parser.parse_args()

    # 加载岗位
    all_jobs = load_all_jobs()
    print(f"\n📦 加载了 {len(all_jobs)} 个岗位\n")

    # 过滤
    if args.risk_only:
        jobs = [j for j in all_jobs if is_high_risk(j)]
        print(f"🔍 筛选高风险岗位: {len(jobs)}/{len(all_jobs)}\n")
    else:
        jobs = all_jobs

    if args.limit > 0:
        jobs = jobs[: args.limit]
        print(f"🔢 限制分析数量: {len(jobs)}\n")

    # 运行背调
    results = []
    total = len(jobs)
    start_time = time.time()

    for i, job in enumerate(jobs, 1):
        result = await run_background_check(job, i, total)
        results.append(result)

        # 避免 API 限流
        if i < total and args.delay > 0:
            await asyncio.sleep(args.delay)

    elapsed_total = time.time() - start_time

    # 保存结果
    output_path = os.path.join(os.path.dirname(__file__), "..", args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_jobs": total,
                "total_elapsed_seconds": round(elapsed_total, 1),
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    # 生成汇总报告
    output_dir = os.path.dirname(output_path)
    summary = generate_summary(results, output_dir)

    # 控制台输出
    print("\n" + "=" * 60)
    print(summary)
    print(f"\n📁 完整结果: {output_path}")
    print(f"📁 汇总报告: {os.path.join(output_dir, 'batch_background_check_summary.md')}")
    print(f"⏱️  总耗时: {elapsed_total:.1f}s (平均 {elapsed_total/total:.1f}s/岗位)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
