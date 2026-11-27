"""长期记忆：SQLite 元数据 + Chroma 向量（cosine、repo_id 过滤）。

architecture.md §4.4 / §7：
- 单一 collection ``long_term_memory``，显式 cosine
- ``memories.id`` ↔ Chroma id，metadata ``{repo_id, kind}``
- 检索：embedding cosine top-k + 分数阈值（低于阈值不注入）
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import load_settings
from app.db.models import MemoryRow, RepoRow
from app.db.session import init_db, session_scope
from app.llm.embed import EmbedClient, create_embed_client

COLLECTION_NAME = "long_term_memory"


@dataclass(slots=True)
class MemoryHit:
    """检索命中（含分数，score ∈ [0,1] cosine 相似度）。"""

    id: str
    repo_id: str
    kind: str
    title: str
    content: str
    task_ref: str | None
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "kind": self.kind,
            "title": self.title,
            "content": self.content,
            "task_ref": self.task_ref,
            "score": self.score,
        }


class LongTermMemory:
    """读写 memories 表 + Chroma 向量。"""

    def __init__(
        self,
        *,
        chroma_dir: str | Path | None = None,
        embed: EmbedClient | None = None,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        settings = load_settings()
        self.chroma_dir = Path(chroma_dir or settings.chroma_dir)
        self.collection_name = collection_name
        self._embed = embed
        self._collection: Any = None
        self._client: Any = None

    # ------------------------------------------------------------------ #
    # Chroma
    # ------------------------------------------------------------------ #
    @property
    def embed(self) -> EmbedClient:
        if self._embed is None:
            self._embed = create_embed_client()
        return self._embed

    def _get_collection(self) -> Any:
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("chromadb 未安装") from e

        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.chroma_dir))
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},  # 显式 cosine
        )
        return self._collection

    def reset_collection(self) -> None:
        """测试用：删除并重建 collection。"""
        import chromadb

        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.chroma_dir))
        with contextlib.suppress(Exception):
            self._client.delete_collection(self.collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------ #
    # SQLite 元数据
    # ------------------------------------------------------------------ #
    def ensure_repo(self, repo_id: str, *, name: str | None = None, path: str = "") -> str:
        """登记仓库（幂等）。"""
        init_db()
        with session_scope() as s:
            row = s.get(RepoRow, repo_id)
            if row is None:
                s.add(
                    RepoRow(
                        id=repo_id,
                        name=name or repo_id,
                        path=path or repo_id,
                        onboarding_status="pending",
                    )
                )
                return repo_id
        return repo_id

    def set_onboarding_status(self, repo_id: str, status: str) -> None:
        init_db()
        with session_scope() as s:
            row = s.get(RepoRow, repo_id)
            if row is not None:
                row.onboarding_status = status

    def add(
        self,
        *,
        repo_id: str,
        kind: str,
        title: str,
        content: str,
        task_ref: str | None = None,
        memory_id: str | None = None,
    ) -> str:
        """写入 memories 表 + 向量；返回 memory id。"""
        if kind not in {"convention", "episode"}:
            raise ValueError(f"kind 必须是 convention|episode，收到 {kind!r}")
        if not title or not content:
            raise ValueError("title/content 不得为空")

        mid = memory_id or f"mem_{uuid.uuid4().hex[:16]}"
        init_db()
        with session_scope() as s:
            # repo 必须存在
            if s.get(RepoRow, repo_id) is None:
                s.add(RepoRow(id=repo_id, name=repo_id, path=repo_id))
            s.add(
                MemoryRow(
                    id=mid,
                    repo_id=repo_id,
                    kind=kind,
                    title=title,
                    content=content,
                    task_ref=task_ref,
                )
            )

        # 向量：title + content 拼接
        text = f"{title}\n{content}"
        embedding = self.embed.embed_one(text)
        coll = self._get_collection()
        coll.upsert(
            ids=[mid],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{"repo_id": repo_id, "kind": kind}],
        )
        return mid

    def get(self, memory_id: str) -> MemoryRow | None:
        init_db()
        with session_scope() as s:
            return s.get(MemoryRow, memory_id)

    def list(
        self,
        *,
        repo_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRow]:
        init_db()
        with session_scope() as s:
            stmt = select(MemoryRow).order_by(MemoryRow.created_at.desc()).limit(limit)
            if repo_id:
                stmt = stmt.where(MemoryRow.repo_id == repo_id)
            if kind:
                stmt = stmt.where(MemoryRow.kind == kind)
            return list(s.scalars(stmt).all())

    def delete(self, memory_id: str) -> bool:
        init_db()
        deleted = False
        with session_scope() as s:
            row = s.get(MemoryRow, memory_id)
            if row is not None:
                s.delete(row)
                deleted = True
        try:
            coll = self._get_collection()
            coll.delete(ids=[memory_id])
        except Exception:  # noqa: BLE001 — 向量删除失败不阻断
            pass
        return deleted

    # ------------------------------------------------------------------ #
    # 检索
    # ------------------------------------------------------------------ #
    def search(
        self,
        query: str,
        *,
        repo_id: str,
        kind: str | None = None,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[MemoryHit]:
        """cosine top-k + 阈值过滤 + repo_id 过滤。"""
        if not query.strip():
            return []
        settings = load_settings()
        k = top_k if top_k is not None else settings.memory_top_k
        threshold = min_score if min_score is not None else settings.memory_min_score

        coll = self._get_collection()
        q_emb = self.embed.embed_one(query)

        where: dict[str, Any] = {"repo_id": repo_id}
        if kind:
            where = {"$and": [{"repo_id": repo_id}, {"kind": kind}]}

        res = coll.query(
            query_embeddings=[q_emb],
            n_results=max(1, k),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        hits: list[MemoryHit] = []
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for i, mid in enumerate(ids):
            # Chroma cosine distance → similarity = 1 - distance
            dist = float(dists[i]) if i < len(dists) else 1.0
            score = 1.0 - dist
            if score < threshold:
                continue
            meta = metas[i] if i < len(metas) else {}
            doc = docs[i] if i < len(docs) else ""
            # title 取首行
            title, _, content = (doc or "").partition("\n")
            # 元数据回查 SQLite 保证 title/content 一致
            row = self.get(str(mid))
            hits.append(
                MemoryHit(
                    id=str(mid),
                    repo_id=str(meta.get("repo_id") or (row.repo_id if row else "")),
                    kind=str(meta.get("kind") or (row.kind if row else "")),
                    title=row.title if row else title,
                    content=row.content if row else content,
                    task_ref=row.task_ref if row else None,
                    score=score,
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    def count(self, *, repo_id: str | None = None, kind: str | None = None) -> int:
        init_db()
        with session_scope() as s:
            stmt = select(MemoryRow)
            if repo_id:
                stmt = stmt.where(MemoryRow.repo_id == repo_id)
            if kind:
                stmt = stmt.where(MemoryRow.kind == kind)
            return len(list(s.scalars(stmt).all()))


def ensure_repo(repo_id: str, **kwargs: Any) -> str:
    return LongTermMemory().ensure_repo(repo_id, **kwargs)


def get_long_term(**kwargs: Any) -> LongTermMemory:
    return LongTermMemory(**kwargs)
