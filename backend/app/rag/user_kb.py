"""
用户知识库操作

存储内容：用户简历、项目经历、技能、偏好
每个用户独立 Collection：user_{user_id}_kb
"""

from app.llm.gateway import llm_gateway
from app.rag.vector_store import vector_store


class UserKnowledgeBase:
    """用户知识库"""

    def _collection_name(self, user_id: str) -> str:
        return f"user_{user_id}_kb"

    async def add_documents(
        self,
        user_id: str,
        documents: list[str],
        metadatas: list[dict] | None = None,
    ):
        """
        添加文档到用户知识库

        Args:
            user_id: 用户 ID
            documents: 文本列表（每个项目/技能/偏好为一条）
            metadatas: 元数据列表
        """
        collection = vector_store.get_or_create_collection(self._collection_name(user_id))

        # 生成 Embedding
        embeddings = await llm_gateway.embed(documents)

        # 添加
        ids = [f"{user_id}_{i}_{hash(doc) % 100000}" for i, doc in enumerate(documents)]
        collection.add(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas or [{}] * len(documents),
            ids=ids,
        )

    async def search(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        filter_metadata: dict | None = None,
    ) -> list[dict]:
        """
        检索用户知识库

        Args:
            user_id: 用户 ID
            query: 检索查询
            top_k: 返回数量
            filter_metadata: 元数据过滤条件

        Returns:
            检索结果列表
        """
        collection_name = self._collection_name(user_id)
        collection = vector_store.get_or_create_collection(collection_name)

        # 生成查询向量
        query_embedding = await llm_gateway.embed([query])

        # 检索
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=top_k,
            where=filter_metadata,
        )

        # 格式化结果
        formatted = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                formatted.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else None,
                })

        return formatted

    async def clear(self, user_id: str):
        """清空用户知识库"""
        vector_store.delete_collection(self._collection_name(user_id))


# 全局单例
user_kb = UserKnowledgeBase()
