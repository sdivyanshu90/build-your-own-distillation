"""End-to-end CLI tests via Typer's CliRunner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from distillery.cli.main import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


@pytest.mark.usefixtures("configured_env")
def test_db_and_credential_commands() -> None:
    assert runner.invoke(app, ["db", "create-all"]).exit_code == 0
    seed = runner.invoke(app, ["db", "seed"])
    assert seed.exit_code == 0

    created = runner.invoke(
        app, ["user", "create", "cli@x.io", "--password", "clipassword123", "--role", "operator"]
    )
    assert created.exit_code == 0, created.stdout

    key = runner.invoke(app, ["apikey", "create", "cli@x.io", "--name", "k"])
    assert key.exit_code == 0
    assert "dst_" in key.stdout


@pytest.mark.usefixtures("configured_env")
def test_apikey_unknown_user_fails() -> None:
    runner.invoke(app, ["db", "create-all"])
    result = runner.invoke(app, ["apikey", "create", "ghost@x.io"])
    assert result.exit_code != 0


@pytest.mark.ml
def test_distill_command(tmp_path: Path) -> None:
    config = {
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
            "inline_rows": [{"text": "great", "label": 1}, {"text": "awful", "label": 0}],
        },
        "training": {"epochs": 1, "train_batch_size": 2, "warmup_ratio": 0.0},
        "kd": {"temperature": 2.0, "alpha": 0.5},
    }
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")
    out = tmp_path / "out"
    result = runner.invoke(app, ["distill", str(cfg_path), "--output", str(out)])
    assert result.exit_code == 0, result.stdout
    assert "accuracy" in result.stdout
    assert (out / "student_model").exists()
