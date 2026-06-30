"""Integration tests for local artifact storage."""

from __future__ import annotations

import pytest

from distillery.domain.exceptions import ArtifactNotFoundError
from distillery.infrastructure.storage.base import compute_checksum, directory_size

pytestmark = pytest.mark.integration


def test_save_and_read_file(local_storage, tmp_path) -> None:
    src = tmp_path / "f.txt"
    src.write_text("hello", encoding="utf-8")
    uri = local_storage.save_file(src, "jobs/1/report.txt")
    assert uri.startswith("file://")
    assert local_storage.exists("jobs/1/report.txt")
    assert local_storage.open_stream("jobs/1/report.txt") == b"hello"


def test_save_and_read_directory(local_storage, tmp_path) -> None:
    d = tmp_path / "model"
    d.mkdir()
    (d / "config.json").write_text("{}", encoding="utf-8")
    (d / "weights.bin").write_bytes(b"\x00\x01")
    local_storage.save_directory(d, "jobs/1/student_model")
    assert local_storage.exists("jobs/1/student_model")
    assert local_storage.open_stream("jobs/1/student_model/config.json") == b"{}"


def test_delete_file_and_dir(local_storage, tmp_path) -> None:
    src = tmp_path / "f.txt"
    src.write_text("x", encoding="utf-8")
    local_storage.save_file(src, "a/b.txt")
    local_storage.delete("a/b.txt")
    assert not local_storage.exists("a/b.txt")


def test_missing_key_raises(local_storage) -> None:
    with pytest.raises(ArtifactNotFoundError):
        local_storage.open_stream("nope/missing.txt")


def test_path_traversal_blocked(local_storage) -> None:
    with pytest.raises(ValueError):
        local_storage.uri_for("../../etc/passwd")


def test_checksum_and_size(tmp_path) -> None:
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    assert compute_checksum(f) == compute_checksum(f)
    assert directory_size(f) == 3
    d = tmp_path / "dir"
    d.mkdir()
    (d / "a").write_bytes(b"ab")
    (d / "b").write_bytes(b"c")
    assert directory_size(d) == 3
