# ADR-0002: Pluggable Distillation Strategies via Strategy Pattern + Registry

## Status

Accepted

## Date

2026-01-15

## Context

Knowledge distillation is not a single algorithm. Distillery needs to support
several distinct approaches, and we expect to add more over time. If the trainer
hard-codes a particular loss formulation, every new method forces edits to the
training loop, increasing the risk of regressions in already-shipped strategies.
We want to add new distillation methods without modifying the trainer or engine.

## Decision

We model each distillation method as a Strategy behind a common interface and
select it through a registry. There are three strategies today:

- **response_based**: classic Hinton soft-target knowledge distillation,
  combining `alpha * T^2 * KL` (teacher/student soft targets at temperature `T`)
  with `(1 - alpha) * CE` (hard-label cross-entropy).
- **feature_based**: response-based KD plus a hidden-state MSE term using
  learnable projections to align teacher and student representations.
- **llm_teacher**: an LLM generates and/or labels data, which is then used for
  supervised fine-tuning of the student.

Each strategy implements `DistillationStrategy.compute_loss`. A registry maps
the strategy enum to a factory, so new strategies are registered without
touching the trainer or engine (Open/Closed Principle). The trainer is
strategy-agnostic: it drives the loop and delegates the loss to the selected
strategy.

A documented constraint applies to `response_based` and `feature_based`: the
teacher and student must share the same tokenizer/vocabulary and have an equal
`num_labels` (the standard DistilBERT-from-BERT setup). In practice we tokenise
once with the student tokenizer and feed the same inputs to both models.

## Consequences

### Positive

- New distillation methods are additive: register a factory, implement the loss.
- The trainer stays simple and stable, reducing regression risk.
- Each strategy is independently testable.

### Negative

- The shared `compute_loss` interface must accommodate differing strategy needs
  (e.g. hidden states for feature-based KD).
- The tokenizer/vocab and `num_labels` constraint limits which teacher/student
  pairs work for response/feature strategies.

### Mitigations

- Keep the interface focused and document the shared-tokenizer constraint
  prominently; the `llm_teacher` strategy covers heterogeneous-model cases.

## Alternatives considered

- **A single configurable loss function** with flags: collapses unrelated
  concerns into one branchy function that is hard to test and extend.
- **Subclassing the trainer per method**: couples training orchestration to the
  loss formulation and duplicates loop code across methods.
