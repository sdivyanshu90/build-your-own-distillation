"""Model and device construction for the distillation engine.

This module is the single place that talks to ``transformers``. It builds a
:class:`ModelBundle` (model + tokenizer + shape metadata) from a
:class:`~distillery.domain.value_objects.ModelSpec`.

Two construction paths exist:

* **Pretrained** (default): load weights and tokenizer from the HuggingFace Hub
  or a local path via the ``Auto*`` factories.
* **Config-only** (``ModelSpec.config_only=True``): build a *small, randomly
  initialised* BERT classifier paired with a deterministic hashing tokenizer.
  This path performs **no network I/O**, making the entire engine runnable in
  CI and unit tests in milliseconds on CPU.

A deliberate, documented constraint of the response-/feature-based strategies is
that teacher and student **share a tokenizer / vocabulary** (the standard
distillation setup, e.g. DistilBERT ← BERT). The engine tokenises each batch
once with the student tokenizer and feeds both models, which makes logit and
hidden-state matching well-defined.
"""

from __future__ import annotations

import logging
import zlib
from dataclasses import dataclass
from typing import Any

import torch
from torch import nn

from distillery.domain.value_objects import ModelSpec

logger = logging.getLogger(__name__)

_DTYPES: dict[str, torch.dtype] = {
    "float32": torch.float32,
    "float16": torch.float16,
    "bfloat16": torch.bfloat16,
}


def resolve_device(preference: str = "auto") -> torch.device:
    """Resolve a device preference into a concrete :class:`torch.device`."""
    pref = (preference or "auto").lower()
    if pref == "cpu":
        return torch.device("cpu")
    if pref == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but not available")
        return torch.device("cuda")
    if pref == "mps":
        if not torch.backends.mps.is_available():
            raise RuntimeError("MPS requested but not available")
        return torch.device("mps")
    # auto
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def count_parameters(model: nn.Module, *, trainable_only: bool = False) -> int:
    """Total number of (optionally only trainable) parameters in a model."""
    return sum(p.numel() for p in model.parameters() if (p.requires_grad or not trainable_only))


@dataclass
class ModelBundle:
    """A model together with its tokenizer and shape metadata."""

    model: nn.Module
    tokenizer: Any
    num_labels: int
    hidden_size: int
    num_hidden_layers: int

    @property
    def num_parameters(self) -> int:
        return count_parameters(self.model)


class HashingTokenizer:
    """A tiny, deterministic, dependency-free tokenizer for offline/CI use.

    It maps whitespace tokens to ids in ``[0, vocab_size)`` via a stable hash.
    Its call signature is a compatible subset of a HuggingFace tokenizer, which
    lets the same data pipeline drive both the config-only and pretrained paths.
    """

    pad_token_id = 0
    cls_token_id = 1
    sep_token_id = 2

    def __init__(self, vocab_size: int = 1024) -> None:
        if vocab_size < 8:
            raise ValueError("vocab_size must be >= 8")
        self.vocab_size = vocab_size

    def _encode(self, text: str, max_length: int) -> list[int]:
        tokens = [self.cls_token_id]
        for word in str(text).lower().split():
            # Reserve 0..2 for special tokens. crc32 is a *stable* hash, so token
            # ids are deterministic across processes (unlike the salted built-in
            # hash()), which keeps runs reproducible.
            token_id = 3 + (zlib.crc32(word.encode("utf-8")) % (self.vocab_size - 3))
            tokens.append(token_id)
            if len(tokens) >= max_length - 1:
                break
        tokens.append(self.sep_token_id)
        return tokens[:max_length]

    def __call__(
        self,
        texts: list[str] | str,
        *,
        padding: bool | str = True,
        truncation: bool = True,
        max_length: int = 128,
        return_tensors: str | None = "pt",
    ) -> dict[str, torch.Tensor]:
        if isinstance(texts, str):
            texts = [texts]
        encoded = [self._encode(t, max_length) for t in texts]
        longest = max((len(e) for e in encoded), default=1)
        width = max_length if padding == "max_length" else longest
        input_ids = torch.full((len(encoded), width), self.pad_token_id, dtype=torch.long)
        attention_mask = torch.zeros((len(encoded), width), dtype=torch.long)
        for i, ids in enumerate(encoded):
            input_ids[i, : len(ids)] = torch.tensor(ids, dtype=torch.long)
            attention_mask[i, : len(ids)] = 1
        return {"input_ids": input_ids, "attention_mask": attention_mask}


def build_tiny_classifier(
    *,
    num_labels: int = 2,
    hidden_size: int = 32,
    num_hidden_layers: int = 2,
    num_attention_heads: int = 2,
    vocab_size: int = 1024,
    max_position_embeddings: int = 512,
) -> ModelBundle:
    """Build a small, randomly-initialised BERT classifier (no network I/O)."""
    from transformers import BertConfig, BertForSequenceClassification

    config = BertConfig(
        vocab_size=vocab_size,
        hidden_size=hidden_size,
        num_hidden_layers=num_hidden_layers,
        num_attention_heads=num_attention_heads,
        intermediate_size=hidden_size * 4,
        max_position_embeddings=max_position_embeddings,
        num_labels=num_labels,
        output_hidden_states=True,
    )
    model = BertForSequenceClassification(config)
    tokenizer = HashingTokenizer(vocab_size=vocab_size)
    return ModelBundle(
        model=model,
        tokenizer=tokenizer,
        num_labels=num_labels,
        hidden_size=hidden_size,
        num_hidden_layers=num_hidden_layers,
    )


def build_model(spec: ModelSpec) -> ModelBundle:
    """Construct a :class:`ModelBundle` from a :class:`ModelSpec`."""
    if spec.config_only:
        logger.info("Building config-only tiny classifier for %s", spec.name_or_path)
        return build_tiny_classifier(num_labels=spec.num_labels)
    return _build_pretrained(spec)


def _build_pretrained(spec: ModelSpec) -> ModelBundle:  # pragma: no cover
    """Load a pretrained model + tokenizer from the Hub (network; CD-tested)."""
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    logger.info("Loading pretrained model %s", spec.name_or_path)
    tokenizer = AutoTokenizer.from_pretrained(
        spec.name_or_path,
        revision=spec.revision,
        trust_remote_code=spec.trust_remote_code,
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        spec.name_or_path,
        num_labels=spec.num_labels,
        revision=spec.revision,
        trust_remote_code=spec.trust_remote_code,
        torch_dtype=_DTYPES.get(spec.dtype, torch.float32),
        output_hidden_states=True,
    )
    config = model.config
    return ModelBundle(
        model=model,
        tokenizer=tokenizer,
        num_labels=spec.num_labels,
        hidden_size=int(getattr(config, "hidden_size", 0)),
        num_hidden_layers=int(getattr(config, "num_hidden_layers", 0)),
    )
