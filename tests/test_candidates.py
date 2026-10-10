import datetime
import io
import json

from fastapi.testclient import TestClient
import pytest

from src.api.app import app
from src.candidates import cv, github, pipeline, profile, routes, store
from src.candidates.models import ProfileSummary
from src.interview import loader

REPO = "https://github.com/team/repo"
DOC = "# Question\nWhat is it?\n\n# Answer\nIt is this.\n\n# Context\nFrom `a.py`.\n"


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(data, monkeypatch):
    # The real preparation calls GitHub and Gemini; keep it out of the API tests.
    monkeypatch.setattr(pipeline, "prepare", lambda session_id: None)
    return TestClient(app)


def _form(**overrides):
    form = {"first_name": "Sam", "last_name": "Rivera", "role": "Backend Engineer",
            "repo_url": REPO, "github_profile": "https://github.com/octocat"}
    form.update(overrides)
    return form


def _make_ready(session_id):
    record = store.read(session_id)
    folder = store.directory(session_id)
    (folder / "questions").mkdir()
    for name in ("q1", "q2", "q3"):
        (folder / "questions" / f"{name}.md").write_text(DOC)
    (folder / "candidate.md").write_text("# Candidate profile\n\nName: Sam Rivera\n")
    record.preparation = "ready"
    store.write(record)
    return folder


def _transcript(session_id, ended_reason):
    return json.dumps({
        "session_id": session_id, "candidate_name": "Sam Rivera",
        "started_at": "2026-10-10T13:00:00+00:00", "ended_at": "2026-10-10T13:04:00+00:00",
        "ended_reason": ended_reason,
        "turns": [{"speaker": "candidate", "question_id": "q1", "text": "An answer.", "t": 1.0}],
    })


# --- creating ------------------------------------------------------------------


def test_create_list_and_detail(client):
    created = client.post("/api/candidates", data=_form(looking_for="Owns APIs end to end"))
    assert created.status_code == 202
    summary = created.json()
    assert summary["status"] == "preparing"
    assert summary["interview_url"] == f"/?session={summary['session_id']}"
    assert len(summary["session_id"]) == 32

    listed = client.get("/api/candidates").json()
    assert [c["session_id"] for c in listed] == [summary["session_id"]]

    detail = client.get(f"/api/candidates/{summary['session_id']}").json()
    assert detail["record"]["github_url"] == "https://github.com/octocat"
    assert detail["record"]["looking_for"] == "Owns APIs end to end"
    assert detail["questions"] is None and detail["transcript"] is None and detail["report"] is None


def test_cv_upload_is_stored(client, data):
    created = client.post(
        "/api/candidates", data=_form(github_profile=""),
        files={"cv_file": ("My CV.txt", io.BytesIO(b"Python engineer"), "text/plain")},
    )
    assert created.status_code == 202
    session_id = created.json()["session_id"]
    assert (data / session_id / "cv.txt").read_bytes() == b"Python engineer"
    assert store.read(session_id).cv_filename == "cv.txt"


@pytest.mark.parametrize("change, message", [
    ({"first_name": "  "}, "first name is required"),
    ({"repo_url": "https://gitlab.com/team/repo"}, "public repository URL"),
    ({"github_profile": "https://github.com/a/b/c"}, "GitHub profile link"),
])
def test_invalid_input_is_rejected(client, change, message):
    response = client.post("/api/candidates", data=_form(**change))
    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_wrong_cv_type_and_unknown_candidate(client):
    bad = client.post("/api/candidates", data=_form(),
                      files={"cv_file": ("cv.docx", io.BytesIO(b"x"), "application/octet-stream")})
    assert bad.status_code == 422 and "PDF, TXT or MD" in bad.json()["detail"]
    assert client.get("/api/candidates/" + "0" * 32).status_code == 404
    assert client.get("/api/candidates/../etc").status_code == 404


# --- status ----------------------------------------------------------------------


def test_status_follows_the_files(client, data):
    session_id = client.post("/api/candidates", data=_form()).json()["session_id"]
    status = lambda: store.summarize(store.read(session_id)).status
    assert status() == "preparing"
    folder = _make_ready(session_id)
    assert status() == "invited"
    (folder / "transcript.json").write_text(_transcript(session_id, None))
    assert status() == "in_progress"
    (folder / "transcript.json").write_text(_transcript(session_id, "completed"))
    assert status() == "interviewed"
    summary = store.summarize(store.read(session_id))
    assert summary.duration_s == 240 and summary.interviewed_at.startswith("2026-10-10T13:00")


def test_failed_preparation_shows_its_error(client):
    session_id = client.post("/api/candidates", data=_form()).json()["session_id"]
    record = store.read(session_id)
    pipeline._fail(record, "GitHub clone failed")
    summary = client.get("/api/candidates").json()[0]
    assert summary["status"] == "failed" and summary["error"] == "GitHub clone failed"


def test_stale_preparations_are_marked_failed(client):
    session_id = client.post("/api/candidates", data=_form()).json()["session_id"]
    assert store.fail_stale() == 0  # just created
    record = store.read(session_id)
    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    record.created_at = old.isoformat(timespec="seconds")
    store.write(record)
    assert store.fail_stale() == 1
    assert store.read(session_id).preparation == "failed"


# --- the candidate's link ----------------------------------------------------------


def _turns(*turns):
    return [{"speaker": speaker, "question_id": question_id, "text": text, "t": float(i)}
            for i, (speaker, question_id, text) in enumerate(turns)]


def _write_transcript(folder, session_id, ended_reason, turns):
    (folder / "transcript.json").write_text(json.dumps({
        "session_id": session_id, "candidate_name": "Sam Rivera",
        "started_at": "2026-10-10T13:00:00+00:00", "ended_at": "2026-10-10T13:01:00+00:00",
        "ended_reason": ended_reason, "turns": turns,
    }))


HELLO_ONLY = _turns(("agent", None, "Hi Sam, how are you?"), ("candidate", None, "Hi, good thanks."),
                    ("agent", "q1", "What is it?"))
ANSWERED = HELLO_ONLY + _turns(("candidate", "q1", "It is this."))


def test_public_endpoint_tells_the_candidate_page_almost_nothing(client, data):
    session_id = client.post("/api/candidates", data=_form()).json()["session_id"]
    public = lambda: client.get(f"/sessions/{session_id}/public").json()
    assert public() == {"first_name": "Sam", "state": "not_ready", "retake": False}
    folder = _make_ready(session_id)
    assert public() == {"first_name": "Sam", "state": "ready", "retake": False}
    store.start_attempt(session_id)
    (folder / "transcript.json").write_text(_transcript(session_id, "completed"))
    assert public() == {"first_name": "Sam", "state": "done", "retake": False}
    assert client.get("/sessions/" + "f" * 32 + "/public").status_code == 404


def test_fixture_sessions_still_work_as_interview_links(client):
    info = client.get("/sessions/demo/public").json()
    assert info == {"first_name": "Alex", "state": "ready", "retake": False}
    assert routes.interview_state("demo") == "ready"


# --- retakes: one, and only if no question was answered ---------------------------


@pytest.mark.parametrize("ended_reason", ["disconnected", "stopped", None])
def test_one_retake_when_the_first_attempt_ended_before_any_answer(client, data, ended_reason):
    session_id = client.post("/api/candidates", data=_form()).json()["session_id"]
    folder = _make_ready(session_id)
    assert store.start_attempt(session_id) == 1
    _write_transcript(folder, session_id, ended_reason, HELLO_ONLY)
    assert routes.interview_state(session_id) == "ready"
    assert client.get(f"/sessions/{session_id}/public").json()["retake"] is True
    if ended_reason is not None:
        # Nothing to evaluate yet: for the recruiter the candidate is still invited.
        assert store.summarize(store.read(session_id)).status == "invited"

    # The retake is the last start, however it ends.
    assert store.start_attempt(session_id) == 2
    _write_transcript(folder, session_id, "disconnected", HELLO_ONLY)
    assert routes.interview_state(session_id) == "closed"
    assert store.summarize(store.read(session_id)).status == "interviewed"


@pytest.mark.parametrize("ended_reason", ["disconnected", "stopped"])
def test_no_retake_once_a_question_was_answered(client, data, ended_reason):
    session_id = client.post("/api/candidates", data=_form()).json()["session_id"]
    folder = _make_ready(session_id)
    store.start_attempt(session_id)
    _write_transcript(folder, session_id, ended_reason, ANSWERED)
    assert routes.interview_state(session_id) == "closed"
    assert client.get(f"/sessions/{session_id}/public").json() == {
        "first_name": "Sam", "state": "closed", "retake": False}
    with client.websocket_connect(f"/sessions/{session_id}/interview") as socket:
        message = socket.receive_json()
    assert message == {"type": "error", "message": "This interview has ended and cannot be restarted."}
    assert store.read(session_id).attempts == 1  # a refused start is not counted


def test_finishing_is_final_even_on_the_first_attempt(client, data):
    session_id = client.post("/api/candidates", data=_form()).json()["session_id"]
    folder = _make_ready(session_id)
    store.start_attempt(session_id)
    for ending in ("completed", "time_limit"):
        _write_transcript(folder, session_id, ending, HELLO_ONLY)
        assert routes.interview_state(session_id) == "done"


def test_a_greeting_alone_is_not_an_answer():
    from src.shared.models import Transcript

    make = lambda turns: Transcript(session_id="s", candidate_name="Sam", started_at="", ended_at="", turns=turns)
    assert not store.answered_a_question(None)
    assert not store.answered_a_question(make(HELLO_ONLY))
    assert store.answered_a_question(make(ANSWERED))


def test_finished_interview_link_is_refused(client, data):
    session_id = client.post("/api/candidates", data=_form()).json()["session_id"]
    folder = _make_ready(session_id)
    store.start_attempt(session_id)
    (folder / "transcript.json").write_text(_transcript(session_id, "completed"))
    with client.websocket_connect(f"/sessions/{session_id}/interview") as socket:
        message = socket.receive_json()
    assert message == {"type": "error", "message": "This interview has already been completed."}


# --- profile sources ---------------------------------------------------------------


@pytest.mark.parametrize("value", [
    "https://github.com/octocat", "github.com/octocat/", "@octocat", "octocat", " https://www.github.com/octocat ",
])
def test_github_username_forms(value):
    assert github.username(value) == "octocat"
    assert github.profile_url(value) == "https://github.com/octocat"


@pytest.mark.parametrize("value", ["https://github.com/a/b", "https://gitlab.com/x", "not a user!", ""])
def test_github_rejects_other_links(value):
    with pytest.raises(github.GithubError):
        github.username(value)


def test_cv_text_extraction():
    assert cv.extract_text("cv.md", b"# Sam\r\n\r\nPython  \n") == "# Sam\n\nPython"
    assert len(cv.extract_text("cv.txt", b"x" * 50_000)) == cv.MAX_CHARS
    for name, data, message in [
        ("cv.docx", b"x", "PDF, TXT or MD"), ("cv.txt", b"   ", "no readable text"),
        ("cv.pdf", b"not a pdf", "could not be read"), ("cv.txt", b"x" * (cv.MAX_BYTES + 1), "5 MB"),
    ]:
        with pytest.raises(cv.CvError, match=message):
            cv.extract_text(name, data)


def test_profile_markdown_is_readable_by_the_interview_loader(client):
    session_id = client.post("/api/candidates", data=_form(looking_for="Owns APIs")).json()["session_id"]
    summary = ProfileSummary(
        headline="Backend engineer, three years", summary="Works  with Python.",
        skills=["Python", " "], experience=[], notable_projects=["A booking service"],
        open_points=["Verify real-time experience"],
    )
    markdown = profile.render(store.read(session_id), summary, {"username": "octocat"}, True)
    assert loader.candidate_name(markdown) == "Sam Rivera"
    assert "Role applied for: Backend Engineer" in markdown
    assert "## Experience" not in markdown  # empty sections are left out
    assert "- Python\n" in markdown and "- \n" not in markdown
    assert markdown.rstrip().endswith("Sources: GitHub @octocat, CV")


# --- preparation -------------------------------------------------------------------


def test_prepare_writes_profile_then_questions(data, monkeypatch):
    record = store.create(first_name="Sam", last_name="Rivera", role="Backend Engineer",
                          looking_for="Owns APIs", repo_url=REPO, subdir="api",
                          github_url="https://github.com/octocat", cv_filename=None)
    monkeypatch.setattr(github, "fetch_profile", lambda url: {"username": "octocat", "languages": ["Python"]})
    monkeypatch.setattr(profile, "summarise", lambda *args: ProfileSummary(
        headline="Engineer", summary="Builds APIs.", skills=["Python"], experience=[],
        notable_projects=[], open_points=[]))
    seen = {}

    def fake_analysis(repo_url, role, subdir, **options):
        seen.update(repo_url=repo_url, role=role, subdir=subdir, **options)
        folder = store.directory(options["session_id"])
        (folder / "questions").mkdir()
        for name in ("q1", "q2", "q3"):
            (folder / "questions" / f"{name}.md").write_text(DOC)

    monkeypatch.setattr(pipeline.agent, "analyze_github", fake_analysis)
    pipeline.prepare(record.session_id)

    assert store.read(record.session_id).preparation == "ready"
    assert seen["subdir"] == "api" and seen["looking_for"] == "Owns APIs"
    assert "Name: Sam Rivera" in seen["candidate_profile"]
    assert len(loader.load_session(record.session_id).questions) == 3
    assert store.summarize(store.read(record.session_id)).status == "invited"


def test_candidate_without_github_or_cv_is_accepted(client):
    created = client.post("/api/candidates", data=_form(github_profile=""))
    assert created.status_code == 202
    record = store.read(created.json()["session_id"])
    assert record.github_url is None and record.cv_filename is None


def _analysis_stub(monkeypatch, seen):
    def fake_analysis(repo_url, role, subdir, **options):
        seen.update(options)
        folder = store.directory(options["session_id"])
        (folder / "questions").mkdir()
        for name in ("q1", "q2", "q3"):
            (folder / "questions" / f"{name}.md").write_text(DOC)

    monkeypatch.setattr(pipeline.agent, "analyze_github", fake_analysis)


@pytest.mark.parametrize("github_url", [None, "https://github.com/ghost-user"])
def test_prepare_carries_on_without_any_profile_source(data, monkeypatch, github_url):
    """Nothing given, or the only source is inaccessible: still prepare the interview."""
    record = store.create(first_name="Sam", last_name="Rivera", role="Engineer", looking_for="Owns APIs",
                          repo_url=REPO, github_url=github_url, cv_filename=None)

    def missing(url):
        raise github.GithubError("GitHub has no user called ghost-user")

    def no_model_call(*args):
        raise AssertionError("the profile agent must not run without sources")

    monkeypatch.setattr(github, "fetch_profile", missing)
    monkeypatch.setattr(profile, "summarise", no_model_call)
    seen = {}
    _analysis_stub(monkeypatch, seen)
    pipeline.prepare(record.session_id)

    done = store.read(record.session_id)
    assert done.preparation == "ready" and done.error is None
    assert any("role and the codebase only" in w for w in done.warnings)
    if github_url:
        assert any("ghost-user" in w for w in done.warnings)
    inputs = loader.load_session(record.session_id)
    assert inputs.candidate_name == "Sam Rivera"
    assert "No GitHub profile or CV was available" in inputs.candidate_profile
    assert "What we are looking for: Owns APIs" in seen["candidate_profile"]


def test_one_unreadable_source_is_only_a_warning(data, monkeypatch):
    record = store.create(first_name="Sam", last_name="Rivera", role="Engineer", repo_url=REPO,
                          github_url="https://github.com/ghost-user", cv_filename="cv.txt")
    (store.directory(record.session_id) / "cv.txt").write_text("Python engineer")
    monkeypatch.setattr(github, "fetch_profile",
                        lambda url: (_ for _ in ()).throw(github.GithubError("rate limit")))
    monkeypatch.setattr(profile, "summarise", lambda *args: ProfileSummary(
        headline="Engineer", summary="Python.", skills=[], experience=[], notable_projects=[], open_points=[]))
    monkeypatch.setattr(pipeline.agent, "analyze_github", lambda *a, **k: None)
    pipeline.prepare(record.session_id)
    done = store.read(record.session_id)
    assert done.preparation == "ready"
    assert done.warnings == ["GitHub profile not used: rate limit"]


def test_candidates_page_is_served(client):
    page = client.get("/candidates")
    assert page.status_code == 200 and "All candidates" in page.text
    assert client.get("/static/candidates.js").status_code == 200
