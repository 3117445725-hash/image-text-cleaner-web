from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.config import DATA_DIR


@dataclass
class JobState:
    job_id: str
    status: str = "queued"
    message: str = "等待处理"
    progress: int = 0
    total_links: int = 0
    processed_links: int = 0
    matched_links: int = 0
    failed_links: int = 0
    changed_cells: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    output_file: str | None = None
    log_file: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "JobState":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in payload.items() if key in allowed})


class JobStore:
    """Thread-safe job state store with lightweight on-disk persistence."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = Lock()
        self._data_dir = data_dir

    def _state_path(self, job_id: str) -> Path:
        return self._data_dir / job_id / "job.json"

    def _persist(self, job: JobState) -> None:
        path = self._state_path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(path)

    def _load(self, job_id: str) -> JobState | None:
        path = self._state_path(job_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return JobState.from_dict(payload)
        except (OSError, ValueError, TypeError):
            return None

    def create(self, job_id: str) -> JobState:
        with self._lock:
            job = JobState(job_id=job_id)
            self._jobs[job_id] = job
            self._persist(job)
            return job

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return job
            job = self._load(job_id)
            if job is not None:
                self._jobs[job_id] = job
            return job

    def update(self, job_id: str, **changes: Any) -> JobState:
        with self._lock:
            job = self._jobs.get(job_id) or self._load(job_id)
            if job is None:
                raise KeyError(job_id)
            for key, value in changes.items():
                if key not in JobState.__dataclass_fields__:
                    raise AttributeError(f"未知任务字段：{key}")
                setattr(job, key, value)
            job.updated_at = datetime.now(timezone.utc).isoformat()
            self._jobs[job_id] = job
            self._persist(job)
            return job

    def recover_interrupted(self) -> int:
        """Mark queued/running jobs as failed after a service restart."""
        recovered = 0
        for path in self._data_dir.iterdir():
            if not path.is_dir():
                continue
            job = self._load(path.name)
            if job and job.status in {"queued", "running"}:
                job.status = "failed"
                job.message = "任务因服务重启而中断"
                job.error = "服务在任务执行期间发生重启，请重新提交该文件。"
                job.updated_at = datetime.now(timezone.utc).isoformat()
                with self._lock:
                    self._jobs[job.job_id] = job
                    self._persist(job)
                recovered += 1
        return recovered

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)


job_store = JobStore()
