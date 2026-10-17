"""Application wiring, built once at startup and shared with routes via dependencies."""

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from api.service import SubmissionService
from api.validation import ValidationService
from runner.config import Settings
from runner.k8s import KubeClient
from runner.models import Submission
from runner.run_task import TaskRunner
from runner.store import SubmissionNotFound, SubmissionStore
from runner.validation.pipeline import Validator
from runner.validation.store import ValidationStore

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    store: SubmissionStore
    kube: KubeClient
    service: SubmissionService
    validations: ValidationService

    @classmethod
    def create(cls, settings: Settings) -> "AppContext":
        store = SubmissionStore(settings.db_path)
        kube = KubeClient(settings.namespace)
        runner = TaskRunner(store, kube, settings)
        validator = Validator(ValidationStore(settings.db_path), runner, settings)
        service = SubmissionService(store, runner, validator, settings)
        validations = ValidationService(validator, settings)
        return cls(settings=settings, store=store, kube=kube, service=service, validations=validations)

    def resume_unfinished(self) -> None:
        self.service.resume_unfinished()
        self.validations.resume_unfinished()

    def shutdown(self) -> None:
        self.validations.shutdown()
        self.service.shutdown()


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


Context = Annotated[AppContext, Depends(get_context)]


def get_submission(context: Context, submission_id: str) -> Submission:
    try:
        return context.store.get(submission_id)
    except SubmissionNotFound:
        raise HTTPException(status_code=404, detail=f"submission {submission_id} not found") from None


SubmissionDep = Annotated[Submission, Depends(get_submission)]


def unprocessable(message: str, report: dict | None = None) -> JSONResponse:
    """The 422 envelope used by every route: a string `detail`, plus a report when one exists."""
    content = {"detail": message} | ({"report": jsonable_encoder(report)} if report else {})
    return JSONResponse(status_code=422, content=content)
