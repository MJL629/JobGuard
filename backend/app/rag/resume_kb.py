"""
简历范例知识库操作

存储内容：按岗位类型分类的优质简历范例、项目描述改写模式
"""

from app.llm.gateway import llm_gateway
from app.rag.vector_store import vector_store

COLLECTION_NAME = "resume_examples_kb"


class ResumeKnowledgeBase:
    """简历范例知识库"""

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
