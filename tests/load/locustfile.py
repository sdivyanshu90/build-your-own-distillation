"""Locust load test for the Distillery API.

Run against a deployed instance:

    locust -f tests/load/locustfile.py --host https://distillery.example.com \
        --users 50 --spawn-rate 5

Set ``DISTILLERY_LOAD_API_KEY`` to a valid operator/admin key. The job-creation
task uses tiny ``config_only`` models so the load focuses on the API/queue path
rather than GPU training.
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task

API_KEY = os.environ.get("DISTILLERY_LOAD_API_KEY", "test-admin-key-000")
_HEADERS = {"X-API-Key": API_KEY}

_JOB = {
    "name": "load-test",
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
        "dataset": {
            "format": "inline",
            "label_names": ["neg", "pos"],
            "inline_rows": [{"text": "good", "label": 1}, {"text": "bad", "label": 0}],
        },
        "training": {"epochs": 1, "train_batch_size": 2},
    },
}


class DistilleryUser(HttpUser):
    """Simulates a client polling health and listing/creating jobs."""

    wait_time = between(0.5, 2.0)

    @task(5)
    def health(self) -> None:
        self.client.get("/health", name="GET /health")

    @task(3)
    def list_jobs(self) -> None:
        self.client.get("/api/v1/jobs", headers=_HEADERS, name="GET /jobs")

    @task(1)
    def create_job(self) -> None:
        self.client.post("/api/v1/jobs", headers=_HEADERS, json=_JOB, name="POST /jobs")
