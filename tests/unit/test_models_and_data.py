"""Unit tests for model construction, tokenisation and the data pipeline."""

from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch")

from distillery.core.data import (  # noqa: E402
    TokenizedDataset,
    _resolve_labels,
    build_datasets,
    load_texts,
    make_dataloader,
)
from distillery.core.models import (  # noqa: E402
    HashingTokenizer,
    build_model,
    build_tiny_classifier,
    count_parameters,
    resolve_device,
)
from distillery.domain.enums import DatasetFormat  # noqa: E402
from distillery.domain.exceptions import ValidationError  # noqa: E402
from distillery.domain.value_objects import DatasetSpec, ModelSpec  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.ml]


# -- tokenizer ---------------------------------------------------------------
def test_hashing_tokenizer_deterministic() -> None:
    tok = HashingTokenizer(vocab_size=64)
    a = tok(["hello world"], max_length=8)
    b = tok(["hello world"], max_length=8)
    assert torch.equal(a["input_ids"], b["input_ids"])
    assert a["input_ids"][0, 0].item() == HashingTokenizer.cls_token_id


def test_hashing_tokenizer_padding_and_mask() -> None:
    tok = HashingTokenizer(vocab_size=64)
    out = tok(["a b c", "single"], padding="max_length", max_length=10)
    assert out["input_ids"].shape == (2, 10)
    assert out["attention_mask"].sum().item() > 0
    assert set(out["attention_mask"].unique().tolist()) <= {0, 1}


def test_hashing_tokenizer_truncation() -> None:
    tok = HashingTokenizer(vocab_size=64)
    out = tok([" ".join(["w"] * 100)], max_length=12)
    assert out["input_ids"].shape[1] == 12


def test_hashing_tokenizer_rejects_tiny_vocab() -> None:
    with pytest.raises(ValueError):
        HashingTokenizer(vocab_size=4)


# -- models ------------------------------------------------------------------
def test_build_tiny_classifier() -> None:
    bundle = build_tiny_classifier(num_labels=3, hidden_size=16, num_hidden_layers=2)
    assert bundle.num_labels == 3
    assert bundle.hidden_size == 16
    assert bundle.num_hidden_layers == 2
    assert bundle.num_parameters > 0
    out = bundle.model(**bundle.tokenizer(["hi there"], max_length=8), output_hidden_states=True)
    assert out.logits.shape == (1, 3)
    assert len(out.hidden_states) == 3  # embeddings + 2 layers


def test_build_model_config_only() -> None:
    bundle = build_model(ModelSpec(name_or_path="x", num_labels=2, config_only=True))
    assert bundle.num_labels == 2
    assert isinstance(bundle.tokenizer, HashingTokenizer)


def test_count_parameters_trainable_filter() -> None:
    bundle = build_tiny_classifier(num_labels=2)
    total = count_parameters(bundle.model)
    for p in bundle.model.parameters():
        p.requires_grad_(False)
    assert count_parameters(bundle.model, trainable_only=True) == 0
    assert count_parameters(bundle.model) == total


def test_resolve_device() -> None:
    assert resolve_device("cpu").type == "cpu"
    assert resolve_device("auto").type in {"cpu", "cuda", "mps"}
    with pytest.raises(RuntimeError):
        resolve_device("mps")  # unavailable on Linux CI


# -- data --------------------------------------------------------------------
def test_resolve_labels_integers() -> None:
    labels, names = _resolve_labels([0, 1, 1, 0], [])
    assert labels == [0, 1, 1, 0]
    assert names == ["0", "1"]


def test_resolve_labels_strings_inferred() -> None:
    labels, names = _resolve_labels(["pos", "neg", "pos"], [])
    assert names == ["neg", "pos"]
    assert labels == [1, 0, 1]


def test_resolve_labels_with_names() -> None:
    labels, names = _resolve_labels(["pos", "neg"], ["neg", "pos"])
    assert labels == [1, 0]
    assert names == ["neg", "pos"]


def test_resolve_labels_unknown_raises() -> None:
    with pytest.raises(ValidationError):
        _resolve_labels(["maybe"], ["neg", "pos"])


def test_tokenized_dataset_alignment() -> None:
    with pytest.raises(ValueError):
        TokenizedDataset(torch.zeros(2, 3), torch.zeros(2, 3), torch.zeros(1))


def test_build_datasets_inline_and_loader() -> None:
    rows = [{"text": f"x {i}", "label": i % 2} for i in range(10)]
    spec = DatasetSpec(format=DatasetFormat.INLINE, inline_rows=rows, label_names=["a", "b"])
    tok = HashingTokenizer(vocab_size=64)
    bundle = build_datasets(spec, tok, max_seq_length=8)
    assert len(bundle.train) == 10
    assert bundle.num_labels == 2
    loader = make_dataloader(bundle.train, batch_size=4, shuffle=True, seed=1)
    batch = next(iter(loader))
    assert batch["input_ids"].shape[0] == 4
    assert {"input_ids", "attention_mask", "labels"} <= set(batch)


def test_inline_provides_eval_split_and_no_shuffle() -> None:
    rows = [{"text": f"x {i}", "label": i % 2} for i in range(6)]
    spec = DatasetSpec(format=DatasetFormat.INLINE, inline_rows=rows, label_names=["a", "b"])
    tok = HashingTokenizer(vocab_size=64)
    bundle = build_datasets(spec, tok, max_seq_length=8)
    assert bundle.eval is not None  # inline reuses rows for evaluation
    loader = make_dataloader(bundle.eval, batch_size=3, shuffle=False)
    assert next(iter(loader))["input_ids"].shape[0] == 3
    assert load_texts(spec) == [r["text"] for r in rows]


def test_build_datasets_respects_sample_caps() -> None:
    rows = [{"text": f"x {i}", "label": i % 2} for i in range(20)]
    spec = DatasetSpec(
        format=DatasetFormat.INLINE, inline_rows=rows, label_names=["a", "b"], max_train_samples=5
    )
    bundle = build_datasets(spec, HashingTokenizer(vocab_size=64), max_seq_length=8)
    assert len(bundle.train) == 5


def test_jsonl_and_csv_loading(tmp_path) -> None:
    jsonl = tmp_path / "d.jsonl"
    jsonl.write_text(
        "\n".join(json.dumps({"text": f"t{i}", "label": i % 2}) for i in range(4)),
        encoding="utf-8",
    )
    spec = DatasetSpec(
        format=DatasetFormat.JSONL, reference=str(jsonl), label_names=["a", "b"], eval_split=None
    )
    assert load_texts(spec) == ["t0", "t1", "t2", "t3"]

    csv = tmp_path / "d.csv"
    csv.write_text("text,label\nhello,a\nworld,b\n", encoding="utf-8")
    spec_csv = DatasetSpec(
        format=DatasetFormat.CSV, reference=str(csv), label_names=["a", "b"], eval_split=None
    )
    bundle = build_datasets(spec_csv, HashingTokenizer(vocab_size=64), max_seq_length=8)
    assert len(bundle.train) == 2
