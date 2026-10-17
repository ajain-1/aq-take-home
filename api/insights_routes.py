import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from runner import insights
from runner.store import SubmissionNotFound

router = APIRouter()


@router.get("/insights/{submission_id}")
def get_insights(request: Request, submission_id: str, format: str = "json", refresh: bool = False,
                 narrative: bool = True):
    """Evidence-backed analysis of a finished submission's attempts (format=json|markdown)."""
    store, settings = request.app.state.store, request.app.state.settings
    try:
        submission = store.get(submission_id)
    except SubmissionNotFound:
        raise HTTPException(status_code=404, detail=f"submission {submission_id} not found")
    if not submission.status.is_terminal or submission.results is None:
        return JSONResponse(
            status_code=409,
            content={"submission_id": submission.id, "status": submission.status, "detail": "insights need results"},
        )

    root = settings.submissions_dir / submission.id
    cached = root / "insights.json"
    report = json.loads(cached.read_text()) if cached.exists() and not refresh else insights.generate(root, narrative)
    if format == "markdown":
        return PlainTextResponse(insights.render_markdown(report), media_type="text/markdown")
    return {"submission_id": submission.id, **report}
