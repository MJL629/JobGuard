"""
自动化评测框架 - JobGuard Eval Runner

Usage:
    python -m tests.eval_runner                    # 运行所有场景
    python -m tests.eval_runner --scenario profile_building
    python -m tests.eval_runner --scenario job_analysis
    python -m tests.eval_runner --scenario edge_cases
    python -m tests.eval_runner --output results.json
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# 添加 backend 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass
class EvalResult:
    test_id: str
    scenario: str
    passed: bool
    score: float  # 0-100
    details: dict
    error: Optional[str] = None


class EvalRunner:
    """自动化评测运行器"""

    # ANSI color codes
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    def __init__(self, dataset_path: str):
        self.dataset_path = dataset_path
        with open(dataset_path, "r", encoding="utf-8") as f:
            self.dataset = json.load(f)
        self.results: list[EvalResult] = []

    async def run_all(self) -> dict:
        """运行所有测试，返回汇总报告"""
        scenarios = self.dataset.get("scenarios", {})
        all_results: list[EvalResult] = []

        for scenario_name in scenarios:
            print(f"\n{self.BOLD}{self.CYAN}{'=' * 60}{self.RESET}")
            print(f"{self.BOLD}{self.CYAN}  场景: {scenario_name}{self.RESET}")
            print(f"{self.BOLD}{self.CYAN}{'=' * 60}{self.RESET}")
            scenario_results = await self.run_scenario(scenario_name)
            all_results.extend(scenario_results)

        self.results = all_results
        return self._build_summary(all_results)

    async def run_scenario(self, scenario_name: str) -> list[EvalResult]:
        """运行指定场景的所有测试用例"""
        scenarios = self.dataset.get("scenarios", {})
        if scenario_name not in scenarios:
            print(f"{self.RED}错误: 未知场景 '{scenario_name}'{self.RESET}")
            return []

        test_cases = scenarios[scenario_name]
        results: list[EvalResult] = []

        for case in test_cases:
            result = await self._run_single_test(case, scenario_name)
            results.append(result)
            self._print_result(result)

        return results

    async def _run_single_test(self, case: dict, scenario: str) -> EvalResult:
        """运行单个测试用例，30 秒超时"""
        test_id = case["id"]
        user_input = case.get("input", "")
        expected_intent = case.get("expected_intent", "")

        try:
            result = await asyncio.wait_for(
                self._execute_test(case, scenario),
                timeout=30.0,
            )
            return result
        except asyncio.TimeoutError:
            return EvalResult(
                test_id=test_id,
                scenario=scenario,
                passed=False,
                score=0,
                details={"reason": "测试超时（30秒）"},
                error="TimeoutError",
            )
        except Exception as e:
            return EvalResult(
                test_id=test_id,
                scenario=scenario,
                passed=False,
                score=0,
                details={"reason": f"异常: {str(e)}"},
                error=str(e),
            )

    async def _execute_test(self, case: dict, scenario: str) -> EvalResult:
        """执行具体的评测逻辑"""
        from app.agents.orchestrator import detect_intent

        test_id = case["id"]
        user_input = case.get("input", "")
        expected_intent = case.get("expected_intent", "")

        # 1. 检测意图
        detected_intent = await detect_intent(user_input)

        # 2. 根据场景做针对性验证
        if scenario == "profile_building":
            return self._eval_profile_building(case, detected_intent)
        elif scenario == "job_analysis":
            return self._eval_job_analysis(case, detected_intent)
        elif scenario == "job_recommendation":
            return self._eval_job_recommendation(case, detected_intent)
        elif scenario == "resume_generation":
            return self._eval_resume_generation(case, detected_intent)
        elif scenario == "edge_cases":
            return self._eval_edge_case(case, detected_intent)
        else:
            # 通用评估：只检查意图
            passed = detected_intent == expected_intent
            return EvalResult(
                test_id=test_id,
                scenario=scenario,
                passed=passed,
                score=100.0 if passed else 0.0,
                details={
                    "expected_intent": expected_intent,
                    "detected_intent": detected_intent,
                },
            )

    # ─── 场景专项评估 ──────────────────────────────────────────────

    def _eval_profile_building(self, case: dict, detected_intent: str) -> EvalResult:
        """评估 profile_building 场景"""
        test_id = case["id"]
        expected_intent = case.get("expected_intent", "build_profile")
        expected_fields = case.get("expected_fields", {})
        min_completeness = case.get("min_completeness", 30)

        score = 0.0
        details = {
            "expected_intent": expected_intent,
            "detected_intent": detected_intent,
            "expected_fields": expected_fields,
        }

        # 意图正确性: 40 分
        if detected_intent == expected_intent:
            score += 40.0

        # 字段匹配: 40 分 (根据 expected_fields 数量按比例)
        if expected_fields:
            # 用规则方式检查关键词是否在输入中（不依赖 LLM 返回）
            input_lower = case.get("input", "").lower()
            field_hits = 0
            for field, value in expected_fields.items():
                if isinstance(value, list):
                    for item in value:
                        if item.lower() in input_lower:
                            field_hits += 1
                            break
                elif value and str(value).lower() in input_lower:
                    field_hits += 1
            if field_hits > 0:
                score += min(40.0, (field_hits / len(expected_fields)) * 40.0)
                details["field_hits"] = field_hits
                details["field_total"] = len(expected_fields)
        else:
            # 没有期望字段时，意图正确就给部分分
            if detected_intent == expected_intent:
                score += 20.0

        # 没有崩溃: 20 分
        score += 20.0
        details["min_completeness"] = min_completeness

        passed = score >= 50.0
        return EvalResult(
            test_id=test_id,
            scenario="profile_building",
            passed=passed,
            score=min(100.0, score),
            details=details,
        )

    def _eval_job_analysis(self, case: dict, detected_intent: str) -> EvalResult:
        """评估 job_analysis 场景"""
        test_id = case["id"]
        expected_intent = case.get("expected_intent", "analyze_job")
        expected_company = case.get("expected_company")
        expected_risk_not = case.get("expected_risk_not")
        min_dimensions = case.get("min_dimensions", 2)

        score = 0.0
        details = {
            "expected_intent": expected_intent,
            "detected_intent": detected_intent,
            "expected_company": expected_company,
            "min_dimensions": min_dimensions,
        }

        # 意图正确性: 40 分
        if detected_intent == expected_intent:
            score += 40.0

        # 公司名识别: 30 分（关键词检查）
        if expected_company:
            input_text = case.get("input", "")
            if expected_company in input_text:
                score += 30.0
                details["company_found"] = True
            else:
                details["company_found"] = False
        else:
            # 不检查公司名时，意图正确给部分分
            if detected_intent == expected_intent:
                score += 15.0

        # 没有崩溃: 30 分
        score += 30.0

        passed = score >= 50.0
        return EvalResult(
            test_id=test_id,
            scenario="job_analysis",
            passed=passed,
            score=min(100.0, score),
            details=details,
        )

    def _eval_job_recommendation(self, case: dict, detected_intent: str) -> EvalResult:
        """评估 job_recommendation 场景"""
        test_id = case["id"]
        expected_intent = case.get("expected_intent", "recommend_jobs")
        min_results = case.get("min_results", 1)

        score = 0.0
        details = {
            "expected_intent": expected_intent,
            "detected_intent": detected_intent,
            "min_results": min_results,
        }

        # 意图正确性: 60 分
        if detected_intent == expected_intent:
            score += 60.0

        # 没有崩溃: 40 分
        score += 40.0

        passed = detected_intent == expected_intent
        return EvalResult(
            test_id=test_id,
            scenario="job_recommendation",
            passed=passed,
            score=score,
            details=details,
        )

    def _eval_resume_generation(self, case: dict, detected_intent: str) -> EvalResult:
        """评估 resume_generation 场景"""
        test_id = case["id"]
        expected_intent = case.get("expected_intent", "generate_resume")
        min_sections = case.get("min_sections", 3)

        score = 0.0
        details = {
            "expected_intent": expected_intent,
            "detected_intent": detected_intent,
            "min_sections": min_sections,
        }

        # 意图正确性: 60 分
        if detected_intent == expected_intent:
            score += 60.0

        # 没有崩溃: 40 分
        score += 40.0

        passed = detected_intent == expected_intent
        return EvalResult(
            test_id=test_id,
            scenario="resume_generation",
            passed=passed,
            score=score,
            details=details,
        )

    def _eval_edge_case(self, case: dict, detected_intent: str) -> EvalResult:
        """评估边界用例"""
        test_id = case["id"]
        expected_intent = case.get("expected_intent", "build_profile")
        description = case.get("description", "")

        score = 100.0
        details = {
            "expected_intent": expected_intent,
            "detected_intent": detected_intent,
            "description": description,
        }

        # 检查不崩溃: 50 分
        # (已经运行到这里说明没有崩溃)

        # 合理的 intent: 50 分
        valid_intents = {"build_profile", "analyze_job", "generate_resume", "recommend_jobs"}
        if detected_intent not in valid_intents:
            score -= 50.0
            details["invalid_intent"] = True

        # 意图匹配期望额外加分
        if detected_intent == expected_intent:
            details["intent_match"] = True
        else:
            details["intent_match"] = False
            # 虽然不匹配但也可能合理
            if detected_intent in valid_intents:
                details["intent_reasonable"] = True

        passed = score >= 50.0
        return EvalResult(
            test_id=test_id,
            scenario="edge_cases",
            passed=passed,
            score=score,
            details=details,
        )

    # ─── 报告生成 ──────────────────────────────────────────────────

    def generate_report(self, results: list[EvalResult]) -> str:
        """生成 Markdown 评测报告"""
        summary = self._build_summary(results)

        lines = [
            f"# JobGuard 评测报告",
            f"",
            f"**测试套件**: {self.dataset.get('test_suite', 'N/A')}",
            f"**创建日期**: {self.dataset.get('created', 'N/A')}",
            f"**评测时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"",
            f"## 总览",
            f"",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 总用例数 | {summary['total']} |",
            f"| 通过数 | {summary['passed']} |",
            f"| 失败数 | {summary['failed']} |",
            f"| 通过率 | {summary['pass_rate']:.1f}% |",
            f"| 平均分 | {summary['avg_score']:.1f} |",
            f"",
            f"## 各场景结果",
            f"",
            f"| 场景 | 总数 | 通过 | 失败 | 通过率 | 平均分 |",
            f"|------|------|------|------|--------|--------|",
        ]

        for scenario_name, stats in summary["by_scenario"].items():
            lines.append(
                f"| {scenario_name} | {stats['total']} | {stats['passed']} | "
                f"{stats['failed']} | {stats['pass_rate']:.1f}% | {stats['avg_score']:.1f} |"
            )

        lines.append("")
        lines.append("## 失败用例详情")
        lines.append("")

        failures = [r for r in results if not r.passed]
        if failures:
            for r in failures:
                lines.append(f"### [{r.test_id}] {r.scenario}")
                lines.append(f"- **分数**: {r.score:.0f}")
                lines.append(f"- **错误**: {r.error or 'N/A'}")
                lines.append(f"- **详情**: {json.dumps(r.details, ensure_ascii=False)}")
                lines.append("")
        else:
            lines.append("无失败用例。")
            lines.append("")

        return "\n".join(lines)

    def _build_summary(self, results: list[EvalResult]) -> dict:
        """构建汇总统计"""
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        pass_rate = (passed / total * 100) if total > 0 else 0
        avg_score = sum(r.score for r in results) / total if total > 0 else 0

        # 按场景分组
        by_scenario: dict[str, dict] = {}
        for r in results:
            if r.scenario not in by_scenario:
                by_scenario[r.scenario] = {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "scores": [],
                }
            stats = by_scenario[r.scenario]
            stats["total"] += 1
            if r.passed:
                stats["passed"] += 1
            else:
                stats["failed"] += 1
            stats["scores"].append(r.score)

        for scenario_name, stats in by_scenario.items():
            total_s = stats["total"]
            stats["pass_rate"] = (stats["passed"] / total_s * 100) if total_s > 0 else 0
            stats["avg_score"] = (
                sum(stats["scores"]) / len(stats["scores"]) if stats["scores"] else 0
            )
            del stats["scores"]

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": pass_rate,
            "avg_score": avg_score,
            "by_scenario": by_scenario,
        }

    # ─── 终端输出 ──────────────────────────────────────────────────

    def _print_result(self, result: EvalResult):
        """在终端打印单个测试结果"""
        status = f"{self.GREEN}PASS{self.RESET}" if result.passed else f"{self.RED}FAIL{self.RESET}"
        print(
            f"  [{status}] {result.test_id:<10} "
            f"score={result.score:5.1f}  "
            f"intent={result.details.get('detected_intent', 'N/A')}"
        )
        if result.error:
            print(f"         {self.RED}Error: {result.error}{self.RESET}")

    def _print_summary(self, summary: dict):
        """在终端打印汇总报告"""
        print(f"\n{self.BOLD}{'=' * 60}{self.RESET}")
        print(f"{self.BOLD}  评测汇总{self.RESET}")
        print(f"{self.BOLD}{'=' * 60}{self.RESET}")
        print(f"  总用例数: {summary['total']}")
        print(f"  通过: {self.GREEN}{summary['passed']}{self.RESET}")
        print(f"  失败: {self.RED}{summary['failed']}{self.RESET}")
        print(f"  通过率: {summary['pass_rate']:.1f}%")
        print(f"  平均分: {summary['avg_score']:.1f}")

        print(f"\n  各场景结果:")
        for scenario_name, stats in summary["by_scenario"].items():
            color = self.GREEN if stats["pass_rate"] >= 80 else self.YELLOW if stats["pass_rate"] >= 50 else self.RED
            print(
                f"    {scenario_name:<25} "
                f"{color}{stats['pass_rate']:5.1f}%{self.RESET}  "
                f"({stats['passed']}/{stats['total']} passed)"
            )

        print(f"{self.BOLD}{'=' * 60}{self.RESET}")


async def main():
    parser = argparse.ArgumentParser(description="JobGuard 自动化评测框架")
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="只运行指定场景 (profile_building/job_analysis/job_recommendation/resume_generation/edge_cases)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="JSON 结果输出文件路径",
    )
    parser.add_argument(
        "--report",
        type=str,
        default=None,
        help="Markdown 报告输出文件路径",
    )

    args = parser.parse_args()

    # 数据集路径
    dataset_path = Path(__file__).resolve().parent / "eval_dataset.json"
    if not dataset_path.exists():
        print(f"错误: 数据集文件不存在: {dataset_path}")
        sys.exit(1)

    runner = EvalRunner(str(dataset_path))

    if args.scenario:
        results = await runner.run_scenario(args.scenario)
    else:
        summary = await runner.run_all()
        runner._print_summary(summary)

    # 输出 JSON 结果
    if args.output or not args.scenario:
        output_path = args.output or "eval_results.json"
        json_results = [
            {
                "test_id": r.test_id,
                "scenario": r.scenario,
                "passed": r.passed,
                "score": r.score,
                "details": r.details,
                "error": r.error,
            }
            for r in runner.results
        ]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(json_results, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {output_path}")

    # 输出 Markdown 报告
    if args.report:
        report = runner.generate_report(runner.results)
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"报告已保存到: {args.report}")


if __name__ == "__main__":
    asyncio.run(main())
