"""Local-filesystem artifact storage (development and single-node deployments)."""

from __future__ import annotations

import shutil
from pathlib import Path

from distillery.domain.exceptions import ArtifactNotFoundError


class LocalArtifactStorage:
    """Stores artifacts under a configurable root directory."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        # Prevent path traversal outside the storage root.
        target = (self._root / key.lstrip("/")).resolve()
        if not str(target).startswith(str(self._root)):
            raise ValueError(f"Storage key escapes root: {key}")
        return target

    def save_file(self, local_path: Path, key: str) -> str:
        dest = self._resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dest)
        return self.uri_for(key)

    def save_directory(self, local_dir: Path, key_prefix: str) -> str:
        dest = self._resolve(key_prefix)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(local_dir, dest)
        return self.uri_for(key_prefix)

    def open_stream(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise ArtifactNotFoundError(details={"key": key})
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    def uri_for(self, key: str) -> str:
        return self._resolve(key).as_uri()
