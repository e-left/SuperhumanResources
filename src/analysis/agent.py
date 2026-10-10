import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from src.analysis.models import CodebaseAnalysis
from src.analysis.prompt import SYSTEM, build_prompt
from src.analysis.repository import AnalysisError, clone, collect_files, project_root
from src.interview import loader


def ask_gemini(bundle: dict, role: str) -> CodebaseAnalysis:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model = os.environ.get("GEMINI_MODEL", "").strip()
    if not api_key or not model:
        raise AnalysisError("set GEMINI_API_KEY and GEMINI_MODEL in the local .env")
    try:
        with genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=90_000, retry_options=types.HttpRetryOptions(attempts=1)),
        ) as client:
            response = client.models.generate_content(
                model=model,
                contents=build_prompt(bundle, role),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM,
                    response_mime_type="application/json",
                    response_schema=CodebaseAnalysis,
                    temperature=0.2,
                ),
            )
        result = CodebaseAnalysis.model_validate_json(response.text or "")
    except Exception as exc:
        # SDK exceptions can contain request data: don't expose their raw text.
        raise AnalysisError(f"Gemini analysis failed ({type(exc).__name__}); check model access, quota, and connectivity") from exc
    paths = {file["path"] for file in bundle["files"]}
    for item in [*result.technologies, *result.project_areas, *result.questions]:
        if not set(item.source_files).issubset(paths):
            raise AnalysisError("Gemini cited a file that was not included in its input")
    return result


def question_docs(result: CodebaseAnalysis) -> dict[str, str]:
    docs = {}
    for index, generated in enumerate(result.questions, 1):
        fields = [generated.question, generated.answer, generated.context]
        if any(not value.strip() or re.search(r"(?m)^\s*#{1,2}\s", value) for value in fields):
            raise AnalysisError("Gemini returned empty fields or unsupported Markdown headings")
        context = generated.context + "\n\nSource files: " + ", ".join(f"`{p}`" for p in generated.source_files)
        doc = f"# Question\n{generated.question}\n\n# Answer\n{generated.answer}\n\n# Context\n{context}\n"
        loader.parse_question(f"q{index}", doc)
        docs[f"q{index}.md"] = doc
    return docs


def analyze(root: Path, role: str = "Software Engineer", repo_url: str | None = None, subdir: str = "") -> dict:
    if not role.strip() or len(role) > 200:
        raise AnalysisError("role must be between 1 and 200 characters")
    bundle = collect_files(root)
    result = ask_gemini(bundle, role)
    docs = question_docs(result)
    session_id = uuid.uuid4().hex
    loader.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Publish the session only after all files have been written successfully.
    with tempfile.TemporaryDirectory(dir=loader.DATA_DIR, prefix=".analysis-") as staging:
        directory = Path(staging)
        (directory / "questions").mkdir()
        for name, doc in docs.items():
            (directory / "questions" / name).write_text(doc, encoding="utf-8")
        context = {
            "session_id": session_id, "repo_url": repo_url, "role": role, "subdir": subdir,
            "model": os.environ.get("GEMINI_MODEL"),
            "included_files": [file["path"] for file in bundle["files"]],
            "omitted_files": bundle["omitted_files"], **result.model_dump(),
        }
        (directory / "context.json").write_text(json.dumps(context, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        directory.rename(loader.DATA_DIR / session_id)
    return load_questions(session_id)


def analyze_github(repo_url: str, role: str, subdir: str = "") -> dict:
    with tempfile.TemporaryDirectory(prefix="codebase-analysis-") as temporary:
        root = Path(temporary) / "repo"
        clone(repo_url, root)
        return analyze(project_root(root, subdir), role, repo_url, subdir)


def load_questions(session_id: str) -> dict:
    directory = loader.session_dir(session_id)
    questions = [loader.parse_question(f"q{i}", (directory / "questions" / f"q{i}.md").read_text(encoding="utf-8")) for i in range(1, 4)]
    return {"session_id": session_id, "questions": [question.model_dump() for question in questions]}


def load_context(session_id: str) -> dict:
    directory = loader.session_dir(session_id)
    try:
        context = json.loads((directory / "context.json").read_text(encoding="utf-8"))
        CodebaseAnalysis.model_validate(context)
    except (ValueError, UnicodeError) as exc:
        raise AnalysisError("saved codebase context is invalid; run a new analysis") from exc
    return context
