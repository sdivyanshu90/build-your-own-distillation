"""The default distillation engine.

:class:`DefaultDistillationEngine` implements the
:class:`distillery.domain.ports.DistillationEngine` port. It wires together the
model/data/strategy/trainer/evaluation components into one orchestration:

1. resolve the device and build the student (and teacher, or LLM dataset);
2. tokenise data and construct dataloaders;
3. train the student with the configured strategy;
4. evaluate quality, fidelity, latency and compression;
5. serialise artifacts to ``work_dir`` and return their descriptors.

The engine is pure with respect to storage and persistence: it writes to a local
``work_dir`` and returns :class:`EngineArtifact` descriptors. The caller (worker
task) is responsible for uploading them to durable storage. This keeps the engine
trivially testable and free of infrastructure concerns.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

import torch

from distillery.core.data import build_datasets, make_dataloader
from distillery.core.evaluation import evaluate, student_accuracy
from distillery.core.models import ModelBundle, build_model, resolve_device
from distillery.core.strategies.registry import build_strategy
from distillery.core.trainer import DistillationTrainer
from distillery.domain.enums import ArtifactType, DatasetFormat, DistillationStrategy
from distillery.domain.exceptions import TrainingError
from distillery.domain.ports import EngineArtifact, EngineResult, ProgressCallback
from distillery.domain.value_objects import (
    DatasetSpec,
    DistillationConfig,
    LLMTeacherConfig,
    ResourceUsage,
)

logger = logging.getLogger(__name__)

# (rows, teacher_tokens_used)
LLMDatasetBuilder = Callable[[LLMTeacherConfig, DatasetSpec], tuple[list[dict], int]]


def _peak_memory_mb(device: torch.device) -> float:
    if device.type == "cuda":  # pragma: no cover - requires a GPU
        return round(float(torch.cuda.max_memory_allocated()) / 1e6, 2)
    try:
        import resource

        # ru_maxrss is kilobytes on Linux, bytes on macOS.
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(rss / 1024.0, 2)
    except Exception:  # pragma: no cover - platform dependent
        return 0.0


class DefaultDistillationEngine:
    """Reference implementation of the :class:`DistillationEngine` port."""

    def __init__(self, llm_dataset_builder: LLMDatasetBuilder | None = None) -> None:
        self._llm_dataset_builder = llm_dataset_builder

    def run(
        self,
        config: DistillationConfig,
        *,
        work_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> EngineResult:
        work_dir.mkdir(parents=True, exist_ok=True)
        device = resolve_device(config.device)
        if device.type == "cuda":  # pragma: no cover - requires a GPU
            torch.cuda.reset_peak_memory_stats()
        logger.info("Starting distillation on device=%s strategy=%s", device, config.strategy.value)
        started = time.perf_counter()
        teacher_tokens = 0

        # 1. Build student.
        student = build_model(config.student)

        # 2. Build teacher / dataset depending on strategy.
        teacher: ModelBundle | None = None
        dataset_spec = config.dataset
        if config.strategy is DistillationStrategy.LLM_TEACHER:
            dataset_spec, teacher_tokens = self._build_llm_dataset(config, work_dir)
        else:
            if config.teacher is None:  # pragma: no cover - guarded by config validation
                raise TrainingError("A teacher ModelSpec is required for this strategy")
            teacher = build_model(config.teacher)

        # 3. Data (always tokenised with the student tokenizer).
        bundle = build_datasets(dataset_spec, student.tokenizer, config.student.max_seq_length)
        train_loader = make_dataloader(
            bundle.train,
            batch_size=config.training.train_batch_size,
            shuffle=True,
            seed=config.training.seed,
        )
        eval_loader = None
        if bundle.eval is not None:
            eval_loader = make_dataloader(
                bundle.eval, batch_size=config.training.eval_batch_size, shuffle=False
            )

        # 4. Train.
        strategy = build_strategy(config.strategy, config.kd)
        trainer = DistillationTrainer(
            strategy,
            config.training,
            device,
            gradient_clip_norm=config.training.max_grad_norm,
            on_progress=on_progress,
        )
        epoch_eval = None
        if eval_loader is not None and config.training.early_stopping_patience:
            epoch_eval = lambda _epoch: student_accuracy(student, eval_loader, device)  # noqa: E731
        training_result = trainer.train(student, teacher, train_loader, epoch_eval=epoch_eval)

        # 5. Evaluate.
        evaluation_loader = eval_loader or train_loader
        report = evaluate(student, evaluation_loader, device, teacher=teacher)

        # 6. Serialise artifacts.
        artifacts = self._serialise(
            work_dir=work_dir,
            student=student,
            config=config,
            report_dict=report.model_dump(),
            history=training_result.history,
            synthetic_rows=(
                dataset_spec.inline_rows
                if config.strategy is DistillationStrategy.LLM_TEACHER
                else None
            ),
        )

        usage = ResourceUsage(
            duration_seconds=round(time.perf_counter() - started, 3),
            peak_memory_mb=_peak_memory_mb(device),
            device=str(device),
            teacher_tokens=teacher_tokens,
        )
        logger.info(
            "Distillation complete: accuracy=%.4f agreement=%.4f compression=%.2fx",
            report.primary_metric,
            report.teacher_agreement,
            report.compression.compression_ratio,
        )
        return EngineResult(evaluation=report, resource_usage=usage, artifacts=artifacts)

    # -- internals ---------------------------------------------------------
    def _build_llm_dataset(
        self, config: DistillationConfig, work_dir: Path
    ) -> tuple[DatasetSpec, int]:
        if config.llm is None:  # pragma: no cover - guarded by config validation
            raise TrainingError("LLM_TEACHER strategy requires an llm configuration")
        builder = self._llm_dataset_builder or self._default_llm_builder()
        rows, tokens = builder(config.llm, config.dataset)
        if not rows:
            raise TrainingError("LLM teacher produced an empty dataset")
        spec = DatasetSpec(
            format=DatasetFormat.INLINE,
            inline_rows=rows,
            text_column="text",
            label_column="label",
            label_names=config.llm.label_names,
            eval_split=None,
        )
        return spec, tokens

    @staticmethod
    def _default_llm_builder() -> LLMDatasetBuilder:
        from distillery.teachers.llm import build_llm_dataset

        return build_llm_dataset

    def _serialise(
        self,
        *,
        work_dir: Path,
        student: ModelBundle,
        config: DistillationConfig,
        report_dict: dict,
        history: list[dict],
        synthetic_rows: list[dict] | None,
    ) -> list[EngineArtifact]:
        artifacts: list[EngineArtifact] = []

        model_dir = work_dir / "student_model"
        model_dir.mkdir(parents=True, exist_ok=True)
        student.model.save_pretrained(model_dir)
        if hasattr(student.tokenizer, "save_pretrained"):
            student.tokenizer.save_pretrained(model_dir)
        artifacts.append(
            EngineArtifact(
                type=ArtifactType.STUDENT_MODEL,
                local_path=model_dir,
                metadata={"format": "huggingface"},
            )
        )

        report_path = work_dir / "evaluation_report.json"
        report_path.write_text(json.dumps(report_dict, indent=2, default=str), encoding="utf-8")
        artifacts.append(
            EngineArtifact(type=ArtifactType.EVALUATION_REPORT, local_path=report_path)
        )

        config_path = work_dir / "config_snapshot.json"
        config_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
        artifacts.append(EngineArtifact(type=ArtifactType.CONFIG_SNAPSHOT, local_path=config_path))

        log_path = work_dir / "training_log.json"
        log_path.write_text(json.dumps(history, indent=2, default=str), encoding="utf-8")
        artifacts.append(EngineArtifact(type=ArtifactType.TRAINING_LOG, local_path=log_path))

        if synthetic_rows is not None:
            ds_path = work_dir / "synthetic_dataset.jsonl"
            with ds_path.open("w", encoding="utf-8") as fh:
                for row in synthetic_rows:
                    fh.write(json.dumps(row, default=str) + "\n")
            artifacts.append(
                EngineArtifact(type=ArtifactType.SYNTHETIC_DATASET, local_path=ds_path)
            )

        return artifacts
