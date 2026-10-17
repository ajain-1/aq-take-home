"""Evidence-backed insights over a finished submission's attempts (see runner/insights)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from api.context import Context, SubmissionDep
from runner import insights
from runner.paths import SubmissionPaths

router = APIRouter()


@router.get("/insights/{submission_id}")
def get_insights(
    context: Context,
    submission: SubmissionDep,
    output_format: Annotated[Literal["json", "markdown"], Query(alias="format")] = "json",
    narrative: bool = False,
):
    """Findings computed from the stored artifacts on every request; read-only.

    `narrative=true` adds a short LLM summary constrained to the verified findings.
    """
    if not submission.status.is_terminal or submission.results is None:
        return JSONResponse(
            status_code=409,
            content={
                "submission_id": submission.id,
                "status": submission.status,
                "detail": "insights need results",
            },
        )

    root = SubmissionPaths(context.settings.submissions_dir / submission.id).root
    report = insights.build(root, context.settings.insights_model if narrative else None)
    if output_format == "markdown":
        return PlainTextResponse(insights.render_markdown(report), media_type="text/markdown")
    return {"submission_id": submission.id, **report}
