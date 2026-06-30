"""Prompt templates for LLM-teacher data distillation.

The prompts force the model to emit strict JSON so the output can be parsed
deterministically. Both generation (synthesising labelled examples) and
labelling (annotating provided texts) are supported.
"""

from __future__ import annotations

import json
from typing import Any

GENERATION_SYSTEM = (
    "You are a meticulous data-labelling expert generating a high-quality, "
    "diverse training dataset for a text-classification model. You always reply "
    "with strict, valid JSON and nothing else."
)

LABELLING_SYSTEM = (
    "You are a meticulous text classifier. You assign exactly one label from the "
    "allowed set to each input. You always reply with strict, valid JSON and "
    "nothing else."
)


def build_generation_prompt(
    *,
    task_description: str,
    label: str,
    all_labels: list[str],
    count: int,
    seed_examples: list[dict[str, Any]] | None = None,
) -> str:
    """Prompt asking the model to synthesise ``count`` examples for ``label``."""
    examples_block = ""
    if seed_examples:
        sample = [e for e in seed_examples if str(e.get("label")) == label][:3]
        if sample:
            examples_block = (
                "\nHere are reference examples for this label:\n"
                + "\n".join(f"- {e.get('text')}" for e in sample)
                + "\n"
            )
    return (
        f"Task: {task_description}\n"
        f"All possible labels: {json.dumps(all_labels)}\n"
        f"Generate {count} realistic, diverse training examples whose correct "
        f'label is exactly "{label}".'
        f"{examples_block}\n"
        "Vary length, tone, vocabulary and structure. Avoid duplicates and "
        "avoid trivially easy examples.\n"
        'Reply with JSON of the form: {"examples": ["text one", "text two", ...]}'
    )


def build_labelling_prompt(
    *,
    task_description: str,
    texts: list[str],
    all_labels: list[str],
) -> str:
    """Prompt asking the model to label a batch of provided texts."""
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(texts))
    return (
        f"Task: {task_description}\n"
        f"Allowed labels (use exactly one per item): {json.dumps(all_labels)}\n"
        "Classify each of the following numbered texts:\n"
        f"{numbered}\n\n"
        'Reply with JSON of the form: {"labels": [{"index": 0, "label": "..."}, ...]} '
        "covering every index exactly once."
    )
