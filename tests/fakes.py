"""测试用的假模型：结果确定、不访问网络，用来替代 Ollama 和 fastembed。"""

import re
import zlib

from langchain_core.messages import AIMessage
from qdrant_client import models

FAKE_DIM = 32


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class FakeDenseEmbedder:
    """把单词哈希到固定维度后计数，词重合越多余弦相似度越高；记录调用过的文本。"""

    def __init__(self, dim: int = FAKE_DIM):
        self.dim = dim
        self.document_calls: list[str] = []

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for w in _words(text):
            vec[zlib.crc32(w.encode()) % self.dim] += 1.0
        if not any(vec):
            vec[0] = 1.0
        return vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls.extend(texts)
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class FakeSparseEmbedder:
    """以单词哈希为下标、词频为值的稀疏向量，效果近似关键词匹配。"""

    def _embed(self, text: str) -> models.SparseVector:
        counts: dict[int, float] = {}
        for w in _words(text):
            idx = zlib.crc32(w.encode()) % 100_000
            counts[idx] = counts.get(idx, 0.0) + 1.0
        return models.SparseVector(indices=list(counts), values=list(counts.values()))

    def embed_documents(self, texts: list[str]) -> list[models.SparseVector]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> models.SparseVector:
        return self._embed(text)


class FakeChatModel:
    """按顺序返回预先编排好的回复，并记录收到的消息。"""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.replies.pop(0))
