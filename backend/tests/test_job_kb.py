from app.rag.job_kb import JobKnowledgeBase


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
    metadata = JobKnowledgeBase.build_metadata(job)

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
    }
