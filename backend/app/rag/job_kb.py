"""岗位向量知识库。

存储内容：岗位标题、公司、地点、薪资、JD 原文、岗位要求、来源信息。

设计目的：
- 岗位推荐：用用户画像/项目经历作为 query，从岗位库召回语义相关岗位。
- 岗位分析：按 job_id 或相似 JD 检索历史相关岗位，辅助风险判断。
- 定向简历：用目标岗位 JD 反向召回用户项目时，可复用统一的岗位文本格式。
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.llm.gateway import llm_gateway
from app.rag.vector_store import vector_store

logger = logging.getLogger(__name__)

COLLECTION_NAME = "job_kb"


class JobKnowledgeBase:
    """岗位向量知识库封装。"""

    @staticmethod
    def build_document(job: dict) -> str:
        """将结构化岗位压成适合 embedding 的检索文本。"""
        requirements = job.get("requirements") or []
        benefits = job.get("benefits") or []
        return "\n".join([
            f"岗位名称：{job.get('job_title') or ''}",
            f"公司名称：{job.get('company_name') or ''}",
            f"岗位大类：{job.get('job_category') or ''}",
            f"细分方向：{job.get('sub_category') or ''}",
            f"工作地点：{job.get('location') or ''}",
            f"薪资范围：{job.get('salary_min') or ''}-{job.get('salary_max') or ''}",
            f"岗位要求：{'；'.join(str(item) for item in requirements)}",
            f"福利待遇：{'；'.join(str(item) for item in benefits)}",
            f"岗位描述：{job.get('jd_text') or ''}",
            f"来源类型：{job.get('source_type') or ''}",
        ]).strip()

    @staticmethod
    def build_metadata(job: dict) -> dict:
        """保留业务过滤所需 metadata。"""
        return {
            "type": "job",
            "job_id": str(job.get("id") or ""),
            "company_name": str(job.get("company_name") or ""),
            "job_title": str(job.get("job_title") or ""),
            "job_category": str(job.get("job_category") or ""),
            "sub_category": str(job.get("sub_category") or ""),
            "location": str(job.get("location") or ""),
            "source_type": str(job.get("source_type") or ""),
        }

    async def upsert_jobs(self, jobs: Iterable[dict]) -> int:
        """批量写入/更新岗位向量。

        Chroma 的 upsert 允许同一个 job_id 重复同步，适合定时刷新岗位库。
        """
        normalized_jobs = [job for job in jobs if job.get("id")]
        if not normalized_jobs:
            return 0

        documents = [self.build_document(job) for job in normalized_jobs]
        metadatas = [self.build_metadata(job) for job in normalized_jobs]
        ids = [f"job_{job['id']}" for job in normalized_jobs]

        embeddings = await llm_gateway.embed(documents)
        collection = vector_store.get_or_create_collection(COLLECTION_NAME)
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        logger.info("[JobKB] upserted %s jobs", len(ids))
        return len(ids)

    async def search(
        self,
        query: str,
        top_k: int = 20,
        filter_metadata: dict | None = None,
    ) -> list[dict]:
        """按语义检索岗位，返回 job_id 和相似度分数。"""
        if not query.strip():
            return []

        query_embedding = await llm_gateway.embed([query])
        collection = vector_store.get_or_create_collection(COLLECTION_NAME)
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=top_k,
            where=filter_metadata,
        )

        formatted: list[dict] = []
        documents = results.get("documents") or []
        if documents and documents[0]:
            for index, content in enumerate(documents[0]):
                metadata = (results.get("metadatas") or [[{}]])[0][index] or {}
                distance = (results.get("distances") or [[None]])[0][index]
                similarity = None if distance is None else 1.0 / (1.0 + float(distance))
                formatted.append({
                    "content": content,
                    "metadata": metadata,
                    "job_id": int(metadata["job_id"]) if str(metadata.get("job_id") or "").isdigit() else None,
                    "distance": distance,
                    "similarity": round(similarity, 6) if similarity is not None else None,
                })
        return formatted

    def clear(self) -> None:
        """清空岗位向量库。"""
        vector_store.delete_collection(COLLECTION_NAME)


job_kb = JobKnowledgeBase()
