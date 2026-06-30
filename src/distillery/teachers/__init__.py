"""Teacher integrations.

Two kinds of teacher supply supervision:

* **HuggingFace teachers** are ordinary transformer models loaded by
  :mod:`distillery.core.models`; the engine uses their logits/hidden states
  directly, so no extra adapter is needed here.
* **LLM teachers** (this package's :mod:`distillery.teachers.llm`) call a hosted
  large language model to *generate* or *label* a training corpus for the
  data-distillation strategy.
"""

from __future__ import annotations

__all__: list[str] = []
