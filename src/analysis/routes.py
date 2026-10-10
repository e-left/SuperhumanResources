import fastapi

from src.analysis import agent
from src.analysis.models import AnalyzeRequest
from src.analysis.repository import AnalysisError, github_url
from src.interview import loader

router = fastapi.APIRouter()


@router.post("/analyze")
def analyze(request: AnalyzeRequest):
    try:
        github_url(request.repo_url)
    except AnalysisError as exc:
        raise fastapi.HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return agent.analyze_github(request.repo_url, request.role, request.subdir)
    except AnalysisError as exc:
        raise fastapi.HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/questions")
def questions(session_id: str):
    try:
        return agent.load_questions(session_id)
    except (loader.SessionError, FileNotFoundError) as exc:
        raise fastapi.HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/context")
def context(session_id: str):
    try:
        return agent.load_context(session_id)
    except (loader.SessionError, FileNotFoundError) as exc:
        raise fastapi.HTTPException(status_code=404, detail="codebase context not found") from exc
    except AnalysisError as exc:
        raise fastapi.HTTPException(status_code=422, detail=str(exc)) from exc
