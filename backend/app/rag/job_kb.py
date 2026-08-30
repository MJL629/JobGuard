"""岗位向量知识库。

存储内容：岗位标题、公司、地点、薪资、JD 原文、岗位要求、来源信息。

设计目的：
- 岗位推荐：用用户画像/项目经历作为 query，从岗位库召回语义相关岗位。
- 岗位分析：按 job_id 或相似 JD 检索历史相关岗位，辅助风险判断。
- 定向简历：用目标岗位 JD 反向召回用户项目时，可复用统一的岗位文本格式。
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from app.llm.gateway import llm_gateway
from app.rag.vector_store import vector_store

logger = logging.getLogger(__name__)

COLLECTION_NAME = "job_kb"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
MIN_SPLIT_SIZE = 800


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
    def build_metadata(job: dict, *, chunk_type: str = "full", chunk_index: int = 0) -> dict:
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
            "chunk_type": chunk_type,
            "chunk_index": chunk_index,
        }

    @classmethod
    def build_chunks(cls, job: dict) -> list[dict]:
        """按业务模块优先切块，长模块再用滑动窗口切分。

        策略：
        - 小于等于 800 中文字符的模块不切。
        - 超过 800 字按 800 字窗口切，保留 120 字 overlap。
        - 每个 chunk 都保留 job_id、chunk_type、chunk_index 等 metadata。
        """
        sections = cls._semantic_sections(job)
        chunks: list[dict] = []
        for section_type, text in sections:
            normalized = cls._normalize_text(text)
            if not normalized:
                continue
            for part_index, chunk_text in enumerate(cls._split_long_text(normalized)):
                chunks.append({
                    "id": f"job_{job['id']}_{section_type}_{part_index}",
                    "content": chunk_text,
                    "metadata": cls.build_metadata(
                        job,
                        chunk_type=section_type,
                        chunk_index=part_index,
                    ),
                })
        return chunks

    @staticmethod
    def _semantic_sections(job: dict) -> list[tuple[str, str]]:
        """把岗位拆成稳定语义模块，而不是简单整段 embedding。"""
        requirements = "；".join(str(item) for item in job.get("requirements") or [])
        benefits = "；".join(str(item) for item in job.get("benefits") or [])
        summary = "\n".join([
            f"岗位名称：{job.get('job_title') or ''}",
            f"公司名称：{job.get('company_name') or ''}",
            f"岗位大类：{job.get('job_category') or ''}",
            f"细分方向：{job.get('sub_category') or ''}",
            f"工作地点：{job.get('location') or ''}",
            f"薪资范围：{job.get('salary_min') or ''}-{job.get('salary_max') or ''}",
            f"来源类型：{job.get('source_type') or ''}",
        ])
        jd_sections = JobKnowledgeBase._split_jd_by_headings(str(job.get("jd_text") or ""))
        sections = [
            ("summary", summary),
            ("requirements", f"岗位要求：{requirements}" if requirements else ""),
            ("benefits", f"福利待遇：{benefits}" if benefits else ""),
        ]
        sections.extend(jd_sections)
        return sections

    @staticmethod
    def _split_jd_by_headings(text: str) -> list[tuple[str, str]]:
        """按常见 JD 标题切分；识别不到标题时作为 jd_description。"""
        normalized = JobKnowledgeBase._normalize_text(text)
        if not normalized:
            return []

        heading_patterns = {
            "responsibilities": r"(岗位职责|工作职责|职位描述|工作内容|你将负责|职责描述)",
            "requirements_detail": r"(任职要求|岗位要求|职位要求|我们希望你|任职资格|基本要求)",
            "bonus": r"(加分项|优先条件|优先考虑|加分条件)",
            "benefits_detail": r"(福利待遇|薪酬福利|你将获得|员工福利)",
            "company_intro": r"(公司介绍|关于我们|团队介绍)",
        }
        combined = "|".join(f"(?P<{name}>{pattern})" for name, pattern in heading_patterns.items())
        matches = list(re.finditer(combined, normalized, flags=re.IGNORECASE))
        if not matches:
            return [("jd_description", normalized)]

        sections: list[tuple[str, str]] = []
        if matches[0].start() > 0:
            sections.append(("jd_description", normalized[:matches[0].start()].strip()))
        for index, match in enumerate(matches):
            section_type = next((name for name, value in match.groupdict().items() if value), "jd_description")
            end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
            sections.append((section_type, normalized[match.start():end].strip()))
        return sections

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", str(text or "").strip())

    @staticmethod
    def _split_long_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
        """滑动窗口切块，优先在换行/句号附近断开。"""
        if len(text) <= MIN_SPLIT_SIZE:
            return [text]

        chunks: list[str] = []
        start = 0
        while start < len(text):
            hard_end = min(len(text), start + chunk_size)
            end = hard_end
            if hard_end < len(text):
                window = text[start:hard_end]
                breakpoints = [window.rfind(mark) for mark in ("\n", "。", "；", ";", ".")]
                best = max(breakpoints)
                if best >= chunk_size * 0.6:
                    end = start + best + 1
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(0, end - overlap)
        return chunks

    async def upsert_jobs(self, jobs: Iterable[dict]) -> int:
        """批量写入/更新岗位向量。

        Chroma 的 upsert 允许同一个 job_id 重复同步，适合定时刷新岗位库。
        """
        normalized_jobs = [job for job in jobs if job.get("id")]
        if not normalized_jobs:
            return 0

        chunk_records = [
            chunk
            for job in normalized_jobs
            for chunk in self.build_chunks(job)
        ]
        if not chunk_records:
            return 0

        documents = [chunk["content"] for chunk in chunk_records]
        metadatas = [chunk["metadata"] for chunk in chunk_records]
        ids = [chunk["id"] for chunk in chunk_records]

        embeddings = await llm_gateway.embed(documents)
        collection = vector_store.get_or_create_collection(COLLECTION_NAME)
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        logger.info("[JobKB] upserted %s chunks from %s jobs", len(ids), len(normalized_jobs))
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
