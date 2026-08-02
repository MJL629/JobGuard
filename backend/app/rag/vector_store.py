"""
Chroma 向量数据库管理
"""

import chromadb
from chromadb.config import Settings as ChromaSettings
from app.config import settings


class VectorStoreManager:
    """向量数据库管理器"""

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def get_or_create_collection(self, name: str):
        """获取或创建 Collection"""
        return self.client.get_or_create_collection(name=name)

    def list_collections(self):
        """列出所有 Collection"""
        return self.client.list_collections()

    def delete_collection(self, name: str):
        """删除 Collection"""
        try:
            self.client.delete_collection(name=name)
        except Exception:
            pass


# 全局单例
vector_store = VectorStoreManager()
