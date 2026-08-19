from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SCENARIOS_PATH = ROOT / "benchmarks" / "scenarios" / "scenarios.json"


def load_scenarios() -> dict[str, Any]:
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def environment_payload(phase: str) -> dict[str, Any]:
    scenarios = load_scenarios()
    return {
        "phase": phase,
        "git_commit": git_output("rev-parse", "HEAD"),
        "git_commit_summary": git_output("log", "-1", "--oneline"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "benchmark_mode": "mock",
        "llm_provider": "benchmark_fake",
        "llm_model": "deterministic-sleep-fake",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "test_config": scenarios,
        "privacy": {
            "uses_real_resume": False,
            "reads_api_keys": False,
            "calls_external_llm": False,
        },
    }
