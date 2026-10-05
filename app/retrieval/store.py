"""存储：子块的向量存进 Qdrant 本地库，父块和文档的 content_hash 存进 SQLite。"""

import json
import sqlite3
import uuid
from dataclasses import asdict
from pathlib import Path

from qdrant_client import QdrantClient, models

from app.ingest.chunk import Chunk

COLLECTION = "kiwiguide_chunks"
DENSE = "dense"
SPARSE = "sparse"


def point_id(chunk_id: str) -> str:
    """Qdrant 的点 id 只接受整数或 UUID，由块 id 派生出稳定的 UUID。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def _topic_filter(topic: str | None) -> models.Filter | None:
    if not topic:
        return None
    return models.Filter(
        must=[models.FieldCondition(key="topic", match=models.MatchValue(value=topic))]
    )


class VectorStore:
    """Qdrant 集合里每个点是一个子块，带命名的 dense 和 sparse 两种向量，payload 是块的元数据。"""

    def __init__(self, client: QdrantClient, dim: int, collection: str = COLLECTION):
        self.client = client
        self.collection = collection
        if not client.collection_exists(collection):
            client.create_collection(
                collection,
                vectors_config={
                    DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)
                },
                # BM25 的 IDF 由 Qdrant 按集合统计计算
                sparse_vectors_config={
                    SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
        else:
            existing = client.get_collection(collection).config.params.vectors[DENSE].size
            if existing != dim:
                raise ValueError(
                    f"索引的向量维度是 {existing}，当前向量模型是 {dim}；更换向量模型后需要重建索引"
                )

    @classmethod
    def open(cls, path: Path, dim: int) -> "VectorStore":
        Path(path).mkdir(parents=True, exist_ok=True)
        return cls(QdrantClient(path=str(path)), dim)

    def upsert(
        self,
        chunks: list[Chunk],
        dense: list[list[float]],
        sparse: list[models.SparseVector],
    ) -> None:
        points = [
            models.PointStruct(
                id=point_id(c.id),
                vector={DENSE: d, SPARSE: s},
                payload=asdict(c),
            )
            for c, d, s in zip(chunks, dense, sparse, strict=True)
        ]
        self.client.upsert(self.collection, points=points)

    def delete_url(self, url: str) -> None:
        selector = models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="url", match=models.MatchValue(value=url))]
            )
        )
        self.client.delete(self.collection, points_selector=selector)

    def count(self) -> int:
        return self.client.count(self.collection).count

    def search(
        self,
        vector: list[float] | models.SparseVector,
        using: str,
        limit: int,
        topic: str | None = None,
    ) -> list[dict]:
        """单路检索，返回按相似度降序的子块 payload。"""
        result = self.client.query_points(
            self.collection,
            query=vector,
            using=using,
            limit=limit,
            query_filter=_topic_filter(topic),
            with_payload=True,
        )
        return [p.payload for p in result.points]

    def close(self) -> None:
        self.client.close()


class ParentStore:
    """父块表按 id 回取正文；文档表记录每个页面的 content_hash，用于增量索引。"""

    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # 并行检索会在其他线程里回取父块；并发访问由 HybridSearcher 的锁串行化
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS parents (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT, topic TEXT,
                heading_path TEXT, retrieved_at TEXT, text TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS parents_url ON parents(url);
            CREATE TABLE IF NOT EXISTS documents (
                url TEXT PRIMARY KEY, title TEXT, topic TEXT, retrieved_at TEXT,
                content_hash TEXT NOT NULL, n_parents INTEGER, n_children INTEGER
            );
            """
        )

    def save_document(self, doc: dict, parents: list[Chunk], n_children: int) -> None:
        """替换一个页面的全部父块并记录 content_hash，在同一个事务里完成。"""
        with self.conn:
            self.conn.execute("DELETE FROM parents WHERE url = ?", (doc["url"],))
            self.conn.executemany(
                "INSERT INTO parents VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (p.id, p.url, p.title, p.topic, json.dumps(p.heading_path, ensure_ascii=False),
                     p.retrieved_at, p.text)
                    for p in parents
                ],
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
                (doc["url"], doc["title"], doc["topic"], doc["retrieved_at"],
                 doc["content_hash"], len(parents), n_children),
            )

    def delete_url(self, url: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM parents WHERE url = ?", (url,))
            self.conn.execute("DELETE FROM documents WHERE url = ?", (url,))

    def document_hashes(self) -> dict[str, str]:
        return dict(self.conn.execute("SELECT url, content_hash FROM documents"))

    def get_parents(self, ids: list[str]) -> list[Chunk]:
        """按传入顺序返回父块，找不到的 id 跳过。"""
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(f"SELECT * FROM parents WHERE id IN ({marks})", ids)
        by_id = {}
        for id_, url, title, topic, heading_path, retrieved_at, text in rows:
            by_id[id_] = Chunk(id_, id_, url, title, topic, json.loads(heading_path),
                               retrieved_at, text)
        return [by_id[i] for i in ids if i in by_id]

    def count(self) -> tuple[int, int]:
        """返回 (文档数, 父块数)。"""
        docs = self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        parents = self.conn.execute("SELECT COUNT(*) FROM parents").fetchone()[0]
        return docs, parents

    def close(self) -> None:
        self.conn.close()
