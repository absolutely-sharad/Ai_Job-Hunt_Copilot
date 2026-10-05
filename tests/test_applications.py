"""Tracker, run-history, and document-detail endpoints."""

from __future__ import annotations

import pytest

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


def _create(client, **overrides) -> dict:
    body = {"job_title": "Backend Engineer", "company": "Acme", **overrides}
    response = client.post("/api/v1/applications", json=body)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def run_id(client) -> str:
    client.post("/api/v1/profile/documents", json=DOCUMENT)
    response = client.post("/api/v1/tailor", json={"job_description": JD})
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def test_application_defaults(client):
    created = _create(client)
    assert created["status"] == "saved"
    assert created["applied_at"] is None
    assert created["run_id"] is None
    assert created["created_at"].endswith(("Z", "+00:00"))  # timezone-aware on SQLite too
    assert client.delete(f"/api/v1/applications/{created['id']}").status_code == 204


def test_application_lifecycle(client):
    created = _create(client, url="https://acme.example/jobs/1", notes="referral via Sam")
    app_id = created["id"]

    assert client.get(f"/api/v1/applications/{app_id}").json()["notes"] == "referral via Sam"
    assert any(a["id"] == app_id for a in client.get("/api/v1/applications").json())

    patched = client.patch(f"/api/v1/applications/{app_id}", json={"notes": "phone screen Tue"})
    assert patched.status_code == 200
    assert patched.json()["notes"] == "phone screen Tue"
    assert patched.json()["company"] == "Acme"  # untouched fields survive a partial update

    assert client.delete(f"/api/v1/applications/{app_id}").status_code == 204
    assert client.get(f"/api/v1/applications/{app_id}").status_code == 404
    assert client.patch(f"/api/v1/applications/{app_id}", json={}).status_code == 404


def test_applied_date_is_stamped_once_on_first_application(client):
    app_id = _create(client)["id"]
    applied = client.patch(f"/api/v1/applications/{app_id}", json={"status": "applied"}).json()
    assert applied["applied_at"] is not None

    later = client.patch(f"/api/v1/applications/{app_id}", json={"status": "interviewing"}).json()
    assert later["applied_at"] == applied["applied_at"]  # not re-stamped on later stages

    cleared = client.patch(f"/api/v1/applications/{app_id}", json={"applied_at": None}).json()
    assert cleared["applied_at"] is None  # explicit null clears it
    client.delete(f"/api/v1/applications/{app_id}")


def test_rejecting_a_saved_job_does_not_invent_an_applied_date(client):
    app_id = _create(client)["id"]
    rejected = client.patch(f"/api/v1/applications/{app_id}", json={"status": "rejected"}).json()
    assert rejected["status"] == "rejected" and rejected["applied_at"] is None
    client.delete(f"/api/v1/applications/{app_id}")


def test_null_does_not_erase_required_fields(client):
    app_id = _create(client)["id"]
    patched = client.patch(f"/api/v1/applications/{app_id}", json={"job_title": None}).json()
    assert patched["job_title"] == "Backend Engineer"
    client.delete(f"/api/v1/applications/{app_id}")


def test_status_filter(client):
    saved = _create(client, company="FilterCo")["id"]
    offer = _create(client, company="FilterCo", status="offer")["id"]
    rows = client.get("/api/v1/applications", params={"status": "offer"}).json()
    ids = {row["id"] for row in rows}
    assert offer in ids and saved not in ids
    assert all(row["status"] == "offer" for row in rows)
    for app_id in (saved, offer):
        client.delete(f"/api/v1/applications/{app_id}")


@pytest.mark.parametrize(
    "payload",
    [
        {"job_title": ""},
        {"job_title": "Eng", "status": "ghosted"},
        {"job_title": "Eng", "url": "javascript:alert(1)"},
        {"job_title": "Eng", "url": "data:text/html,<script>1</script>"},
    ],
)
def test_invalid_application_is_rejected(client, payload):
    assert client.post("/api/v1/applications", json=payload).status_code == 422


def test_unknown_status_filter_is_rejected(client):
    assert client.get("/api/v1/applications", params={"status": "nope"}).status_code == 422


def test_application_linked_to_run_snapshots_score_and_survives_run_deletion(client, run_id):
    score = client.get(f"/api/v1/runs/{run_id}").json()["match_report"]["ats_score"]
    created = _create(client, run_id=run_id)
    assert created["run_id"] == run_id
    assert created["ats_score"] == score

    assert client.delete(f"/api/v1/runs/{run_id}").status_code == 204
    survivor = client.get(f"/api/v1/applications/{created['id']}").json()
    assert survivor["run_id"] is None
    assert survivor["ats_score"] == score  # snapshot outlives the run
    client.delete(f"/api/v1/applications/{created['id']}")


def test_application_for_unknown_run_is_404(client):
    response = client.post(
        "/api/v1/applications", json={"job_title": "Eng", "run_id": "run-missing"}
    )
    assert response.status_code == 404


def test_run_history_list_pagination_and_delete(client, run_id):
    listed = client.get("/api/v1/runs").json()
    row = next(item for item in listed if item["run_id"] == run_id)
    assert {"job_title", "company", "ats_score", "latency_ms", "created_at"} <= row.keys()

    assert client.get("/api/v1/runs", params={"limit": 1, "offset": 0}).status_code == 200
    assert client.get("/api/v1/runs", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/runs", params={"limit": 101}).status_code == 422
    assert client.get("/api/v1/runs", params={"offset": -1}).status_code == 422

    assert client.delete(f"/api/v1/runs/{run_id}").status_code == 204
    assert client.get(f"/api/v1/runs/{run_id}").status_code == 404
    assert client.delete(f"/api/v1/runs/{run_id}").status_code == 404


def test_document_detail_returns_citable_chunks(client):
    created = client.post(
        "/api/v1/profile/documents",
        json={**DOCUMENT, "content": ("Built a RAG pipeline in Python. " * 80).strip()},
    ).json()
    detail = client.get(f"/api/v1/profile/documents/{created['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert len(body["chunks"]) == created["chunk_count"] > 1
    assert [c["position"] for c in body["chunks"]] == sorted(c["position"] for c in body["chunks"])
    assert all(
        c["id"].startswith("ev-") and c["document_id"] == created["id"] for c in body["chunks"]
    )

    client.delete(f"/api/v1/profile/documents/{created['id']}")
    assert client.get(f"/api/v1/profile/documents/{created['id']}").status_code == 404
