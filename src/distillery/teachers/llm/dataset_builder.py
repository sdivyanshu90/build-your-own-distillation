"""Build a training corpus from an LLM teacher (generation or labelling).

Two modes, selected by :attr:`LLMTeacherConfig.label_existing`:

* **Generation** — synthesise ``num_samples`` labelled examples spread across the
  configured labels.
* **Labelling** — annotate an existing (unlabelled) dataset with the LLM.

Both modes fan out requests over a bounded thread pool, parse strict-JSON
responses defensively, and report the total teacher tokens consumed.
"""

from __future__ import annotations

import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from distillery.config.settings import get_settings
from distillery.domain.exceptions import TeacherError
from distillery.domain.value_objects import DatasetSpec, LLMTeacherConfig
from distillery.teachers.llm.base import LLMClient
from distillery.teachers.llm.prompts import (
    GENERATION_SYSTEM,
    LABELLING_SYSTEM,
    build_generation_prompt,
    build_labelling_prompt,
)

logger = logging.getLogger(__name__)

_GEN_BATCH = 20
_LABEL_BATCH = 20
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json_object(text: str) -> dict[str, Any]:
    """Extract and parse the first JSON object from a model response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned[cleaned.find("{") :] if "{" in cleaned else cleaned
    try:
        return cast("dict[str, Any]", json.loads(cleaned))
    except json.JSONDecodeError:
        match = _JSON_RE.search(text)
        if not match:
            raise TeacherError("LLM response did not contain valid JSON") from None
        try:
            return cast("dict[str, Any]", json.loads(match.group(0)))
        except json.JSONDecodeError as exc:
            raise TeacherError("LLM response contained malformed JSON") from exc


def _coerce_label(raw: str, label_names: list[str]) -> str:
    """Map a returned label to the closest allowed label (case-insensitive)."""
    if raw in label_names:
        return raw
    lowered = {name.lower(): name for name in label_names}
    return lowered.get(str(raw).strip().lower(), label_names[0])


class LLMDatasetBuilder:
    """Orchestrates LLM calls to produce a labelled training corpus."""

    def __init__(self, client: LLMClient, *, max_concurrency: int = 4) -> None:
        self._client = client
        self._max_concurrency = max(1, max_concurrency)

    def build(
        self, llm_config: LLMTeacherConfig, dataset_spec: DatasetSpec
    ) -> tuple[list[dict[str, Any]], int]:
        if llm_config.label_existing:
            return self._label(llm_config, dataset_spec)
        return self._generate(llm_config)

    # -- generation --------------------------------------------------------
    def _generate(self, cfg: LLMTeacherConfig) -> tuple[list[dict[str, Any]], int]:
        per_label = math.ceil(cfg.num_samples / len(cfg.label_names))
        tasks: list[tuple[str, int]] = []
        for label in cfg.label_names:
            remaining = per_label
            while remaining > 0:
                batch = min(_GEN_BATCH, remaining)
                tasks.append((label, batch))
                remaining -= batch

        rows: list[dict[str, Any]] = []
        total_tokens = 0
        for partial_rows, tokens in self._map(self._generate_one, tasks, cfg):
            rows.extend(partial_rows)
            total_tokens += tokens

        if not rows:
            raise TeacherError("LLM generation produced no usable examples")
        return rows[: cfg.num_samples], total_tokens

    def _generate_one(
        self, task: tuple[str, int], cfg: LLMTeacherConfig
    ) -> tuple[list[dict[str, Any]], int]:
        label, count = task
        prompt = build_generation_prompt(
            task_description=cfg.task_description,
            label=label,
            all_labels=cfg.label_names,
            count=count,
            seed_examples=cfg.seed_examples,
        )
        response = self._client.complete(
            system=GENERATION_SYSTEM,
            prompt=prompt,
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
        )
        payload = _parse_json_object(response.text)
        examples = payload.get("examples", [])
        rows = [{"text": str(t), "label": label} for t in examples if str(t).strip()]
        return rows, response.total_tokens

    # -- labelling ---------------------------------------------------------
    def _label(
        self, cfg: LLMTeacherConfig, dataset_spec: DatasetSpec
    ) -> tuple[list[dict[str, Any]], int]:
        from distillery.core.data import load_texts

        texts = load_texts(dataset_spec)[: cfg.num_samples]
        if not texts:
            raise TeacherError("No texts found to label")
        batches = [texts[i : i + _LABEL_BATCH] for i in range(0, len(texts), _LABEL_BATCH)]

        rows: list[dict[str, Any]] = []
        total_tokens = 0
        for partial_rows, tokens in self._map(self._label_one, batches, cfg):
            rows.extend(partial_rows)
            total_tokens += tokens
        return rows, total_tokens

    def _label_one(
        self, batch: list[str], cfg: LLMTeacherConfig
    ) -> tuple[list[dict[str, Any]], int]:
        prompt = build_labelling_prompt(
            task_description=cfg.task_description,
            texts=batch,
            all_labels=cfg.label_names,
        )
        response = self._client.complete(
            system=LABELLING_SYSTEM,
            prompt=prompt,
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            temperature=0.0,
        )
        payload = _parse_json_object(response.text)
        annotations = {int(item["index"]): item["label"] for item in payload.get("labels", [])}
        rows: list[dict[str, Any]] = []
        for idx, text in enumerate(batch):
            if idx in annotations:
                rows.append(
                    {"text": text, "label": _coerce_label(str(annotations[idx]), cfg.label_names)}
                )
        return rows, response.total_tokens

    # -- concurrency helper ------------------------------------------------
    def _map(self, fn: Any, items: list[Any], cfg: LLMTeacherConfig) -> list[Any]:
        if self._max_concurrency == 1 or len(items) <= 1:
            return [fn(item, cfg) for item in items]
        with ThreadPoolExecutor(max_workers=self._max_concurrency) as pool:
            return list(pool.map(lambda item: fn(item, cfg), items))


def build_llm_dataset(
    llm_config: LLMTeacherConfig,
    dataset_spec: DatasetSpec,
    client: LLMClient | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Convenience entry point used by the engine (constructs the default client)."""
    if client is None:
        from distillery.teachers.llm.anthropic_client import AnthropicLLMClient

        client = AnthropicLLMClient.from_settings()
    settings = get_settings()
    builder = LLMDatasetBuilder(client, max_concurrency=settings.llm.max_concurrency)
    return builder.build(llm_config, dataset_spec)
