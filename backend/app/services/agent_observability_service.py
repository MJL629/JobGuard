"""Database-backed Agent run tracing with privacy-preserving summaries."""

from __future__ import annotations

import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.agent_run import AgentEvaluation, AgentRun, ToolCallTrace


SENSITIVE_KEYS = {
    "password", "password_hash", "api_key", "apikey", "authorization",
    "cookie", "userkey", "user_key", "token", "access_token", "refresh_token",
    "resume_raw_text", "extracted_text",
}


class AgentObservabilityService:
    @staticmethod
    def redact(value: Any, depth: int = 0) -> Any:
        if depth > 4:
            return "[depth-limited]"
        if isinstance(value, dict):
            return {
                str(key): (
                    "[redacted]" if str(key).lower() in SENSITIVE_KEYS
                    else AgentObservabilityService.redact(item, depth + 1)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [AgentObservabilityService.redact(item, depth + 1) for item in value[:20]]
        if isinstance(value, str):
            text = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[redacted]", value)
            return text[:500]
        return value

    def start_run(
        self,
        db: Session,
        *,
        user_id: int | None,
        session_id: int | None,
        workflow: str,
        intent: str | None = None,
        input_summary: str | None = None,
        context_snapshot: dict | None = None,
    ) -> AgentRun:
        run = AgentRun(
            id=str(uuid.uuid4()),
            user_id=user_id,
            session_id=session_id,
            workflow=workflow,
            intent=intent,
            status="running",
            current_step="started",
            input_summary=self.redact(input_summary or ""),
            context_snapshot=self.redact(context_snapshot or {}),
            cost_status="provider_usage_unavailable",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    @staticmethod
    def update_step(db: Session, run: AgentRun, step: str, *, intent: str | None = None) -> None:
        run.current_step = step
        if intent:
            run.intent = intent
        run.updated_at = datetime.utcnow()
        db.commit()

    def complete_run(self, db: Session, run: AgentRun, output_summary: str = "") -> None:
        now = datetime.utcnow()
        run.status = "completed"
        run.current_step = "completed"
        run.output_summary = self.redact(output_summary)
        run.completed_at = now
        run.updated_at = now
        run.duration_ms = int((now - run.created_at).total_seconds() * 1000)
        db.add(AgentEvaluation(
            id=str(uuid.uuid4()),
            run_id=run.id,
            evaluator="deterministic_workflow_gate",
            metric_name="workflow_completed",
            score=1.0,
            passed=True,
            details={"scope": "流程完成性；不代表内容事实准确率"},
            created_at=now,
        ))
        db.commit()
        self._export_to_langsmith_async(run)

    def fail_run(self, db: Session, run: AgentRun, step: str, exc: Exception) -> None:
        now = datetime.utcnow()
        run.status = "failed"
        run.current_step = "failed"
        run.failure_step = step[:100]
        run.error_type = type(exc).__name__[:100]
        run.completed_at = now
        run.updated_at = now
        run.duration_ms = int((now - run.created_at).total_seconds() * 1000)
        db.add(AgentEvaluation(
            id=str(uuid.uuid4()),
            run_id=run.id,
            evaluator="deterministic_workflow_gate",
            metric_name="workflow_completed",
            score=0.0,
            passed=False,
            details={"failure_step": step[:100], "error_type": type(exc).__name__},
            created_at=now,
        ))
        db.commit()
        self._export_to_langsmith_async(run)

    def record_tool_call(
        self,
        db: Session,
        *,
        run: AgentRun,
        tool_name: str,
        arguments: dict,
        result: Any,
        started_at: float,
        requires_confirmation: bool,
        confirmed: bool,
        error: Exception | None = None,
    ) -> ToolCallTrace:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        status = "failed" if error else str((result or {}).get("status", "success") if isinstance(result, dict) else "success")
        sources = (result or {}).get("sources", []) if isinstance(result, dict) else []
        trace = ToolCallTrace(
            id=str(uuid.uuid4()),
            run_id=run.id,
            tool_name=tool_name,
            status=status[:30],
            arguments_redacted=self.redact(arguments),
            result_summary=self.redact(self._summarize_result(result)),
            source_count=len(sources),
            duration_ms=duration_ms,
            error_type=type(error).__name__ if error else None,
            requires_confirmation=requires_confirmation,
            confirmed_by_user=confirmed,
            created_at=datetime.utcnow(),
        )
        run.tool_calls_count = int(run.tool_calls_count or 0) + 1
        if not error and status not in {"failed", "error"}:
            run.tool_success_count = int(run.tool_success_count or 0) + 1
        db.add(trace)
        db.commit()
        db.refresh(trace)
        return trace

    @staticmethod
    def _summarize_result(result: Any) -> dict:
        if not isinstance(result, dict):
            return {"type": type(result).__name__}
        allowed = {
            "tool_name", "status", "count", "verification_status",
            "verified_dimensions", "missing_dimensions", "profile_completeness",
            "scoring_version", "resume_id", "template_id", "version",
            "docx_ready", "pdf_ready", "message", "notice", "policy",
        }
        summary = {key: result[key] for key in allowed if key in result}
        if "items" in result:
            summary["item_count"] = len(result.get("items") or [])
        if "steps" in result:
            summary["step_count"] = len(result.get("steps") or [])
        return summary

    @staticmethod
    def _export_to_langsmith_async(run: AgentRun) -> None:
        """Do not add external tracing latency to the user's request."""
        from app.services.langsmith_adapter import langsmith_adapter

        if not langsmith_adapter.enabled:
            return
        threading.Thread(
            target=langsmith_adapter.export_completed_run,
            args=(run,),
            name="jobguard-langsmith-export",
            daemon=True,
        ).start()

    @staticmethod
    def list_runs(db: Session, user_id: int, limit: int = 50) -> list[dict]:
        runs = (
            db.query(AgentRun)
            .filter(AgentRun.user_id == user_id)
            .order_by(AgentRun.created_at.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        return [AgentObservabilityService.run_to_dict(db, run) for run in runs]

    @staticmethod
    def run_to_dict(db: Session, run: AgentRun) -> dict:
        traces = db.query(ToolCallTrace).filter(ToolCallTrace.run_id == run.id).all()
        evaluations = db.query(AgentEvaluation).filter(AgentEvaluation.run_id == run.id).all()
        return {
            "id": run.id,
            "workflow": run.workflow,
            "intent": run.intent,
            "status": run.status,
            "current_step": run.current_step,
            "duration_ms": run.duration_ms,
            "tool_calls_count": run.tool_calls_count,
            "tool_success_count": run.tool_success_count,
            "failure_step": run.failure_step,
            "error_type": run.error_type,
            "model_provider": run.model_provider,
            "model_name": run.model_name,
            "prompt_tokens": run.prompt_tokens,
            "completion_tokens": run.completion_tokens,
            "estimated_cost_usd": run.estimated_cost_usd,
            "cost_status": run.cost_status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "tool_traces": [
                {
                    "id": item.id,
                    "tool_name": item.tool_name,
                    "status": item.status,
                    "duration_ms": item.duration_ms,
                    "source_count": item.source_count,
                    "requires_confirmation": item.requires_confirmation,
                    "confirmed_by_user": item.confirmed_by_user,
                    "error_type": item.error_type,
                }
                for item in traces
            ],
            "evaluations": [
                {
                    "evaluator": item.evaluator,
                    "metric_name": item.metric_name,
                    "score": item.score,
                    "passed": item.passed,
                    "details": item.details,
                }
                for item in evaluations
            ],
        }

    @staticmethod
    def metrics(db: Session, user_id: int, days: int = 30) -> dict:
        since = datetime.utcnow() - timedelta(days=max(1, min(days, 365)))
        runs = db.query(AgentRun).filter(AgentRun.user_id == user_id, AgentRun.created_at >= since)
        total = runs.count()
        completed = runs.filter(AgentRun.status == "completed").count()
        failed = runs.filter(AgentRun.status == "failed").count()
        aggregates = runs.with_entities(
            func.avg(AgentRun.duration_ms),
            func.sum(AgentRun.tool_calls_count),
            func.sum(AgentRun.tool_success_count),
        ).first()
        tool_total = int((aggregates[1] or 0) if aggregates else 0)
        tool_success = int((aggregates[2] or 0) if aggregates else 0)
        return {
            "window_days": days,
            "runs_total": total,
            "runs_completed": completed,
            "runs_failed": failed,
            "workflow_success_rate": round(completed / total, 4) if total else None,
            "average_duration_ms": round(float(aggregates[0]), 2) if aggregates and aggregates[0] is not None else None,
            "tool_calls_total": tool_total,
            "tool_success_rate": round(tool_success / tool_total, 4) if tool_total else None,
            "cost_status": "provider_usage_unavailable",
            "accuracy_status": "仅记录确定性流程门禁；内容准确率需离线数据集或人工标注",
        }


agent_observability_service = AgentObservabilityService()
