"""Environment-driven settings shared by the API and the runner."""

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class ResourceClass:
    cpu_request: str
    memory_request: str
    cpu_limit: float
    memory_limit: str


RESOURCE_CLASSES = {
    "small": ResourceClass("250m", "512Mi", 1.0, "1g"),
    "medium": ResourceClass("500m", "1Gi", 2.0, "2g"),
    "large": ResourceClass("1", "2Gi", 4.0, "4g"),
}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.environ.get("AQ_DATA_DIR", REPO_ROOT / "data")).resolve()
    namespace: str = os.environ.get("AQ_NAMESPACE", "default")
    agent: str = os.environ.get("AQ_AGENT", "terminus-1")
    model: str = os.environ.get("AQ_MODEL", "openrouter/anthropic/claude-opus-4.5")
    default_attempts: int = int(os.environ.get("AQ_DEFAULT_ATTEMPTS", "1"))
    max_attempts: int = int(os.environ.get("AQ_MAX_ATTEMPTS", "10"))
    max_concurrent_submissions: int = int(os.environ.get("AQ_MAX_CONCURRENT_SUBMISSIONS", "16"))
    max_concurrent_builds: int = int(os.environ.get("AQ_MAX_CONCURRENT_BUILDS", "4"))
    max_upload_bytes: int = int(os.environ.get("AQ_MAX_UPLOAD_BYTES", str(50 * 1024**2)))
    max_extracted_bytes: int = int(os.environ.get("AQ_MAX_EXTRACTED_BYTES", str(500 * 1024**2)))
    build_timeout_sec: int = int(os.environ.get("AQ_BUILD_TIMEOUT_SEC", "1800"))
    attempt_overhead_sec: int = int(os.environ.get("AQ_ATTEMPT_OVERHEAD_SEC", "600"))
    retries_per_attempt: int = int(os.environ.get("AQ_RETRIES_PER_ATTEMPT", "1"))
    poll_interval_sec: float = float(os.environ.get("AQ_POLL_INTERVAL_SEC", "5"))
    adaptive_max_wave: int = int(os.environ.get("AQ_ADAPTIVE_MAX_WAVE", "10"))
    adaptive_extra_launches: int = int(os.environ.get("AQ_ADAPTIVE_EXTRA_LAUNCHES", "3"))
    # Claude Opus 4.5 list price; token counts come from terminal-bench's tokenizer
    # estimates and ignore prompt caching, so dollar figures are approximate.
    price_input_per_mtok: float = float(os.environ.get("AQ_PRICE_INPUT_PER_MTOK", "5.0"))
    price_output_per_mtok: float = float(os.environ.get("AQ_PRICE_OUTPUT_PER_MTOK", "25.0"))
    # Docker Desktop's daemon sees the macOS filesystem under /host_mnt; pods bind
    # host paths through it when starting sibling task containers.
    host_path_prefix: str = os.environ.get("AQ_HOST_PATH_PREFIX", "/host_mnt")
    llm_secret_name: str = "aq-llm-credentials"
    llm_secret_keys: tuple[str, ...] = field(default=("OPENROUTER_API_KEY",))

    @property
    def submissions_dir(self) -> Path:
        return self.data_dir / "submissions"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "executor.db"


settings = Settings()
