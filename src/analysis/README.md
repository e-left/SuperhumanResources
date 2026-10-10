# Codebase context extraction agent

Gemini reads the source files, identifies technologies and project areas, and
generates three generalized questions about project experience, optimization,
and trade-offs. Candidates do not need to have read the repository.

The Python code only collects files, calls Gemini once, validates the result,
and saves it. There is no separate manual codebase analysis or vector database.

From the repository root:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Fill in `GEMINI_API_KEY` in the root `.env`. The local `.env` is gitignored and
has `GEMINI_MODEL=gemini-2.5-flash` set. You can change it to another model
available to your API key that supports
[structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).

Analyze the local demo:

```sh
.venv/bin/python -m src.analysis --path demo-proj --role "Backend Engineer"
```

Or shallow-clone a public GitHub repository. Use `--subdir` if the project lives
inside a larger repository:

```sh
.venv/bin/python -m src.analysis \
  --repo-url https://github.com/e-left/SuperhumanResources \
  --subdir demo-proj --role "Backend Engineer"
```

The command prints the session ID and parsed questions. It writes:

```text
data/<session_id>/context.json
data/<session_id>/questions/q1.md
data/<session_id>/questions/q2.md
data/<session_id>/questions/q3.md
```

`context.json` contains the summary, technologies, project areas, optimization
topics, questions, and the file coverage. Each question document contains
`# Question`, `# Answer`, and `# Context`, including source paths. Add the actual
candidate profile as `data/<session_id>/candidate.md` before starting the voice
interview at `/?session=<session_id>`.

The FastAPI app also exposes `POST /analyze` with
`{"repo_url": "https://github.com/owner/repo", "role": "Backend Engineer", "subdir": ""}`
and `GET /sessions/<session_id>/questions`.

## Context Studio

Start `.venv/bin/uvicorn src.api.app:app` and open `http://localhost:8000/`.
The workspace accepts a public GitHub repository, hiring role, and optional
project directory. It shows the saved technology map, project areas, three
questions with reference answers, and included/omitted source files. You can
export the context as JSON or copy its session ID. The **Explore a sample**
button shows a labeled illustrative preview without calling Gemini.

`GET /sessions/<session_id>/context` returns the saved `context.json` analysis.
The workspace remembers its session in `/?context=<session_id>` so refreshing
or reopening the link loads saved context instead of generating it again.
Voice interviews remain at `/?session=<session_id>`; add the actual candidate
profile to `data/<session_id>/candidate.md` before opening an interview.

Collection skips hidden files/directories (including `.env` and `.git`), obvious
credential filenames, symlinks, vendored/generated files, and lockfiles. It sends
up to 150 supported text files, 80 KB per file, 600 KB total. Budget exclusions
are listed in `context.json`; this is a bounded sample for large repositories.
File filtering is not a general secret scanner: source text is sent to Gemini.
No repository code is executed. Clone and Gemini requests have 60 and 90 second
timeouts respectively; failed Gemini calls are not retried automatically.

Tests run offline with a mocked Gemini response:

```sh
.venv/bin/python -m pytest tests/test_analysis.py
```

## Candidate flow

Context Studio now prepares an interview for one candidate: it posts the form to
`POST /api/candidates` (`src/candidates/`), which builds the candidate's profile
and then calls `agent.analyze_github(..., looking_for=..., candidate_profile=...,
session_id=...)`. With those options the questions are written for that
candidate and saved into the candidate's existing session folder; at most two of
them get a `# Follow-up` section. Without them, `POST /analyze` and the CLI
behave exactly as before.
