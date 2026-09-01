"""Summarize JobGuard SFT v3 baseline evaluation reports.

Example:
    python backend/scripts/summarize_sft_v3_baselines.py \
      --run base_qwen=/root/autodl-tmp/jobguard_sft_v3_outputs/base_qwen/test_eval.json \
      --run sft_r16=/root/autodl-tmp/jobguard_sft_v3_outputs/full_r16/test_eval.json \
      --output-md backend/finetune/jobguard_sft_v3/results/baseline_comparison.md \
      --output-csv backend/finetune/jobguard_sft_v3/results/baseline_comparison.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


METRIC_COLUMNS = [
    ("samples", "样本数"),
    ("json_success", "JSON合法率"),
    ("required_field_success", "必填字段成功率"),
    ("field_accuracy", "字段准确率"),
    ("skill_f1", "技能F1"),
    ("risk_f1", "风险F1"),
    ("missing_predictions", "缺失预测数"),
]


def fmt(value: Any) -> str:
    if isinstance(value, float):
        if 0 <= value <= 1:
            return f"{value * 100:.2f}%"
        return f"{value:.4f}"
    return str(value)


def parse_run(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--run 格式应为 name=/path/to/eval.json")
    name, path = value.split("=", 1)
    name = name.strip()
    if not name:
        raise argparse.ArgumentTypeError("run name 不能为空")
    return name, Path(path)


def read_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if "overall" in report:
        overall = dict(report.get("overall") or {})
        overall["missing_predictions"] = report.get("missing_predictions", 0)
    else:
        overall = dict(report.get("test_eval") or {})
        overall["samples"] = overall.get("samples") or report.get("training", {}).get("test_examples")
        overall["missing_predictions"] = overall.get("missing_predictions", 0)
    return overall


def build_rows(runs: list[tuple[str, Path]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, path in runs:
        metrics = read_report(path)
        row = {"run": name, "path": str(path)}
        for key, _label in METRIC_COLUMNS:
            row[key] = metrics.get(key)
        rows.append(row)
    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["run", *[key for key, _label in METRIC_COLUMNS], "path"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_md(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = ["实验版本", *[label for _key, label in METRIC_COLUMNS]]
    lines = [
        "# JobGuard SFT v3 基线对比结果",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        cells = [row["run"], *[fmt(row.get(key)) for key, _label in METRIC_COLUMNS]]
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "说明：",
            "",
            "- JSON合法率和必填字段成功率用于衡量模型是否稳定遵循结构化输出约束。",
            "- 字段准确率用于衡量岗位名称、公司、城市、薪资、学历、分类等结构化字段是否与测试集标准答案一致。",
            "- 技能F1和风险F1使用集合重叠计算，适合评估技能列表、风险标签这类非单一字段。",
            "- 该表只汇总自动评估指标，不等同于人工偏好评测；人工金标复核可以作为后续升级。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize JobGuard SFT v3 baseline eval reports.")
    parser.add_argument("--run", action="append", type=parse_run, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args()

    rows = build_rows(args.run)
    write_md(rows, args.output_md)
    write_csv(rows, args.output_csv)
    print(f"Wrote markdown summary to {args.output_md}")
    print(f"Wrote csv summary to {args.output_csv}")


if __name__ == "__main__":
    main()
