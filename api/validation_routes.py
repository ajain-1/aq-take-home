"""Endpoints for task quality validation (see runner/validation)."""

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from api.context import Context, unprocessable
from api.validation import ValidationRejected
from runner.validation.models import ValidationMode
from runner.validation.store import ValidationNotFound

router = APIRouter()


@router.post("/validate")
def validate_task(
    context: Context,
    file: Annotated[UploadFile, File()],
    mode: Annotated[ValidationMode, Form()] = ValidationMode.FULL,
    force: Annotated[bool, Form()] = False,
):
    """
    Check a task before spending agent compute on it.

    `static` returns the report immediately. `full` (202) also builds and probes the
    image and runs the oracle (twice) and nop agents as Jobs; poll /validations/{id}.
    `force` runs the dynamic stages even when static checks report errors.
    """
    archive = file.file.read(context.settings.max_upload_bytes + 1)
    try:
        validation = context.validations.validate(archive, mode, force)
    except ValidationRejected as e:
        return unprocessable(str(e))
    status_code = 200 if validation.status.is_terminal else 202
    return JSONResponse(status_code=status_code, content=jsonable_encoder(validation.report()))


@router.get("/validations/{validation_id}")
def get_validation(context: Context, validation_id: str):
    try:
        return context.validations.get(validation_id).report()
    except ValidationNotFound:
        raise HTTPException(status_code=404, detail=f"validation {validation_id} not found") from None
