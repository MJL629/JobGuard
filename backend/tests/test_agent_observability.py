from app.services.agent_observability_service import agent_observability_service


def test_trace_redaction_removes_credentials_and_raw_resume():
    redacted = agent_observability_service.redact({
        "api_key": "top-secret",
        "cookie": "session=private",
        "resume_raw_text": "private resume",
        "nested": {"authorization": "Bearer abc.def"},
        "safe": "岗位分析",
    })

    assert redacted["api_key"] == "[redacted]"
    assert redacted["cookie"] == "[redacted]"
    assert redacted["resume_raw_text"] == "[redacted]"
    assert redacted["nested"]["authorization"] == "[redacted]"
    assert redacted["safe"] == "岗位分析"


def test_result_summary_does_not_store_full_items_or_evidence():
    summary = agent_observability_service._summarize_result({
        "tool_name": "search_job_database",
        "status": "success",
        "items": [{"jd_text": "very long"}],
        "evidence": [{"content": "private"}],
    })

    assert summary == {
        "tool_name": "search_job_database",
        "status": "success",
        "item_count": 1,
    }
