"""Opt-in LangSmith bridge that exports metadata only, never raw user content."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)


class LangSmithAdapter:
    @property
    def enabled(self) -> bool:
        return bool(settings.langsmith_tracing and settings.langsmith_api_key)

    def export_completed_run(self, run) -> bool:
        """Export a single sanitized run summary when explicitly enabled."""
        if not self.enabled:
            return False
        try:
            from langsmith import Client

            client = Client(api_key=settings.langsmith_api_key)
            external_id = uuid.uuid4()
            client.create_run(
                name=f"JobGuard:{run.workflow}",
                run_type="chain",
                id=external_id,
                project_name=settings.langsmith_project,
                inputs={
                    "intent": run.intent,
                    "session_bound": run.session_id is not None,
                    "privacy": "metadata_only",
                },
                start_time=run.created_at,
                tags=["jobguard", "sanitized"],
            )
            client.update_run(
                external_id,
                end_time=run.completed_at or datetime.utcnow(),
                outputs={
                    "status": run.status,
                    "duration_ms": run.duration_ms,
                    "tool_calls_count": run.tool_calls_count,
                    "tool_success_count": run.tool_success_count,
                },
                error=run.error_type if run.status == "failed" else None,
            )
            return True
        except Exception:
            logger.exception("[LangSmith] 脱敏轨迹导出失败，本地轨迹不受影响")
            return False

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "project": settings.langsmith_project if self.enabled else None,
            "privacy_mode": "metadata_only",
            "local_tracing": "always_on",
        }


langsmith_adapter = LangSmithAdapter()
