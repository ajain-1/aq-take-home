"""Environment-driven settings shared by the API and the runner."""

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


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

# Agent name -> whether it calls an LLM (and so needs a model and credentials).
AGENTS = {"terminus-1": True, "oracle": False, "nop": False}


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = REPO_ROOT / "data"
    namespace: str = "default"
    agent: str = "terminus-1"
    model: str = "openrouter/anthropic/claude-opus-4.5"
    default_attempts: int = 1
    max_attempts: int = 10
    max_concurrent_submissions: int = 16
    max_concurrent_builds: int = 4
    max_upload_bytes: int = 50 * 1024**2
    max_extracted_bytes: int = 500 * 1024**2
    build_timeout_sec: int = 1800
    attempt_overhead_sec: int = 600
    retries_per_attempt: int = 1
    poll_interval_sec: float = 5.0
    adaptive_max_wave: int = 10
    adaptive_extra_launches: int = 3
    # Claude Opus 4.5 list price; token counts come from terminal-bench's tokenizer
    # estimates and ignore prompt caching, so dollar figures are approximate.
    price_input_per_mtok: float = 5.0
    price_output_per_mtok: float = 25.0
    # Docker Desktop's daemon sees the macOS filesystem under /host_mnt; pods bind
    # host paths through it when starting sibling task containers.
    host_path_prefix: str = "/host_mnt"
    harness_memory_limit: str = "2Gi"
    # A prebuilt Job pod image; when unset it is built locally from runner/Dockerfile.
    runner_image: str | None = None
    llm_secret_name: str = "aq-llm-credentials"
    llm_secret_keys: tuple[str, ...] = field(default=("OPENROUTER_API_KEY",))

    @classmethod
    def from_env(cls) -> "Settings":
        """Defaults overridden by AQ_* environment variables (and the repo's .env)."""
        load_dotenv()
        defaults = cls()
        return cls(
            data_dir=Path(_env("AQ_DATA_DIR", str(defaults.data_dir))).resolve(),
            namespace=_env("AQ_NAMESPACE", defaults.namespace),
            agent=_env("AQ_AGENT", defaults.agent),
            model=_env("AQ_MODEL", defaults.model),
            default_attempts=int(_env("AQ_DEFAULT_ATTEMPTS", str(defaults.default_attempts))),
            max_attempts=int(_env("AQ_MAX_ATTEMPTS", str(defaults.max_attempts))),
            max_concurrent_submissions=int(
                _env("AQ_MAX_CONCURRENT_SUBMISSIONS", str(defaults.max_concurrent_submissions))
            ),
            max_concurrent_builds=int(_env("AQ_MAX_CONCURRENT_BUILDS", str(defaults.max_concurrent_builds))),
            max_upload_bytes=int(_env("AQ_MAX_UPLOAD_BYTES", str(defaults.max_upload_bytes))),
            max_extracted_bytes=int(_env("AQ_MAX_EXTRACTED_BYTES", str(defaults.max_extracted_bytes))),
            build_timeout_sec=int(_env("AQ_BUILD_TIMEOUT_SEC", str(defaults.build_timeout_sec))),
            attempt_overhead_sec=int(_env("AQ_ATTEMPT_OVERHEAD_SEC", str(defaults.attempt_overhead_sec))),
            retries_per_attempt=int(_env("AQ_RETRIES_PER_ATTEMPT", str(defaults.retries_per_attempt))),
            poll_interval_sec=float(_env("AQ_POLL_INTERVAL_SEC", str(defaults.poll_interval_sec))),
            adaptive_max_wave=int(_env("AQ_ADAPTIVE_MAX_WAVE", str(defaults.adaptive_max_wave))),
            adaptive_extra_launches=int(
                _env("AQ_ADAPTIVE_EXTRA_LAUNCHES", str(defaults.adaptive_extra_launches))
            ),
            price_input_per_mtok=float(
                _env("AQ_PRICE_INPUT_PER_MTOK", str(defaults.price_input_per_mtok))
            ),
            price_output_per_mtok=float(
                _env("AQ_PRICE_OUTPUT_PER_MTOK", str(defaults.price_output_per_mtok))
            ),
            host_path_prefix=_env("AQ_HOST_PATH_PREFIX", defaults.host_path_prefix),
            harness_memory_limit=_env("AQ_HARNESS_MEMORY_LIMIT", defaults.harness_memory_limit),
            runner_image=os.environ.get("AQ_RUNNER_IMAGE") or None,
        )

    def requires_model(self, agent: str) -> bool:
        return AGENTS[agent]

    @property
    def submissions_dir(self) -> Path:
        return self.data_dir / "submissions"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "executor.db"
