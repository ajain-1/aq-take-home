import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from api.context import AppContext, get_context
from runner import insights
from runner.store import SubmissionNotFound

router = APIRouter()
Context = Annotated[AppContext, Depends(get_context)]


@router.get("/insights/{submission_id}")
def get_insights(
    context: Context, submission_id: str, format: str = "json", refresh: bool = False, narrative: bool = True
):
    """Evidence-backed analysis of a finished submission's attempts (format=json|markdown)."""
    try:
        submission = context.store.get(submission_id)
    except SubmissionNotFound as e:
        raise HTTPException(status_code=404, detail=f"submission {submission_id} not found") from e
    if not submission.status.is_terminal or submission.results is None:
        return JSONResponse(
            status_code=409,
            content={
                "submission_id": submission.id,
                "status": submission.status,
                "detail": "insights need results",
            },
        )

    root = context.settings.submissions_dir / submission.id
    cached = root / "insights.json"
    report = (
        json.loads(cached.read_text())
        if cached.exists() and not refresh
        else insights.generate(root, narrative)
    )
    if format == "markdown":
        return PlainTextResponse(insights.render_markdown(report), media_type="text/markdown")
    return {"submission_id": submission.id, **report}
