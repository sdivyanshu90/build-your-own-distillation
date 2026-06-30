"""Dataset loading, label resolution and tokenisation.

Turns a :class:`~distillery.domain.value_objects.DatasetSpec` into ready-to-train
PyTorch ``DataLoader`` objects. Four source formats are supported (inline rows,
JSONL, CSV, and HuggingFace Hub datasets). Labels may be integers or strings;
strings are mapped to indices via the spec's ``label_names`` (or inferred and
sorted for determinism).

Tokenisation uses the *student* tokenizer for both models — see the constraint
documented in :mod:`distillery.core.models`.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import DataLoader, Dataset

from distillery.domain.enums import DatasetFormat
from distillery.domain.exceptions import ValidationError
from distillery.domain.value_objects import DatasetSpec

logger = logging.getLogger(__name__)


class TokenizedDataset(Dataset):
    """An in-memory tensor dataset of tokenised classification examples."""

    def __init__(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        labels: torch.Tensor,
    ) -> None:
        if not (len(input_ids) == len(attention_mask) == len(labels)):
            raise ValueError("input_ids, attention_mask and labels must align")
        self.input_ids = input_ids
        self.attention_mask = attention_mask
        self.labels = labels

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        return {
            "input_ids": self.input_ids[index],
            "attention_mask": self.attention_mask[index],
            "labels": self.labels[index],
        }


@dataclass
class DatasetBundle:
    """Train/eval datasets plus resolved label metadata."""

    train: TokenizedDataset
    eval: TokenizedDataset | None
    label_names: list[str]
    num_labels: int


def _read_inline(
    rows: list[dict[str, Any]], text_col: str, label_col: str
) -> tuple[list[str], list[Any]]:
    texts = [str(r[text_col]) for r in rows]
    labels = [r[label_col] for r in rows]
    return texts, labels


def _read_jsonl(path: Path, text_col: str, label_col: str) -> tuple[list[str], list[Any]]:
    texts: list[str] = []
    labels: list[Any] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            obj = json.loads(line)
            texts.append(str(obj[text_col]))
            labels.append(obj[label_col])
    return texts, labels


def _read_csv(path: Path, text_col: str, label_col: str) -> tuple[list[str], list[Any]]:
    texts: list[str] = []
    labels: list[Any] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            texts.append(str(row[text_col]))
            labels.append(row[label_col])
    return texts, labels


def _read_hf_hub(  # pragma: no cover - network path, exercised by integration/CD
    reference: str, split: str, text_col: str, label_col: str
) -> tuple[list[str], list[Any]]:
    from datasets import load_dataset  # local import: heavy, prod-only path

    ds = load_dataset(reference, split=split)
    return [str(x) for x in ds[text_col]], list(ds[label_col])


def _load_split(spec: DatasetSpec, split: str) -> tuple[list[str], list[Any]] | None:
    """Load (texts, labels) for a given split, or ``None`` if unavailable."""
    if spec.format is DatasetFormat.INLINE:
        if split == spec.train_split:
            return _read_inline(spec.inline_rows, spec.text_column, spec.label_column)
        # Inline datasets reuse their rows for evaluation (overfit sanity check).
        return _read_inline(spec.inline_rows, spec.text_column, spec.label_column)

    if spec.format is DatasetFormat.JSONL:
        return _read_jsonl(Path(spec.reference or ""), spec.text_column, spec.label_column)
    if spec.format is DatasetFormat.CSV:
        return _read_csv(Path(spec.reference or ""), spec.text_column, spec.label_column)
    if spec.format is DatasetFormat.HF_HUB:  # pragma: no cover - network path
        try:
            return _read_hf_hub(spec.reference or "", split, spec.text_column, spec.label_column)
        except Exception as exc:
            if split == spec.eval_split:
                logger.warning("Eval split %s unavailable: %s", split, exc)
                return None
            raise
    raise ValidationError(f"Unsupported dataset format: {spec.format}")


def _resolve_labels(raw_labels: list[Any], label_names: list[str]) -> tuple[list[int], list[str]]:
    """Map raw labels to contiguous integer ids and return the name table."""
    if label_names:
        name_to_idx = {name: i for i, name in enumerate(label_names)}
        resolved: list[int] = []
        for label in raw_labels:
            if isinstance(label, str):
                if label not in name_to_idx:
                    raise ValidationError(f"Unknown label '{label}' not in label_names")
                resolved.append(name_to_idx[label])
            else:
                resolved.append(int(label))
        return resolved, list(label_names)

    # Infer a deterministic label table.
    if all(isinstance(label, int | float) and not isinstance(label, bool) for label in raw_labels):
        ints = [int(label) for label in raw_labels]
        names = [str(i) for i in range(max(ints) + 1)] if ints else []
        return ints, names

    unique = sorted({str(label) for label in raw_labels})
    name_to_idx = {name: i for i, name in enumerate(unique)}
    return [name_to_idx[str(label)] for label in raw_labels], unique


def _tokenize(
    texts: list[str], labels: list[int], tokenizer: Any, max_seq_length: int
) -> TokenizedDataset:
    encoded = tokenizer(
        texts,
        padding="max_length",
        truncation=True,
        max_length=max_seq_length,
        return_tensors="pt",
    )
    return TokenizedDataset(
        input_ids=encoded["input_ids"],
        attention_mask=encoded["attention_mask"],
        labels=torch.tensor(labels, dtype=torch.long),
    )


def build_datasets(spec: DatasetSpec, tokenizer: Any, max_seq_length: int) -> DatasetBundle:
    """Build tokenised train/eval datasets and resolve the label table."""
    train_raw = _load_split(spec, spec.train_split)
    if train_raw is None:
        raise ValidationError("Training split could not be loaded")
    train_texts, train_labels_raw = train_raw

    if spec.max_train_samples:
        train_texts = train_texts[: spec.max_train_samples]
        train_labels_raw = train_labels_raw[: spec.max_train_samples]

    train_labels, label_names = _resolve_labels(train_labels_raw, spec.label_names)
    if not train_texts:
        raise ValidationError("Training dataset is empty")

    train_ds = _tokenize(train_texts, train_labels, tokenizer, max_seq_length)

    eval_ds: TokenizedDataset | None = None
    if spec.eval_split:
        eval_raw = _load_split(spec, spec.eval_split)
        if eval_raw is not None:
            eval_texts, eval_labels_raw = eval_raw
            if spec.max_eval_samples:
                eval_texts = eval_texts[: spec.max_eval_samples]
                eval_labels_raw = eval_labels_raw[: spec.max_eval_samples]
            eval_labels, _ = _resolve_labels(eval_labels_raw, label_names)
            eval_ds = _tokenize(eval_texts, eval_labels, tokenizer, max_seq_length)

    num_labels = max(len(label_names), max(train_labels) + 1 if train_labels else 1)
    return DatasetBundle(
        train=train_ds, eval=eval_ds, label_names=label_names, num_labels=num_labels
    )


def load_texts(spec: DatasetSpec, split: str | None = None) -> list[str]:
    """Load only the text column for a split (used by LLM labelling)."""
    loaded = _load_split(spec, split or spec.train_split)
    if loaded is None:
        return []
    return loaded[0]


def make_dataloader(
    dataset: TokenizedDataset,
    *,
    batch_size: int,
    shuffle: bool,
    seed: int = 42,
    num_workers: int = 0,
) -> DataLoader:
    """Create a deterministic DataLoader (seeded generator for reproducibility)."""
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        generator=generator if shuffle else None,
        drop_last=False,
    )
