"""
简历范例知识库操作

存储内容：按岗位类型分类的优质简历范例、项目描述改写模式
"""

import re

from app.llm.gateway import llm_gateway
from app.rag.vector_store import vector_store

COLLECTION_NAME = "resume_examples_kb"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
MIN_SPLIT_SIZE = 800


class ResumeKnowledgeBase:
    """简历范例知识库"""

    @staticmethod
    def split_resume_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
        """按简历模块优先切块，长模块再滑窗。

        识别教育经历、技能、项目经历、实习经历、自我评价等常见标题。
        返回 [{"chunk_type": str, "chunk_index": int, "content": str}, ...]。
        """
        normalized = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
        if not normalized:
            return []

        heading_patterns = {
            "education": r"(教育经历|教育背景|学历背景)",
            "skills": r"(专业技能|技能清单|技术栈|技能)",
            "projects": r"(项目经历|项目经验|个人项目)",
            "internships": r"(实习经历|工作经历|实践经历)",
            "self_evaluation": r"(自我评价|个人总结|个人优势)",
        }
        combined = "|".join(f"(?P<{name}>{pattern})" for name, pattern in heading_patterns.items())
        matches = list(re.finditer(combined, normalized, flags=re.IGNORECASE))
        sections: list[tuple[str, str]] = []
        if not matches:
            sections = [("resume_text", normalized)]
        else:
            if matches[0].start() > 0:
                sections.append(("resume_summary", normalized[:matches[0].start()].strip()))
            for index, match in enumerate(matches):
                chunk_type = next((name for name, value in match.groupdict().items() if value), "resume_text")
                end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
                sections.append((chunk_type, normalized[match.start():end].strip()))

        chunks: list[dict] = []
        for chunk_type, section_text in sections:
            if not section_text:
                continue
            for chunk_index, content in enumerate(ResumeKnowledgeBase._split_long_text(section_text, chunk_size, overlap)):
                chunks.append({
                    "chunk_type": chunk_type,
                    "chunk_index": chunk_index,
                    "content": content,
                })
        return chunks

    @staticmethod
    def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
        if len(text) <= MIN_SPLIT_SIZE:
            return [text]
        chunks: list[str] = []
        start = 0
        while start < len(text):
            hard_end = min(len(text), start + chunk_size)
            end = hard_end
            if hard_end < len(text):
                window = text[start:hard_end]
                best = max(window.rfind(mark) for mark in ("\n", "。", "；", ";", "."))
                if best >= chunk_size * 0.6:
                    end = start + best + 1
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(0, end - overlap)
        return chunks

    async def add_example(
        self,
        job_category: str,
        project_type: str,
        example_text: str,
        metadata: dict | None = None,
    ):
        """添加简历范例"""
        collection = vector_store.get_or_create_collection(COLLECTION_NAME)

        embeddings = await llm_gateway.embed([example_text])

        doc_id = f"{job_category}_{project_type}_{hash(example_text) % 100000}"
        collection.add(
            embeddings=embeddings,
            documents=[example_text],
            metadatas=[{
                "job_category": job_category,
                "project_type": project_type,
                **(metadata or {}),
            }],
            ids=[doc_id],
        )

    async def search(
        self,
        query: str,
        job_category: str | None = None,
        top_k: int = 3,
    ) -> list[dict]:
        """检索简历范例"""
        collection = vector_store.get_or_create_collection(COLLECTION_NAME)

        query_embedding = await llm_gateway.embed([query])

        where = None
        if job_category:
            where = {"job_category": job_category}

        results = collection.query(
            query_embeddings=query_embedding,
            n_results=top_k,
            where=where,
        )

        formatted = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                formatted.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                })

        return formatted


# 全局单例
resume_kb = ResumeKnowledgeBase()
