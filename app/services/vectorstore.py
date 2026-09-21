"""ChromaDB-backed vector store for the candidate profile corpus."""

from __future__ import annotations

import logging
import threading
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

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
