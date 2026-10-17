from pathlib import Path
from typing import Any

from pydantic import BaseModel

from terminal_bench.dataset.dataset import Dataset


class DatasetLock(BaseModel):
    name: str | None = None
    version: str | None = None
    local_path: str | None = None
    registry_url: str | None = None
    local_registry_path: str | None = None
    task_ids: list[str]

    @classmethod
    def from_dataset(cls, dataset: Dataset) -> "DatasetLock":
        config = dataset.config
        return cls(
            name=config.name,
            version=config.version,
            local_path=str(config.path.absolute()) if config.path else None,
            registry_url=config.registry_url,
            local_registry_path=(
                str(config.local_registry_path) if config.local_registry_path else None
            ),
            task_ids=sorted(dataset.task_ids),
        )


class AgentLock(BaseModel):
    name: str
    model_name: str | None = None
    import_path: str
    extra_kwargs: dict[str, Any] | None = None


class RunConfigLock(BaseModel):
    log_level: str
    livestream: bool
    n_concurrent_trials: int
    n_attempts: int
    no_rebuild: bool
    cleanup: bool
    global_timeout_multiplier: float
    global_agent_timeout_sec: float | None = None
    global_test_timeout_sec: float | None = None


class LocalConfig(BaseModel):
    output_path: Path
    run_id: str
    upload_results: bool


class RunLock(BaseModel):
    """Snapshot of a run's configuration, used to validate resumes."""

    dataset: DatasetLock
    agent: AgentLock
    run_config: RunConfigLock
    local_config: LocalConfig

    def to_json(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=4))

    @classmethod
    def from_json(cls, path: Path) -> "RunLock":
        return cls.model_validate_json(path.read_text())
