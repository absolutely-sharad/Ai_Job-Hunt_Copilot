"""API contract tests against the running FastAPI app."""

JD = """Hiring an AI/ML Engineer to build RAG systems in Python, design agentic
pipelines, and ship LLM features. Required: Python, RAG, FastAPI, vector databases."""

DOCUMENT = {
    "title": "AI Job-Hunt Copilot",
    "kind": "project",
    "content": (
        "Built a production RAG pipeline in Python using ChromaDB, Gemini embeddings, "
        "MMR re-ranking, and a LangGraph agent workflow exposed through FastAPI."
    ),
}


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_reports_checks(client):
    body = client.get("/readyz").json()
    assert body["status"] in ("ready", "degraded")
    assert "vector_store" in body["checks"]


def test_request_id_header_is_returned(client):
    assert client.get("/healthz").headers.get("X-Request-ID")


def test_document_lifecycle(client):
    created = client.post("/api/v1/profile/documents", json=DOCUMENT)
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    assert created.json()["chunk_count"] >= 1

    listed = client.get("/api/v1/profile/documents")
    assert any(item["id"] == document_id for item in listed.json())

    assert client.delete(f"/api/v1/profile/documents/{document_id}").status_code == 204
    assert client.delete(f"/api/v1/profile/documents/{document_id}").status_code == 404


def test_tailor_requires_indexed_evidence(client):
    response = client.post("/api/v1/tailor", json={"job_description": JD})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "empty_corpus"


def test_tailor_returns_grounded_result(client):
    client.post("/api/v1/profile/documents", json=DOCUMENT)
    response = client.post("/api/v1/tailor", json={"job_description": JD})
    assert response.status_code == 200, response.text
    body = response.json()
    valid_ids = {chunk["id"] for chunk in body["evidence"]}
    for bullet in body["resume_bullets"]:
        assert set(bullet["evidence_ids"]) <= valid_ids

    stored = client.get(f"/api/v1/runs/{body['run_id']}")
    assert stored.status_code == 200
    assert stored.json()["run_id"] == body["run_id"]


def test_validation_error_on_short_jd(client):
    assert client.post("/api/v1/tailor", json={"job_description": "too short"}).status_code == 422
