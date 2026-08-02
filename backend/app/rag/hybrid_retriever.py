"""
混合检索器 — P1 RAG 增强模块

包含三个组件：
- QueryRewriter: 用 LLM 改写自然语言查询为关键词组合
- BM25Retriever: 基于 BM25 的关键词检索
- HybridRetriever: 向量检索 + BM25 → RRF 融合排序的主检索器
"""

import asyncio
import logging
from collections import defaultdict

import jieba
from rank_bm25 import BM25Okapi

from app.llm.gateway import llm_gateway
from app.rag.vector_store import vector_store

logger = logging.getLogger(__name__)

# ─── RRF 常量 ──────────────────────────────────────────────────────────
RRF_K = 60


# ═══════════════════════════════════════════════════════════════════════
# 1. QueryRewriter — 查询改写
# ═══════════════════════════════════════════════════════════════════════

class QueryRewriter:
    """
    用 LLM 将用户的自然语言查询改写为 2-3 个更适合检索的关键词组合。
    """

    SYSTEM_PROMPT = (
        "你是一个招聘搜索查询改写助手。用户会输入自然语言描述的工作需求，"
        "你需要将其改写为 2-3 个精简的关键词搜索短语，用于搜索引擎检索。\n"
        "规则：\n"
        "1. 每行一个关键词短语，共 2-3 行\n"
        "2. 去掉语气词和冗余描述，保留核心语义\n"
        "3. 加入同义词或相关词以提高召回率\n"
        "4. 只输出关键词短语，不要输出序号、解释或其他内容\n\n"
        "示例输入：我想找不加班的后端开发工作\n"
        "示例输出：\n"
        "后端开发 双休 不加班 工作生活平衡\n"
        "后端工程师 965 弹性工作\n"
        "Golang Java 后端 双休"
    )

    async def rewrite(self, query: str) -> list[str]:
        """将自然语言查询改写为关键词短语列表"""
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]

        try:
            response = await llm_gateway.chat(
                messages=messages,
                temperature=0.3,
                max_tokens=256,
            )
        except Exception as e:
            logger.warning(f"[QueryRewriter] LLM 调用失败，回退到原始查询: {e}")
            return [query]

        # 解析返回的多行关键词短语
        lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
        if not lines:
            logger.warning("[QueryRewriter] 改写结果为空，回退到原始查询")
            return [query]

        logger.info(f"[QueryRewriter] {query!r} → {lines}")
        return lines


# ═══════════════════════════════════════════════════════════════════════
# 2. BM25Retriever — BM25 关键词检索
# ═══════════════════════════════════════════════════════════════════════

class BM25Retriever:
    """
    对所有文档建立 BM25 索引，支持关键词检索。
    """

    def __init__(self, documents: list[str]):
        """
        Args:
            documents: 文档文本列表，索引顺序即为文档 ID
        """
        self._documents = documents
        self._tokenized = [self._tokenize(doc) for doc in documents]
        self._bm25 = BM25Okapi(self._tokenized) if self._tokenized else None
        logger.info(f"[BM25Retriever] 已建立索引，文档数: {len(documents)}")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """jieba 分词"""
        return list(jieba.cut(text))

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """
        BM25 关键词检索。

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            [(doc_index, score), ...] 按分数降序排列
        """
        if not self._bm25 or not self._documents:
            return []

        tokenized = self._tokenize(query)
        scores = self._bm25.get_scores(tokenized)

        # 按分数降序取 top_k
        indexed = [(i, scores[i]) for i in range(len(scores))]
        indexed.sort(key=lambda x: x[1], reverse=True)

        result = indexed[:top_k]
        logger.debug(f"[BM25Retriever] query={query!r}, top_k={top_k}, hits={len(result)}")
        return result


# ═══════════════════════════════════════════════════════════════════════
# 3. HybridRetriever — 混合检索主类
# ═══════════════════════════════════════════════════════════════════════

class HybridRetriever:
    """
    混合检索器：QueryRewrite → BM25 + BGE-M3 向量检索 → RRF 融合 → 返回 top_k。
    """

    def __init__(self, collection_name: str):
        self._collection_name = collection_name
        self._rewriter = QueryRewriter()
        self._bm25: BM25Retriever | None = None
        self._initialized = False

    async def _ensure_bm25(self):
        """延迟加载 BM25 索引（从 Chroma 中拉取所有文档）"""
        if self._initialized:
            return

        collection = vector_store.get_or_create_collection(self._collection_name)
        try:
            result = collection.get()
        except Exception as e:
            logger.warning(f"[HybridRetriever] 无法获取 Collection 文档: {e}")
            self._bm25 = BM25Retriever([])
            self._initialized = True
            return

        documents = result.get("documents", []) or []
        self._bm25 = BM25Retriever(documents)
        self._initialized = True

    async def _vector_search(self, query: str, top_k: int) -> dict[int, float]:
        """BGE-M3 向量检索，返回 {doc_index: score}"""
        collection = vector_store.get_or_create_collection(self._collection_name)
        try:
            query_embedding = await llm_gateway.embed([query])
        except Exception as e:
            logger.error(f"[HybridRetriever] Embedding 失败: {e}")
            return {}

        try:
            results = collection.query(
                query_embeddings=query_embedding,
                n_results=top_k * 2,
            )
        except Exception as e:
            logger.error(f"[HybridRetriever] 向量检索失败: {e}")
            return {}

        index_scores: dict[int, float] = {}
        if results.get("ids") and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                distance = results.get("distances", [[0.0]])[0][i]
                score = 1.0 / (1.0 + distance)
                index_scores[int(doc_id)] = score

        return index_scores

    @staticmethod
    def _rrf_fusion(
        bm25_ranked: list[tuple[int, float]],
        vector_ranked: dict[int, float],
        alpha: float,
        k: int = RRF_K,
    ) -> list[tuple[int, float]]:
        """
        RRF 加权融合排序。

        score(d) = alpha * (1 / (k + rank_vec(d))) + (1 - alpha) * (1 / (k + rank_bm25(d)))

        Args:
            bm25_ranked: BM25 结果，已按分数降序排列
            vector_ranked: {doc_index: similarity_score}，用于确定向量排名
            alpha: 向量检索权重 (0~1)
            k: RRF 平滑常数

        Returns:
            [(doc_index, fused_score), ...] 按分数降序
        """
        # 计算向量排名 (按分数降序)
        vector_items = sorted(vector_ranked.items(), key=lambda x: x[1], reverse=True)
        vec_rank = {doc_id: rank + 1 for rank, (doc_id, _) in enumerate(vector_items)}

        bm25_rank = {doc_id: rank + 1 for rank, (doc_id, _) in enumerate(bm25_ranked)}

        all_doc_ids = set(bm25_rank.keys()) | set(vec_rank.keys())

        fused: list[tuple[int, float]] = []
        for doc_id in all_doc_ids:
            score = 0.0
            if doc_id in vec_rank:
                score += alpha * (1.0 / (k + vec_rank[doc_id]))
            if doc_id in bm25_rank:
                score += (1 - alpha) * (1.0 / (k + bm25_rank[doc_id]))
            fused.append((doc_id, score))

        fused.sort(key=lambda x: x[1], reverse=True)
        return fused

    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
        alpha: float = 0.7,
    ) -> list[dict]:
        """
        混合检索主入口。

        流程：QueryRewrite → BM25检索 + BGE-M3向量检索（并行） → RRF融合排序 → 返回 top_k

        Args:
            query: 用户原始查询
            top_k: 返回结果数
            alpha: 向量检索权重，0.7 表示向量占 70%，BM25 占 30%

        Returns:
            [{"content": str, "score": float, "metadata": dict}, ...]
        """
        await self._ensure_bm25()

        # Step 1: 查询改写
        rewritten = await self._rewriter.rewrite(query)
        logger.info(f"[HybridRetriever] 改写查询: {rewritten}")

        # Step 2: BM25 + 向量检索（并行）
        # BM25 对每个改写查询分别检索，合并结果
        bm25_results: dict[int, float] = {}
        for rq in rewritten:
            for doc_idx, score in self._bm25.search(rq, top_k=top_k * 2):
                if doc_idx not in bm25_results or score > bm25_results[doc_idx]:
                    bm25_results[doc_idx] = score

        # 向量检索（用原始查询，语义信息更完整）
        vector_task = self._vector_search(query, top_k)

        vector_results = await vector_task

        # Step 3: RRF 融合
        bm25_ranked = sorted(bm25_results.items(), key=lambda x: x[1], reverse=True)
        fused = self._rrf_fusion(bm25_ranked, vector_results, alpha)

        # Step 4: 取 top_k，并组装返回结果
        collection = vector_store.get_or_create_collection(self._collection_name)
        all_docs = collection.get()

        doc_map: dict[int, dict] = {}
        if all_docs.get("documents"):
            for i, doc_text in enumerate(all_docs["documents"]):
                doc_map[i] = {
                    "content": doc_text,
                    "metadata": all_docs["metadatas"][i] if all_docs.get("metadatas") else {},
                }

        result = []
        for doc_idx, score in fused[:top_k]:
            if doc_idx in doc_map:
                item = dict(doc_map[doc_idx])
                item["score"] = round(score, 6)
                result.append(item)

        logger.info(
            f"[HybridRetriever] 检索完成: query={query!r}, "
            f"bm25_hits={len(bm25_results)}, vec_hits={len(vector_results)}, "
            f"fused_top={len(result)}"
        )
        return result


# ─── 工厂函数 ──────────────────────────────────────────────────────────

def create_hybrid_retriever(collection_name: str) -> HybridRetriever:
    """创建指定 Collection 的混合检索器"""
    return HybridRetriever(collection_name)
