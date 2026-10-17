"""Application wiring, built once at startup and shared with routes via dependencies."""

import logging
from dataclasses import dataclass

from fastapi import Request

from api.service import SubmissionService
from runner.config import Settings
from runner.k8s import KubeClient
from runner.run_task import TaskRunner
from runner.store import SubmissionStore

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    store: SubmissionStore
    kube: KubeClient
    service: SubmissionService

    @classmethod
    def create(cls, settings: Settings) -> "AppContext":
        store = SubmissionStore(settings.db_path)
        kube = KubeClient(settings.namespace)
        service = SubmissionService(store, TaskRunner(store, kube, settings), settings)
        return cls(settings=settings, store=store, kube=kube, service=service)


def configure_logging() -> None:
    """uvicorn owns the root logger's setup, so our packages get their own handler."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    for name in ("api", "runner"):
        package_logger = logging.getLogger(name)
        if not package_logger.handlers:
            package_logger.addHandler(handler)
        package_logger.setLevel(logging.INFO)
        package_logger.propagate = False


def get_context(request: Request) -> AppContext:
    return request.app.state.context
