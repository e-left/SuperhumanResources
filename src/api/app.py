"""FastAPI app. Run with: uvicorn src.api.app:app"""

import logging
import pathlib

import dotenv
import fastapi
import fastapi.responses
import gradbot

from src.analysis.routes import router as analysis_router
from src.candidates import store as candidate_store
from src.candidates.routes import router as candidates_router
from src.evaluation import evaluator
from src.interview import llm_proxy, loader
from src.interview.session import run_interview
from src.shared.models import Report, Transcript

ROOT = pathlib.Path(__file__).resolve().parents[2]
dotenv.load_dotenv(ROOT / ".env")

gradbot.init_logging()
# Show the interview's own log lines (tool calls, transcript saved) in the server output.
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s", "%H:%M:%S"))
logging.getLogger("interview").addHandler(_handler)
logging.getLogger("interview").setLevel(logging.INFO)
app = fastapi.FastAPI(title="SuperhumanResources")
app.include_router(llm_proxy.router)
app.include_router(analysis_router)
app.include_router(candidates_router)
# Preparations cut short by a restart would otherwise stay "preparing" forever.
candidate_store.fail_stale()


@app.websocket("/sessions/{session_id}/interview")
async def interview(websocket: fastapi.WebSocket, session_id: str):
    await run_interview(websocket, session_id)


@app.post("/sessions/{session_id}/evaluate")
def evaluate(session_id: str) -> Report:
    try:
        return evaluator.evaluate(session_id)
    except loader.SessionError as exc:
        raise fastapi.HTTPException(status_code=404, detail=str(exc))
    except evaluator.EvaluationError as exc:
        raise fastapi.HTTPException(status_code=422, detail=str(exc))


@app.get("/sessions/{session_id}/report")
def report(session_id: str) -> Report:
    try:
        found = evaluator.load_report(session_id)
    except loader.SessionError as exc:
        raise fastapi.HTTPException(status_code=404, detail=str(exc))
    if found is None:
        raise fastapi.HTTPException(status_code=404, detail="no report yet")
    return found


@app.get("/sessions/{session_id}/transcript")
def transcript(session_id: str) -> Transcript:
    try:
        return evaluator.load_transcript(session_id)
    except (loader.SessionError, evaluator.EvaluationError) as exc:
        raise fastapi.HTTPException(status_code=404, detail=str(exc))


# Internal, for recruiters. Deliberately not under web/, which is the candidate's page.
@app.get("/internal/report")
def report_page():
    return fastapi.responses.FileResponse(ROOT / "internal" / "report.html")


# Recruiter's list of candidates, their transcripts and evaluations.
@app.get("/candidates", include_in_schema=False)
def candidates_page():
    return fastapi.responses.FileResponse(ROOT / "web" / "candidates.html")


# Context Studio at /, the candidate's voice interview at /?session=<id>.
@app.get("/", include_in_schema=False)
def workspace(session: str | None = None):
    page = "index.html" if session is not None else "context.html"
    return fastapi.responses.FileResponse(ROOT / "web" / page)


@app.get("/applicants", include_in_schema=False)
def applicants():
    return fastapi.responses.FileResponse(ROOT / "web" / "applicants.html")


# Serves the workspace assets and Gradbot's audio worklet under /static/js.
gradbot.routes.setup(app, static_dir=ROOT / "web")
