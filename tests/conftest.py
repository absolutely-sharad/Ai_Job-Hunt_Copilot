"""Shared fixtures. All tests run against the fake providers — no API key needed."""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ.update(
    {
        "LLM_PROVIDER": "fake",
        "ENVIRONMENT": "local",
        "LOG_LEVEL": "WARNING",
        "API_KEY": "",
    }
)

_TMP = tempfile.mkdtemp(prefix="copilot-test-")
os.environ["CHROMA_PATH"] = f"{_TMP}/chroma"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"


@pytest.fixture(scope="session")
def settings():
    from app.core.config import get_settings

    return get_settings()


@pytest.fixture
def store(settings, tmp_path):
    from app.services.vectorstore import VectorStore

    settings_copy = settings.model_copy(update={"chroma_path": str(tmp_path / "chroma")})
    return VectorStore(settings_copy)


@pytest.fixture
def embedder(settings):
    from app.services.embeddings import get_embedder

    return get_embedder(settings)


@pytest.fixture
def sample_documents() -> list[dict]:
    return [
        {
            "title": "AI Job-Hunt Copilot",
            "kind": "project",
            "content": (
                "Built a RAG pipeline in Python with ChromaDB and Gemini embeddings. "
                "Implemented MMR re-ranking and a grounding critic that rejects "
                "resume bullets citing no evidence.\n\n"
                "Orchestrated the agent workflow with LangGraph state machines and "
                "exposed it through a FastAPI service."
            ),
        },
        {
            "title": "Infonix Cloud",
            "kind": "experience",
            "content": (
                "Co-founded a software company delivering web and mobile products to "
                "60+ business clients using React.js, Node.js, and Laravel.\n\n"
                "Deployed AI chatbots that automate customer support and lead "
                "qualification for client businesses."
            ),
        },
        {
            "title": "Finance Tracker",
            "kind": "project",
            "content": (
                "Developed a full-stack finance tracker with React, TypeScript, and "
                "Supabase. Built dashboards with Recharts for income and expense "
                "category analysis."
            ),
        },
    ]


@pytest.fixture
def indexed_store(store, embedder, settings, sample_documents):
    from app.schemas.profile import DocumentIn
    from app.services.ingestion import IngestionService

    service = IngestionService(store, embedder, settings)
    for document in sample_documents:
        service.ingest(DocumentIn(**document))
    return store


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
