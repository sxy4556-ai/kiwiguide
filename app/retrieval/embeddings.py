"""向量化：稠密向量用 Ollama 的向量模型，稀疏向量用 fastembed 的 BM25。"""

from typing import Protocol

from qdrant_client import models

from app.config import Settings


class DenseEmbedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SparseEmbedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[models.SparseVector]: ...

    def embed_query(self, text: str) -> models.SparseVector: ...


def make_dense_embedder(settings: Settings) -> DenseEmbedder:
    """创建 Ollama 稠密向量模型；模型名和服务地址来自配置。"""
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(model=settings.embed_model, base_url=settings.ollama_base_url)


class FastembedSparse:
    """fastembed 的 BM25 稀疏向量；文档和查询的编码方式不同，分别调用对应的方法。"""

    def __init__(self, model_name: str):
        from fastembed import SparseTextEmbedding

        self._model = SparseTextEmbedding(model_name=model_name)

    @staticmethod
    def _to_qdrant(emb) -> models.SparseVector:
        return models.SparseVector(indices=emb.indices.tolist(), values=emb.values.tolist())

    def embed_documents(self, texts: list[str]) -> list[models.SparseVector]:
        return [self._to_qdrant(e) for e in self._model.embed(texts)]

    def embed_query(self, text: str) -> models.SparseVector:
        return self._to_qdrant(next(iter(self._model.query_embed(text))))


def make_sparse_embedder(settings: Settings) -> SparseEmbedder:
    return FastembedSparse(settings.sparse_model)


def probe_dimension(dense: DenseEmbedder) -> int:
    """实际编码一段文本来得到向量维度，换模型时不需要改代码。"""
    return len(dense.embed_query("dimension probe"))
