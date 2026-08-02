from __future__ import annotations

import logging
import os
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable, Protocol

from paper_agent.config import Settings, load_settings
from paper_agent.pipeline import PipelineProgress, PipelineRunFailed, run_pipeline
from paper_agent.web.api_models import RunProgress
from paper_agent.web.artifacts import ArtifactReader
from paper_agent.web.registry import RegistryRun, RunRegistry


class PipelineRunner(Protocol):
    def __call__(self, question: str, **kwargs: object) -> object: ...


class SingleRunExecutor:
    def __init__(
        self,
        registry: RunRegistry,
        artifacts: ArtifactReader,
        output_root: Path,
        *,
        runner: PipelineRunner = run_pipeline,
        settings_loader: Callable[[], Settings] = load_settings,
    ) -> None:
        self.registry = registry
        self.artifacts = artifacts
        self.output_root = output_root
        self.runner = runner
        self.settings_loader = settings_loader
        self.available = False
        self._stop = False
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._logger = logging.getLogger("paper_agent.web.execution")
        self._lock_path = registry.path.parent / "server.lock"
        self._lock_fd: int | None = None

    def start(self) -> None:
        try:
            self._acquire_lock()
            self.reconcile_startup()
            self.available = True
            self._thread = threading.Thread(target=self._work, name="paper-agent-runner", daemon=True)
            self._thread.start()
        except Exception:
            self._release_lock()
            raise

    def close(self) -> None:
        self.available = False
        with self._condition:
            self._stop = True
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._release_lock()

    def _release_lock(self) -> None:
        if self._lock_fd is not None:
            os.lseek(self._lock_fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._lock_fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None

    def _acquire_lock(self) -> None:
        lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR)
        try:
            if os.fstat(lock_fd).st_size == 0:
                os.write(lock_fd, b"0")
            os.lseek(lock_fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            os.close(lock_fd)
            raise
        self._lock_fd = lock_fd

    def notify(self) -> None:
        with self._condition:
            self._condition.notify()

    def reconcile_startup(self) -> None:
        for row in self.registry.active():
            manifest = None
            if row.artifact_run_id:
                try:
                    manifest = self.artifacts.manifest(row.origin, row.artifact_run_id)
                except Exception:
                    manifest = None
            if manifest is not None and manifest.status != "running":
                self.registry.terminal(row.id, manifest.status, finished_at=manifest.finished_at)
            else:
                self.registry.terminal(
                    row.id, "interrupted",
                    error={"stage": "initializing", "code": "web_process_interrupted"},
                )

    def _work(self) -> None:
        while True:
            with self._condition:
                if self._stop:
                    return
            row = self.registry.claim_oldest()
            if row is None:
                with self._condition:
                    self._condition.wait(timeout=1)
                continue
            self._execute(row)

    def _execute(self, row: RegistryRun) -> None:
        request = row.request
        artifact_seen = False

        def artifact_created(artifact_run_id: str) -> None:
            nonlocal artifact_seen
            self.registry.set_artifact_id(row.id, artifact_run_id)
            artifact_seen = True

        def progress(event: PipelineProgress) -> None:
            self.registry.update_progress(
                row.id, event.phase,
                RunProgress(
                    completed_units=event.completed_units,
                    total_units=event.total_units,
                    paper_id=event.paper_id,
                ),
            )

        try:
            base = self.settings_loader()
            settings = replace(
                base,
                retrieval_mode=request.retrieval.mode,
                retrieval_candidate_k=request.retrieval.candidate_k,
                retrieval_top_k=request.retrieval.top_k,
                retrieval_rrf_k=request.retrieval.rrf_k,
                analysis_evidence_per_paper=request.retrieval.analysis_evidence_per_paper,
            )
            self.runner(
                request.question,
                output_base=self.output_root,
                limit=request.paper_limit,
                no_pdf=request.content_mode == "abstract_only",
                settings=settings,
                progress_sink=progress,
                artifact_created_sink=artifact_created,
            )
        except PipelineRunFailed:
            pass
        except Exception:
            self._logger.error("run execution failed", extra={"api_run_id": row.id})
            if not artifact_seen:
                self.registry.terminal(
                    row.id, "failed",
                    error={"stage": "initializing", "code": "execution_initialization_failed"},
                )
                return
        current = self.registry.get(row.id)
        if current.artifact_run_id:
            try:
                manifest = self.artifacts.manifest(current.origin, current.artifact_run_id)
            except Exception:
                manifest = None
            if manifest is not None and manifest.status != "running":
                self.registry.terminal(row.id, manifest.status, finished_at=manifest.finished_at)
                return
        self.registry.terminal(
            row.id, "interrupted",
            error={"stage": "pipeline", "code": "pipeline_terminated_without_manifest"},
        )
