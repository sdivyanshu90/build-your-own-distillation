"""S3-compatible object storage backend (AWS S3, MinIO, R2, ...).

``boto3`` is imported lazily so the dependency is only required when the S3
backend is actually selected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from distillery.domain.exceptions import ArtifactNotFoundError


class S3ArtifactStorage:
    """Stores artifacts in an S3-compatible bucket under a key prefix."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "distillery",
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("An S3 bucket name is required")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        if client is not None:
            self._client = client
        else:  # pragma: no cover - exercised only with real AWS credentials
            import boto3

            self._client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        return f"{self._prefix}/{key}" if self._prefix else key

    def save_file(self, local_path: Path, key: str) -> str:
        self._client.upload_file(str(local_path), self._bucket, self._full_key(key))
        return self.uri_for(key)

    def save_directory(self, local_dir: Path, key_prefix: str) -> str:
        local_dir = Path(local_dir)
        for path in local_dir.rglob("*"):
            if path.is_file():
                rel = path.relative_to(local_dir).as_posix()
                self._client.upload_file(
                    str(path), self._bucket, self._full_key(f"{key_prefix}/{rel}")
                )
        return self.uri_for(key_prefix)

    def open_stream(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=self._full_key(key))
        except Exception as exc:
            raise ArtifactNotFoundError(details={"key": key}) from exc
        data: bytes = response["Body"].read()
        return data

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._full_key(key))
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        full = self._full_key(key)
        paginator = self._client.get_paginator("list_objects_v2")
        to_delete: list[dict[str, str]] = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=full):
            to_delete.extend({"Key": obj["Key"]} for obj in page.get("Contents", []))
        if to_delete:
            self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": to_delete})
        else:
            self._client.delete_object(Bucket=self._bucket, Key=full)

    def uri_for(self, key: str) -> str:
        return f"s3://{self._bucket}/{self._full_key(key)}"
