"""Recruiter-side API for candidates, plus the one thing the candidate page may know."""

import fastapi

from src.analysis.repository import AnalysisError, github_url
from src.candidates import cv, github, pipeline, store
from src.candidates.models import CandidateDetail, CandidateSummary
from src.interview import loader

router = fastapi.APIRouter()

def _clean(value: str, limit: int, field: str, required: bool = True) -> str:
    value = " ".join((value or "").split())
    if required and not value:
        raise fastapi.HTTPException(status_code=422, detail=f"{field} is required")
    if len(value) > limit:
        raise fastapi.HTTPException(status_code=422, detail=f"{field} is too long")
    return value


@router.post("/api/candidates", status_code=202)
async def create_candidate(
    background: fastapi.BackgroundTasks,
    first_name: str = fastapi.Form(...),
    last_name: str = fastapi.Form(...),
    role: str = fastapi.Form(...),
    repo_url: str = fastapi.Form(...),
    looking_for: str = fastapi.Form(""),
    subdir: str = fastapi.Form(""),
    github_profile: str = fastapi.Form(""),
    cv_file: fastapi.UploadFile | None = fastapi.File(None),
) -> CandidateSummary:
    fields = {
        "first_name": _clean(first_name, 80, "first name"),
        "last_name": _clean(last_name, 80, "last name"),
        "role": _clean(role, 200, "role"),
        "looking_for": (looking_for or "").strip()[:2000],
        "subdir": _clean(subdir, 300, "project directory", required=False),
    }
    try:
        fields["repo_url"] = github_url(repo_url.strip())
        profile_link = github.profile_url(github_profile) if github_profile.strip() else None
    except (AnalysisError, github.GithubError) as exc:
        raise fastapi.HTTPException(status_code=422, detail=str(exc)) from exc

    cv_bytes = cv_name = None
    if cv_file is not None and cv_file.filename:
        try:
            cv_name = "cv" + cv.suffix(cv_file.filename)
        except cv.CvError as exc:
            raise fastapi.HTTPException(status_code=422, detail=str(exc)) from exc
        cv_bytes = await cv_file.read(cv.MAX_BYTES + 1)
        if len(cv_bytes) > cv.MAX_BYTES:
            raise fastapi.HTTPException(status_code=422, detail="the CV is larger than 5 MB")
    # Both sources are optional: with neither, the questions are tailored to the
    # opening and the codebase only.
    record = store.create(github_url=profile_link, cv_filename=cv_name, **fields)
    if cv_bytes is not None:
        (store.directory(record.session_id) / cv_name).write_bytes(cv_bytes)
    background.add_task(pipeline.prepare, record.session_id)
    return store.summarize(record)


@router.get("/api/candidates")
def list_candidates() -> list[CandidateSummary]:
    return [store.summarize(record) for record in store.list_records()]


@router.get("/api/candidates/{session_id}")
def get_candidate(session_id: str) -> CandidateDetail:
    try:
        return store.detail(store.read(session_id))
    except store.NotFound as exc:
        raise fastapi.HTTPException(status_code=404, detail=str(exc)) from exc


def interview_state(session_id: str) -> str:
    """'ready', 'not_ready', 'done' or 'closed' for an interview link (see store.interview_state).

    Sessions that are not candidates (the hand-made fixtures) can always start.
    """
    return store.interview_state(session_id) if store.exists(session_id) else "ready"


@router.get("/sessions/{session_id}/public")
def public(session_id: str) -> dict:
    """All the candidate's page is told: a first name and whether the interview can start."""
    try:
        if store.exists(session_id):
            record = store.read(session_id)
            first_name = record.first_name
            state = interview_state(session_id)
            if state == "ready":
                loader.load_session(session_id)  # the inputs must really be there
            retake = state == "ready" and record.attempts > 0
        else:
            first_name = loader.load_session(session_id).candidate_name.split()[0]
            state, retake = "ready", False
    except loader.SessionError as exc:
        raise fastapi.HTTPException(status_code=404, detail="unknown interview link") from exc
    # `retake` tells the page this start is the one second chance at starting.
    return {"first_name": first_name, "state": state, "retake": retake}
