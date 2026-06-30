"""Artifact storage backends implementing the ``ArtifactStorage`` port."""

from __future__ import annotations

from distillery.config.settings import StorageBackend, StorageSettings
from distillery.domain.ports import ArtifactStorage
from distillery.infrastructure.storage.local import LocalArtifactStorage


def build_storage(settings: StorageSettings) -> ArtifactStorage:
    """Construct the configured storage backend."""
    if settings.backend is StorageBackend.S3:  # pragma: no cover - requires AWS/boto3
        from distillery.infrastructure.storage.s3 import S3ArtifactStorage

        return S3ArtifactStorage(
            bucket=settings.s3_bucket,
            prefix=settings.s3_prefix,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url or None,
        )
    return LocalArtifactStorage(root=settings.local_root)


__all__ = ["ArtifactStorage", "LocalArtifactStorage", "build_storage"]
