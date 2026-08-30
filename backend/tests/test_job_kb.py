from app.rag.job_kb import CHUNK_SIZE, JobKnowledgeBase


def test_job_kb_builds_search_document_and_metadata():
    job = {
        "id": 141,
        "job_title": "算法开发实习生（RAG与Agent方向）",
        "company_name": "广州文基智能科技有限公司",
        "job_category": "algorithm",
        "sub_category": "大模型应用",
        "location": "广州",
        "salary_min": 4000,
        "salary_max": 6000,
        "requirements": ["Python", "RAG", "LangGraph"],
        "benefits": ["双休", "导师带教"],
        "jd_text": "负责智能体和知识库系统开发",
        "source_type": "local_seed",
    }

    document = JobKnowledgeBase.build_document(job)
    metadata = JobKnowledgeBase.build_metadata(job, chunk_type="summary", chunk_index=0)
    chunks = JobKnowledgeBase.build_chunks(job)

    assert "岗位名称：算法开发实习生" in document
    assert "岗位要求：Python；RAG；LangGraph" in document
    assert "岗位描述：负责智能体和知识库系统开发" in document
    assert metadata == {
        "type": "job",
        "job_id": "141",
        "company_name": "广州文基智能科技有限公司",
        "job_title": "算法开发实习生（RAG与Agent方向）",
        "job_category": "algorithm",
        "sub_category": "大模型应用",
        "location": "广州",
        "source_type": "local_seed",
        "chunk_type": "summary",
        "chunk_index": 0,
    }
    assert {chunk["metadata"]["chunk_type"] for chunk in chunks} >= {"summary", "requirements", "benefits", "jd_description"}
    assert all(chunk["metadata"]["job_id"] == "141" for chunk in chunks)


def test_job_kb_splits_long_jd_by_heading_then_window():
    long_requirements = "任职要求：" + "熟悉大模型、RAG、Agent、LangGraph、FastAPI。" * 90
    job = {
        "id": 142,
        "job_title": "大模型应用工程师",
        "company_name": "示例公司",
        "job_category": "algorithm",
        "sub_category": "大模型应用",
        "location": "广州",
        "requirements": ["Python", "RAG"],
        "jd_text": f"岗位职责：负责智能体系统开发。\n{long_requirements}",
        "source_type": "local_seed",
    }

    chunks = JobKnowledgeBase.build_chunks(job)
    requirement_chunks = [
        chunk for chunk in chunks
        if chunk["metadata"]["chunk_type"] == "requirements_detail"
    ]

    assert len(requirement_chunks) > 1
    assert all(len(chunk["content"]) <= CHUNK_SIZE for chunk in requirement_chunks[:-1])
    assert [chunk["metadata"]["chunk_index"] for chunk in requirement_chunks] == list(range(len(requirement_chunks)))
