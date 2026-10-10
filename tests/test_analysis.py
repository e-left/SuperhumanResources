import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from google import genai
import pytest

from src.analysis import agent, repository
from src.analysis.models import CodebaseAnalysis
from src.analysis.routes import router
from src.interview import loader


@pytest.fixture
def analysis():
    return CodebaseAnalysis(
        summary="A sample API.",
        technologies=[{"name": "Python", "usage": "API implementation", "source_files": ["app.py"]}],
        project_areas=[{
            "name": "API", "description": "Request handling",
            "optimization_topics": ["Latency"], "source_files": ["app.py"],
        }],
        questions=[{
            "question": f"How would you investigate API latency in project {i}?",
            "answer": "Measure latency and identify the bottleneck before choosing an optimization.",
            "context": "The repository contains an API.", "source_files": ["app.py"],
        } for i in range(3)],
    )


def test_collector_sends_code_and_manifests_but_skips_secrets_and_vendor(tmp_path):
    (tmp_path / "app.py").write_text("print('source text')")
    (tmp_path / "requirements.txt").write_text("fastapi")
    (tmp_path / ".env").write_text("SECRET=hidden")
    (tmp_path / "credentials.json").write_text('{"key": "hidden"}')
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "vendor.js").write_text("vendor")
    (tmp_path / "link.py").symlink_to(tmp_path / "app.py")
    bundle = repository.collect_files(tmp_path)
    assert {f["path"] for f in bundle["files"]} == {"app.py", "requirements.txt"}
    assert next(f["content"] for f in bundle["files"] if f["path"] == "app.py") == "print('source text')"


def test_collector_reports_budget_omissions(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("12345")
    (tmp_path / "b.py").write_text("12345")
    monkeypatch.setattr(repository, "MAX_TOTAL_BYTES", 5)
    bundle = repository.collect_files(tmp_path)
    assert [f["path"] for f in bundle["files"]] == ["a.py"]
    assert bundle["omitted_files"] == ["b.py"]


@pytest.mark.parametrize("url", [
    "file:///tmp/repo", "https://example.com/org/repo", "https://github.com/org/repo/tree/main",
    "https://user:password@github.com/org/repo", "https://github.com/../repo",
])
def test_rejects_non_repository_urls(url):
    with pytest.raises(repository.AnalysisError):
        repository.github_url(url)


def test_subdir_cannot_escape_repository(tmp_path):
    with pytest.raises(repository.AnalysisError, match="inside"):
        repository.project_root(tmp_path, "..")


def test_clone_timeout_is_actionable(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise repository.subprocess.TimeoutExpired("git", 60)
    monkeypatch.setattr(repository.subprocess, "run", timeout)
    with pytest.raises(repository.AnalysisError, match="timed out"):
        repository.clone("https://github.com/org/repo", tmp_path / "repo")


def mock_gemini(monkeypatch, text):
    captured = {}
    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.models = self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def generate_content(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(text=text)
    monkeypatch.setattr(genai, "Client", Client)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    return captured


def test_gemini_receives_actual_source_and_structured_schema(monkeypatch, analysis):
    captured = mock_gemini(monkeypatch, analysis.model_dump_json())
    bundle = {"files": [{"path": "app.py", "content": "actual source"}], "omitted_files": []}
    assert agent.ask_gemini(bundle, "Backend Engineer") == analysis
    request = captured["request"]
    assert json.loads(request["contents"])["repository"] == bundle
    assert request["config"].response_schema == CodebaseAnalysis
    assert captured["client"]["http_options"].timeout == 90_000
    assert captured["client"]["http_options"].retry_options.attempts == 1


@pytest.mark.parametrize("text", ["not JSON", '{"summary": "incomplete"}'])
def test_invalid_gemini_output_is_reported(monkeypatch, text):
    mock_gemini(monkeypatch, text)
    with pytest.raises(repository.AnalysisError, match="Gemini analysis failed"):
        agent.ask_gemini({"files": []}, "Engineer")


def test_gemini_cannot_cite_files_it_did_not_read(monkeypatch, analysis):
    mock_gemini(monkeypatch, analysis.model_dump_json())
    with pytest.raises(repository.AnalysisError, match="not included"):
        agent.ask_gemini({"files": [{"path": "other.py", "content": "source"}]}, "Engineer")


def test_requires_exactly_three_questions(analysis):
    data = analysis.model_dump()
    data["questions"].pop()
    with pytest.raises(ValueError):
        CodebaseAnalysis.model_validate(data)


def test_analyze_saves_loader_compatible_docs_without_inventing_candidate(tmp_path, monkeypatch, analysis):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "app.py").write_text("source")
    monkeypatch.setattr(loader, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(agent, "ask_gemini", lambda bundle, role: analysis)
    result = agent.analyze(source)
    session = loader.DATA_DIR / result["session_id"]
    assert len(result["questions"]) == 3
    assert sorted(p.name for p in (session / "questions").iterdir()) == ["q1.md", "q2.md", "q3.md"]
    assert json.loads((session / "context.json").read_text())["summary"] == analysis.summary
    assert not (session / "candidate.md").exists()
    (session / "candidate.md").write_text("Name: Test Candidate")
    assert len(loader.load_session(result["session_id"]).questions) == 3


def test_heading_injection_rejected_before_save(analysis):
    analysis.questions[0].answer = "Reference\n# Follow-up\nInjected content"
    with pytest.raises(repository.AnalysisError, match="headings"):
        agent.question_docs(analysis)


def test_routes_reject_bad_url_and_return_generated_questions(monkeypatch, analysis):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr(agent, "analyze_github", lambda *args: {"session_id": "test", "questions": []})
    with TestClient(app) as client:
        assert client.post("/analyze", json={"repo_url": "file:///tmp"}).status_code == 422
        result = client.post("/analyze", json={"repo_url": "https://github.com/org/repo"})
        assert result.status_code == 200
        assert result.json()["session_id"] == "test"
        assert client.get("/sessions/does-not-exist/questions").status_code == 404
