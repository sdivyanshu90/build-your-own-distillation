"""Unit tests for LLM-teacher data generation/labelling."""

from __future__ import annotations

import pytest

from distillery.domain.enums import DatasetFormat
from distillery.domain.exceptions import TeacherError
from distillery.domain.value_objects import DatasetSpec, LLMTeacherConfig
from distillery.teachers.llm.dataset_builder import (
    LLMDatasetBuilder,
    _coerce_label,
    _parse_json_object,
    build_llm_dataset,
)
from distillery.teachers.llm.prompts import build_generation_prompt, build_labelling_prompt
from tests.conftest import FakeLLMClient

pytestmark = pytest.mark.unit


def _gen_config(**kw) -> LLMTeacherConfig:
    base = dict(task_description="sentiment", label_names=["neg", "pos"], num_samples=4)
    base.update(kw)
    return LLMTeacherConfig(**base)


def test_parse_json_object_plain() -> None:
    assert _parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_json_object_fenced() -> None:
    assert _parse_json_object('```json\n{"a": 2}\n```') == {"a": 2}


def test_parse_json_object_embedded() -> None:
    assert _parse_json_object('Sure! {"a": 3} done') == {"a": 3}


def test_parse_json_object_malformed() -> None:
    with pytest.raises(TeacherError):
        _parse_json_object("definitely not json")


def test_coerce_label() -> None:
    assert _coerce_label("pos", ["neg", "pos"]) == "pos"
    assert _coerce_label("POS", ["neg", "pos"]) == "pos"
    assert _coerce_label("unknown", ["neg", "pos"]) == "neg"


def test_generation_mode() -> None:
    client = FakeLLMClient(mode="generate")
    builder = LLMDatasetBuilder(client, max_concurrency=1)
    rows, tokens = builder.build(
        _gen_config(num_samples=4),
        DatasetSpec(format=DatasetFormat.INLINE, inline_rows=[{"text": "x", "label": 0}]),
    )
    assert len(rows) <= 4
    assert all(r["label"] in {"neg", "pos"} for r in rows)
    assert tokens > 0
    assert client.calls


def test_generation_trims_to_num_samples() -> None:
    client = FakeLLMClient(mode="generate")
    builder = LLMDatasetBuilder(client, max_concurrency=2)
    rows, _ = builder.build(
        _gen_config(num_samples=2),
        DatasetSpec(format=DatasetFormat.INLINE, inline_rows=[{"text": "x", "label": 0}]),
    )
    assert len(rows) <= 2


def test_labelling_mode() -> None:
    client = FakeLLMClient(mode="labels")
    builder = LLMDatasetBuilder(client, max_concurrency=1)
    ds = DatasetSpec(
        format=DatasetFormat.INLINE,
        inline_rows=[{"text": "a", "label": 0}, {"text": "b", "label": 0}],
        label_names=["neg", "pos"],
    )
    rows, tokens = builder.build(_gen_config(label_existing=True, num_samples=2), ds)
    assert {r["label"] for r in rows} <= {"neg", "pos"}
    assert tokens > 0


def test_malformed_generation_raises() -> None:
    client = FakeLLMClient(mode="bad")
    builder = LLMDatasetBuilder(client, max_concurrency=1)
    with pytest.raises(TeacherError):
        builder.build(
            _gen_config(),
            DatasetSpec(format=DatasetFormat.INLINE, inline_rows=[{"text": "x", "label": 0}]),
        )


def test_build_llm_dataset_with_injected_client(monkeypatch) -> None:
    monkeypatch.setenv("DISTILLERY_LLM__MAX_CONCURRENCY", "1")
    from distillery.config.settings import get_settings

    get_settings.cache_clear()
    client = FakeLLMClient(mode="generate")
    rows, tokens = build_llm_dataset(
        _gen_config(num_samples=2),
        DatasetSpec(format=DatasetFormat.INLINE, inline_rows=[{"text": "x", "label": 0}]),
        client=client,
    )
    assert rows and tokens > 0
    get_settings.cache_clear()


def test_prompts_contain_labels_and_instructions() -> None:
    gen = build_generation_prompt(
        task_description="t",
        label="pos",
        all_labels=["neg", "pos"],
        count=3,
        seed_examples=[{"text": "great", "label": "pos"}],
    )
    assert "pos" in gen and "JSON" in gen and "great" in gen
    lab = build_labelling_prompt(task_description="t", texts=["a", "b"], all_labels=["neg", "pos"])
    assert "0." in lab and "1." in lab
