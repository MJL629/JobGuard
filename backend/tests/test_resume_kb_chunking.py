from app.rag.resume_kb import CHUNK_SIZE, ResumeKnowledgeBase


def test_resume_kb_splits_by_resume_sections():
    text = """
教育经历
广州大学 计算机科学与技术 本科

专业技能
Python、FastAPI、LangGraph、RAG、MySQL

项目经历
JobGuard 求职卫士：基于多 Agent 和 RAG 的岗位分析系统。

自我评价
关注大模型应用工程和 AI Infra。
""".strip()

    chunks = ResumeKnowledgeBase.split_resume_text(text)
    chunk_types = {chunk["chunk_type"] for chunk in chunks}

    assert {"education", "skills", "projects", "self_evaluation"} <= chunk_types
    assert all(chunk["content"].strip() for chunk in chunks)


def test_resume_kb_splits_long_project_section_with_overlap():
    text = "项目经历\n" + "JobGuard 项目负责 RAG 召回、Agent 编排、FastAPI 后端接口。" * 120

    chunks = ResumeKnowledgeBase.split_resume_text(text)
    project_chunks = [chunk for chunk in chunks if chunk["chunk_type"] == "projects"]

    assert len(project_chunks) > 1
    assert all(len(chunk["content"]) <= CHUNK_SIZE for chunk in project_chunks[:-1])
    assert [chunk["chunk_index"] for chunk in project_chunks] == list(range(len(project_chunks)))
