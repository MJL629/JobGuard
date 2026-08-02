"""
企业/岗位知识库操作

存储内容：历史分析过的企业信息、岗位信息、风险评估结果
"""

from app.llm.gateway import llm_gateway
from app.rag.vector_store import vector_store

COLLECTION_NAME = "company_job_kb"


class CompanyKnowledgeBase:
    """企业/岗位知识库"""

    async def add_analysis(
        self,
        company_name: str,
        job_title: str,
        analysis_text: str,
        metadata: dict | None = None,
    ):
        """存储分析结果"""
        collection = vector_store.get_or_create_collection(COLLECTION_NAME)

        embeddings = await llm_gateway.embed([analysis_text])

        doc_id = f"{company_name}_{job_title}_{hash(analysis_text) % 100000}"
        collection.add(
            embeddings=embeddings,
            documents=[analysis_text],
            metadatas=[{
                "company_name": company_name,
                "job_title": job_title,
                **(metadata or {}),
            }],
            ids=[doc_id],
        )

    async def search(
        self,
        query: str,
        company_name: str | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """检索企业/岗位分析记录"""
        collection = vector_store.get_or_create_collection(COLLECTION_NAME)

        query_embedding = await llm_gateway.embed([query])

        where = None
        if company_name:
            where = {"company_name": company_name}

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
company_kb = CompanyKnowledgeBase()
