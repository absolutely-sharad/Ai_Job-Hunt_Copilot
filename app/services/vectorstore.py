"""ChromaDB-backed vector store for the candidate profile corpus."""

from __future__ import annotations

import logging
import math
import threading
from typing import Any

from sqlalchemy import delete, func, select

from app.core.config import Settings, get_settings
from app.core.logging import get_logger, log_event

logger = get_logger(__name__)
_lock = threading.Lock()


class VectorStore:
    """Thin wrapper over a persistent Chroma collection.

    Embeddings are supplied by the caller so the store stays provider-agnostic
    and Chroma never downloads its default ONNX embedding model at runtime.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        import chromadb  # lazy: optional dependency, absent from serverless bundles
        from chromadb.config import Settings as ChromaSettings

        self.client = chromadb.PersistentClient(
            path=self.settings.chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        self.collection = self.client.get_or_create_collection(
            name=self.settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        if not ids:
            return
        with _lock:
            self.collection.upsert(
                ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
            )
        log_event(logger, logging.INFO, "vectorstore_upsert", chunks=len(ids))

    def query(
        self, embedding: list[float], top_k: int, where: dict | None = None
    ) -> list[dict[str, Any]]:
        """Return candidates ordered by cosine similarity (1 - distance)."""
        if self.count() == 0:
            return []
        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, self.count()),
            where=where or None,
            include=["documents", "metadatas", "distances", "embeddings"],
        )
        hits: list[dict[str, Any]] = []
        for index, chunk_id in enumerate(result["ids"][0]):
            hits.append(
                {
                    "id": chunk_id,
                    "text": result["documents"][0][index],
                    "metadata": result["metadatas"][0][index],
                    "score": 1.0 - float(result["distances"][0][index]),
                    "embedding": list(result["embeddings"][0][index]),
                }
            )
        return hits

    def delete_document(self, document_id: str) -> None:
        with _lock:
            self.collection.delete(where={"document_id": document_id})
        log_event(logger, logging.INFO, "vectorstore_delete", document_id=document_id)

    def count(self) -> int:
        return self.collection.count()

    def reset(self) -> None:
        self.client.delete_collection(self.settings.chroma_collection)
        self.collection = self.client.get_or_create_collection(
            name=self.settings.chroma_collection, metadata={"hnsw:space": "cosine"}
        )


class SqlVectorStore:
    """Vector store backed by the application database (SQLite or Postgres).

    Cosine similarity is computed in-process over the candidate set. That is
    exact and plenty fast for a personal profile corpus (hundreds of chunks),
    and it removes the need for a persistent disk, which serverless lacks.
    """

    def __init__(self, settings: Settings | None = None):
        from app.db.models import Base, ChunkRecord
        from app.db.session import engine

        self.settings = settings or get_settings()
        self._model = ChunkRecord
        self._engine = engine
        Base.metadata.create_all(bind=engine, tables=[ChunkRecord.__table__])

    def _session(self):
        from app.db.session import session_scope

        return session_scope()

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        if not ids:
            return
        with self._session() as session:
            for chunk_id, embedding, text, meta in zip(
                ids, embeddings, documents, metadatas, strict=True
            ):
                session.merge(
                    self._model(
                        id=chunk_id,
                        document_id=str(meta.get("document_id", "")),
                        text=text,
                        chunk_metadata=meta,
                        embedding=list(embedding),
                        norm=math.sqrt(sum(v * v for v in embedding)) or 1.0,
                    )
                )
        log_event(logger, logging.INFO, "vectorstore_upsert", chunks=len(ids))

    def query(
        self, embedding: list[float], top_k: int, where: dict | None = None
    ) -> list[dict[str, Any]]:
        """Return candidates ordered by cosine similarity."""
        query_norm = math.sqrt(sum(v * v for v in embedding)) or 1.0
        with self._session() as session:
            stmt = select(self._model)
            if where and "document_id" in where:
                stmt = stmt.where(self._model.document_id == where["document_id"])
            rows = session.execute(stmt).scalars().all()
            scored = []
            for row in rows:
                dot = sum(a * b for a, b in zip(embedding, row.embedding, strict=False))
                scored.append(
                    {
                        "id": row.id,
                        "text": row.text,
                        "metadata": dict(row.chunk_metadata),
                        "score": dot / (query_norm * row.norm),
                        "embedding": list(row.embedding),
                    }
                )
        scored.sort(key=lambda hit: hit["score"], reverse=True)
        return scored[:top_k]

    def delete_document(self, document_id: str) -> None:
        with self._session() as session:
            session.execute(delete(self._model).where(self._model.document_id == document_id))
        log_event(logger, logging.INFO, "vectorstore_delete", document_id=document_id)

    def count(self) -> int:
        with self._session() as session:
            return session.execute(select(func.count()).select_from(self._model)).scalar_one()

    def reset(self) -> None:
        with self._session() as session:
            session.execute(delete(self._model))


def create_vector_store(settings: Settings | None = None) -> VectorStore | SqlVectorStore:
    """Build the vector store selected by ``VECTOR_STORE``."""
    settings = settings or get_settings()
    if settings.vector_store == "sql":
        return SqlVectorStore(settings)
    return VectorStore(settings)
