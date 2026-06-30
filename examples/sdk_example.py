"""Minimal Python client for the Distillery API using httpx.

Usage:
    pip install httpx
    export DISTILLERY_BASE_URL=http://localhost:8000
    export DISTILLERY_API_KEY=dev-local-admin-key
    python examples/sdk_example.py

Creates a response-based distillation job from a request body, polls until it
reaches a terminal state, and prints the evaluation summary and artifact URIs.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

BASE_URL = os.environ.get("DISTILLERY_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("DISTILLERY_API_KEY", "dev-local-admin-key")
REQUEST = Path(__file__).parent / "requests" / "create_job_response_based.json"

TERMINAL = {"succeeded", "failed", "cancelled"}


def main() -> None:
    headers = {"X-API-Key": API_KEY}
    payload = json.loads(REQUEST.read_text())

    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=30.0) as client:
        created = client.post("/api/v1/jobs", json=payload)
        created.raise_for_status()
        job = created.json()
        job_id = job["id"]
        print(f"Created job {job_id} (status={job['status']})")

        # Poll until terminal (in eager mode it is already done).
        while job["status"] not in TERMINAL:
            time.sleep(2.0)
            job = client.get(f"/api/v1/jobs/{job_id}").json()
            print(f"  status={job['status']} progress={job['progress_percent']}%")

        print(f"\nFinal status: {job['status']}")
        if job["status"] == "succeeded":
            ev = job["evaluation"]
            print(f"  accuracy            : {ev['primary_metric']:.4f}")
            print(f"  teacher agreement   : {ev['teacher_agreement']:.4f}")
            print(f"  compression ratio   : {ev['compression_ratio']:.2f}x")
            print(f"  accuracy retention  : {ev['teacher_accuracy_retention']:.4f}")
            artifacts = client.get(f"/api/v1/jobs/{job_id}/artifacts").json()
            print("  artifacts:")
            for a in artifacts:
                print(f"    - {a['type']}: {a['uri']}")
        else:
            print(f"  error: {job.get('error')}")


if __name__ == "__main__":
    main()
