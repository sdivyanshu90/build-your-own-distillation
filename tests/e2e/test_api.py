"""End-to-end API tests through the ASGI app (TestClient, eager execution)."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.ml]


def _job_payload() -> dict:
    rows = [{"text": f"great {i}", "label": 1} for i in range(8)] + [
        {"text": f"bad {i}", "label": 0} for i in range(8)
    ]
    return {
        "name": "e2e-job",
        "config": {
            "strategy": "response_based",
            "teacher_type": "huggingface",
            "device": "cpu",
            "teacher": {
                "name_or_path": "t",
                "num_labels": 2,
                "config_only": True,
                "max_seq_length": 16,
            },
            "student": {
                "name_or_path": "s",
                "num_labels": 2,
                "config_only": True,
                "max_seq_length": 16,
            },
            "dataset": {"format": "inline", "label_names": ["neg", "pos"], "inline_rows": rows},
            "training": {"epochs": 1, "train_batch_size": 4, "warmup_ratio": 0.0},
            "kd": {"temperature": 2.0, "alpha": 0.5},
        },
    }


def test_health_and_ready(api_client) -> None:
    assert api_client.get("/health").status_code == 200
    r = api_client.get("/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["database"] == "ok"


def test_security_and_request_headers(api_client) -> None:
    r = api_client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "X-Request-ID" in r.headers


def test_requires_authentication(api_client) -> None:
    r = api_client.get("/api/v1/jobs")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_full_job_flow(api_client, admin_headers) -> None:
    create = api_client.post("/api/v1/jobs", headers=admin_headers, json=_job_payload())
    assert create.status_code == 202
    body = create.json()
    assert body["status"] == "succeeded"  # eager
    job_id = body["id"]
    assert body["evaluation"]["primary_metric"] is not None
    assert "X-RateLimit-Remaining" in create.headers

    listed = api_client.get("/api/v1/jobs", headers=admin_headers)
    assert listed.json()["total"] == 1

    got = api_client.get(f"/api/v1/jobs/{job_id}", headers=admin_headers)
    assert got.status_code == 200

    arts = api_client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=admin_headers)
    assert len(arts.json()) >= 3

    # delete terminal job
    assert api_client.delete(f"/api/v1/jobs/{job_id}", headers=admin_headers).status_code == 204
    assert api_client.get(f"/api/v1/jobs/{job_id}", headers=admin_headers).status_code == 404


def test_not_found_envelope(api_client, admin_headers) -> None:
    r = api_client.get("/api/v1/jobs/missing", headers=admin_headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "job_not_found"
    assert r.json()["error"]["request_id"]


def test_validation_error(api_client, admin_headers) -> None:
    r = api_client.post(
        "/api/v1/jobs", headers=admin_headers, json={"name": "x", "config": {"strategy": "nope"}}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "request_validation_error"


def test_auth_user_login_and_rbac(api_client, admin_headers) -> None:
    # admin creates a viewer
    created = api_client.post(
        "/api/v1/auth/users",
        headers=admin_headers,
        json={"email": "viewer@x.io", "password": "viewerpassword1", "role": "viewer"},
    )
    assert created.status_code == 201

    token = api_client.post(
        "/api/v1/auth/login", json={"email": "viewer@x.io", "password": "viewerpassword1"}
    ).json()["access_token"]
    bearer = {"Authorization": f"Bearer {token}"}

    me = api_client.get("/api/v1/auth/me", headers=bearer)
    assert me.json()["role"] == "viewer"

    # viewer cannot create jobs (needs operator)
    forbidden = api_client.post("/api/v1/jobs", headers=bearer, json=_job_payload())
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


def test_api_key_self_service(api_client, admin_headers) -> None:
    issued = api_client.post(
        "/api/v1/auth/api-keys", headers=admin_headers, json={"name": "ci", "role": "operator"}
    )
    assert issued.status_code == 201
    assert issued.json()["api_key"].startswith("dst_")
    listed = api_client.get("/api/v1/auth/api-keys", headers=admin_headers)
    assert any(k["name"] == "ci" for k in listed.json())


def test_metrics_endpoint(api_client) -> None:
    r = api_client.get("/metrics")
    assert r.status_code == 200
    assert b"distillery_http_requests_total" in r.content


def test_openapi_available(api_client) -> None:
    schema = api_client.get("/openapi.json").json()
    assert schema["info"]["license"]["name"] == "Apache-2.0"
    assert "/api/v1/jobs" in schema["paths"]
