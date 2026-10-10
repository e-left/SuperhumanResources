# SuperhumanResources — CONTEXT

Shared context for humans and coding agents. Read this first. Update it when a decision changes.

## 1. What we are building

An AI HR platform that runs a technical interview grounded in a company's own code.

1. **Analyze**: take a GitHub repo URL, read the codebase, produce 3 interview questions specific to it.
2. **Interview**: a voice agent (Gradium) takes those 3 questions plus a candidate profile, asks the questions by voice and records the full transcript. It does no scoring.
3. **Evaluate**: an agent scores the transcript and writes a report.

One-line pitch: "Interview candidates on the code they would actually work on."

## 2. Hackathon

- Event: {Tech: Europe} Agentic AI Hack, Zürich, co-hosted by Google DeepMind and J floor
- Date: Saturday 10 Oct 2026, 09:30 to 21:30
- **19:00 competition opt-in deadline** (hard stop for features)
- 20:00 live demos, 20:45 awards
- Technology partners (free credits): **Gradium** (voice: TTS + STT), **Entire** (agent-human collaboration platform, already wired into this repo via `.entire/`)
- Frontier models: Google DeepMind (Gemini)
- Event page: https://luma.com/zrh-hack
- TODO: judging criteria and submission format were not on the event page. Check Discord and paste here.

Implication: the demo is live. A working end-to-end path beats any single polished step.

## 3. Locked decisions

| Area | Decision |
| - | - |
| Language | Python 3.12+ (Gradbot requirement) |
| Backend | FastAPI, one process |
| Frontend | Buildless HTML/CSS/JS Context Studio at `/`, voice interview at `/?session=<id>`, and final report. The interview itself is voice only, no question text on screen |
| LLM | Gemini for all three agents. Model id in `GEMINI_MODEL` env var, currently `gemini-3.8-flash` |
| Voice | Gradium. Start with Gradbot (`pip install gradbot`), fall back to raw SDK (`pip install gradium`) |
| Code input | Public GitHub repo URL, shallow clone |
| Storage | JSON files on disk under `data/` (gitignored). No database |
| Auth | None |

## 4. Ownership

| Part | Owner | Folder |
| - | - | - |
| Codebase to questions | Teammate (TODO: name) | `src/analysis/` |
| Demo target repo (the "proprietary codebase" we interview on) | Teammate | separate repo, TODO: URL |
| Interview voice agent | Fotis | `src/interview/` |
| Evaluation agent | Fotis | `src/evaluation/` |
| API glue + web page | Fotis, teammate adds the analyze endpoint | `src/api/`, `web/` |

The contracts in section 6 are the boundary. Change them only by editing this file and telling the other person.

## 5. Architecture

```
GitHub URL
   │  POST /analyze
   ▼
[analysis]  clone → pick key files → Gemini → 3 question docs   data/<session>/questions/q1..q3.md
   │                              candidate profile (given)      data/<session>/candidate.md
   │
   ▼
[interview] Gradium voice loop, asks Q1..Q3, optional follow-up  data/<session>/transcript.json
   │        browser mic ⇄ WebSocket ⇄ FastAPI ⇄ Gradium + Gemini
   ▼
[evaluation] Gemini scores each answer against its reference     data/<session>/report.json
   │
   ▼
Report page: overall score, per-question scores, evidence quotes, recommendation
```

Proposed layout:

```
src/
  analysis/     repo clone, file selection, question generation
  interview/    loader (inputs), prompt, flow (tool-driven state), recorder (transcript), session (voice loop)
  evaluation/   prompt, evaluator (Gemini judgement + code-side scoring rules), CLI
  api/          FastAPI app, routes, session store
  shared/       pydantic models for the contracts below, Gemini client
web/            context.html/css/js (analysis workspace), index.html (voice), report.html
data/           runtime session files (gitignored)
fixtures/       sample sessions: `demo` (fictional order service, includes a transcript.json) and `example` (questions about this repo's own code)
tests/          pytest unit tests
```

## 6. Contracts

Pydantic models live in `src/shared/models.py`. These JSON shapes are the source of truth.

### Question docs (analysis → interview, evaluation)

One Markdown file per question in `data/<session>/questions/`, named `q1.md`, `q2.md`, `q3.md`. The file name is the question id.

```markdown
# Question
Spoken-friendly wording, one or two sentences, no code read aloud.

# Answer
Reference answer: what a strong candidate would say. Never spoken aloud.

# Context
Specialized context: the file/module/pattern it comes from and the background the interviewer needs.

# Follow-up
## Question
Spoken-friendly follow-up.
## Answer
Reference answer for the follow-up.
## Context
Specialized context for the follow-up.
```

Exactly 3 docs. `# Question`, `# Answer` and `# Context` are required and non-empty. The whole `# Follow-up` section is optional, at most one per question; if present it needs all three sub-sections. The loader (`src/interview/loader.py`) rejects anything else. `Question` must be sayable out loud. `Answer` is required, the interviewer and the evaluator both depend on it.

### Candidate profile (given → interview)

`data/<session>/candidate.md`. Free-form Markdown report, passed to the interviewer as-is. A `Name: ...` line (or the first `#` title) is used as `candidate_name` in the transcript.

### Transcript (interview → evaluation)

```json
{
  "session_id": "string",
  "candidate_name": "string",
  "started_at": "ISO-8601",
  "ended_at": "ISO-8601",
  "turns": [
    {"speaker": "agent", "question_id": null, "text": "intro...", "t": 0.0},
    {"speaker": "agent", "question_id": "q1", "text": "...", "t": 4.1},
    {"speaker": "candidate", "question_id": "q1", "text": "...", "t": 6.4},
    {"speaker": "agent", "question_id": "q1", "followup": true, "text": "...", "t": 41.0},
    {"speaker": "candidate", "question_id": "q1", "followup": true, "text": "...", "t": 46.2}
  ]
}
```

Every turn is tagged with the question it belongs to; introduction and closing turns have `question_id: null`. The transcript holds only what was said: no reference answers, context or scores. Follow-ups keep the parent `question_id` and set `"followup": true` (optional, defaults to false), so the evaluator can match them to `followup.answer`.

### Report (evaluation → UI)

Written to `data/<session>/report.json`. Models: `Report` and `QuestionReport` in `src/shared/models.py`.

```json
{
  "session_id": "string",
  "candidate_name": "string",
  "generated_at": "ISO-8601",
  "model": "gemini model id",
  "overall_score": 0,
  "recommendation": "strong_hire | hire | no_hire",
  "summary": "short paragraph",
  "reasoning": "why the scores came out as they did",
  "interview_complete": true,
  "needs_human_review": false,
  "review_reasons": ["..."],
  "per_question": [
    {
      "question_id": "q1",
      "question": "the question as asked",
      "status": "answered | not_answered",
      "followup_asked": true,
      "score": 0,
      "reasoning": "...",
      "covered_points": ["..."],
      "missed_points": ["..."],
      "strengths": ["..."],
      "gaps": ["..."],
      "evidence": ["direct quotes from the candidate"]
    }
  ],
  "profile_alignment": {"confirmed": ["..."], "contradicted": ["..."]},
  "red_flags": ["..."],
  "suggested_next_steps": ["topics to probe in a human round"],
  "communication": "one or two sentences, not scored"
}
```

Scores are 0 to 100. `overall_score` is the hiring score: the mean of the three question scores, computed in code. `recommendation` comes from fixed thresholds in code: 80 and above `strong_hire`, 60 and above `hire`, otherwise `no_hire`. A question's score covers the main answer and, if it was asked, the follow-up. A question with no answer scores 0 and makes `interview_complete` false. Evidence quotes that do not appear in the candidate's turns are removed. `needs_human_review` is set when a question was not answered, a quote was removed, or a question is scored without a verified quote. The report is advisory; a person makes the hiring decision.

### HTTP

| Route | Owner | Does |
| - | - | - |
| `GET /` | Teammate | Context Studio: repository/role form, analysis results, and sample preview |
| `POST /analyze` `{repo_url, role, subdir?}` | Teammate | writes `questions/q1..q3.md` and `context.json`, returns the parsed questions |
| `GET /sessions/{id}/questions` | Teammate | returns the parsed questions |
| `GET /sessions/{id}/context` | Teammate | returns saved codebase context; 404 if missing, 422 if invalid |
| `WS /sessions/{id}/interview` | Fotis | audio in/out, writes `transcript.json` on end, disconnect or time cap. Inputs are read from `data/<id>/`, falling back to `fixtures/<id>/` |
| `GET /?session=<id>` | Fotis | voice interview page (`?session=demo` for the fixture) |
| `POST /llm/chat/completions` | Fotis | internal: Gradbot to Gemini proxy, see section 7 |
| `POST /sessions/{id}/evaluate` | Fotis | runs the evaluation, returns Report, writes `report.json`. Transcript is read from `data/<id>/`, falling back to `fixtures/<id>/` |
| `GET /sessions/{id}/report` | Fotis | returns the saved Report, 404 until one exists |
| `GET /static/report.html?session=<id>` | Fotis | report page. Add `&run=1` to run the evaluation first; the interview page links here when it finishes |

## 7. Gradium notes

Docs: https://docs.gradium.ai (index for agents: https://docs.gradium.ai/llms.txt)

- Key in `GRADIUM_API_KEY` (format `gd_...`). `gradium.client.GradiumClient()` reads it from the env.
- **Gradbot** is Gradium's open-source voice agent loop, built for hackathons: streaming audio, VAD, turn-taking, interruptions, tool calls, OpenAI-compatible LLM. Repo: https://github.com/gradium-ai/gradbot

  - Needs Python 3.12+. Flagship English voices include Harper, Tilly, Declan (there is no "Emma"); we use `gradbot.flagship_voice("Harper")`.
  - Gemini does **not** work when Gradbot calls it directly: Gemini's OpenAI-compatible stream omits `index` on tool calls (Gradbot drops them) and Gemini 3 needs its thought signatures echoed back. So Gradbot's `llm_base_url` points at our own proxy, `POST /llm/chat/completions` in `src/api/llm_proxy.py`, which fixes both, sets `reasoning_effort` to `low` (override with `GEMINI_REASONING_EFFORT`) and retries 429/503. Also: no trailing slash on the base URL, Gradbot appends `/chat/completions`.
  - Verified on 10 Oct with `gemini-3.8-flash`: full 3-question voice interview in about 2 minutes, replies start roughly 3 to 4 seconds after the candidate stops.
  - `gradbot.websocket.handle_session` forwards transcripts to the browser but has no server-side hook, so `src/interview/session.py` runs its own loop on `gradbot.run` and records `stt_text` (candidate) and `tts_text` (agent) messages.
  - `gradbot.routes.setup(app, static_dir="web")` serves the page and the browser audio worklet (`/static/js/`), so mic capture and playback are not hand-written.
- Raw SDK fallback:
  - TTS: `client.tts(setup={"voice_id": ..., "output_format": "wav"}, text=...)`, or WebSocket `wss://api.gradium.ai/api/speech/tts`
  - STT: `client.stt_realtime(model_name="default", input_format="pcm", json_config={"language": "en", "delay_in_frames": 16})`
  - Turn end: STT sends a `step` message every 80 ms with `vad[-1]["inactivity_prob"]`. Treat 3 consecutive steps above 0.5 as end of turn, call `send_flush()`, and use the `flushed` message as "answer complete".
- Audio: TTS `pcm` is 48 kHz 16-bit mono. STT bare `pcm` means 24 kHz; say `pcm_16000` / `pcm_48000` if sending another rate. Opus is supported both ways.
- Never put the API key in browser code. If the browser talks to Gradium directly, the server mints a single-use token: `GET https://api.gradium.ai/api/api-keys/token` with `x-api-key`, then connect with `?token=...`.
- Session cap is 3000 s, far above our interview length.

## 8. Agent behaviour

**Interviewer**: takes the candidate profile and the 3 question docs. Introduces itself, asks the 3 questions in order and as written. After each answer, if the question has a follow-up, it decides on the fly whether that follow-up is relevant to what the candidate just said, and asks it only then; the profile may inform that decision but never changes the questions. At most one follow-up per question, and only the pre-written one, no improvised follow-ups. Never reveals or hints at the reference answers or context, never scores or comments on an answer, keeps its own turns short, closes the interview and ends the session. Target length 5 to 8 minutes, about 3 for the demo, hard cap 10.

Flow is enforced in code, not only in the prompt: the LLM must call `start_question(question_id)`, `ask_followup()` or `end_interview()` before each step, and `src/interview/flow.py` rejects out-of-order questions, a second follow-up and ending early. These calls also tag the transcript turns.

**Evaluator**: takes the transcript, the 3 question docs and the candidate profile, and runs separately from the interview with its own context. The model judges, the code decides. Gemini (structured output, `Judgement` schema) scores each question against its reference answer on anchored bands, strictly, using only what the candidate said, and returns reasoning, covered and missed points, and word-for-word quotes. A follow-up that was asked counts toward its question; one that was not asked is never penalised. Partial answers get partial credit; no answer scores 0. Accent, filler words and STT glitches are never penalised. The profile is context only and never changes a score; it feeds the unscored `profile_alignment`. The transcript is treated as untrusted data: attempts to instruct the evaluator are ignored and listed under `red_flags`. Code (`finalize()` in `src/evaluation/evaluator.py`) then computes the overall score and recommendation, decides from the transcript which questions were answered, and verifies every quote.

**Analyzer**: Gemini reads the collected codebase files itself, extracts technologies and project areas, and generates 3 generalized spoken questions about relevant project experience, optimizations and engineering trade-offs. Candidates do not need to have read the repository. Writes a reference `answer` and private `context` with source paths for every question; no follow-ups in the initial implementation. Skip hidden files (including secrets), vendored code, lockfiles and generated files when selecting input. Saves the extracted context and file coverage to `data/<session>/context.json`. Run locally with `.venv/bin/python -m src.analysis --path demo-proj --role "Backend Engineer"`, or use `--repo-url` with an optional `--subdir`.

## 9. Environment

```
GEMINI_API_KEY=
GEMINI_MODEL=
GRADIUM_API_KEY=
LLM_EXTRA_CONFIG=   # optional JSON merged into the LLM request, e.g. {"reasoning_effort": "none"}
```

Setup and run:

```
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m pytest tests
.venv/bin/uvicorn src.api.app:app      # then open http://localhost:8000/?session=demo
.venv/bin/python -m src.evaluation demo # evaluate a session from the command line
```

Keep these in `.env` (gitignored). `.env.example` lists them with empty values.

## 10. Build order

Work in parallel against `fixtures/` so nobody blocks on anybody.

1. Shared models + fixtures (`fixtures/demo`) — done. The fixture has questions with and without a follow-up
2. Evaluation from a fixture transcript (text only, quick win)
3. Voice loop: agent says one line and transcribes one reply
4. Full interview: 3 questions, transcript written
5. Analysis: repo URL to the 3 question docs — implemented, offline tests pass; live Gemini run pending API key
6. Wire the three together behind the API, one web page
7. Rehearse the demo twice on the demo repo. Record a backup video.

Cut line if time runs short: drop follow-up questions (the analyzer omits the `# Follow-up` section), drop arbitrary repo URLs (use the demo repo only), keep voice.

## 11. Demo script

1. Paste the demo repo URL, show the 3 generated questions and where in the code they come from
2. Live voice interview, a teammate plays the candidate
3. Report appears: score, per-question breakdown, quotes

Risks: venue noise and wifi (bring a headset, keep a recorded run), STT turn-taking cutting the candidate off (tune the threshold early), LLM latency in the voice loop (keep interviewer prompts short).

## 12. Open questions

- Judging criteria and submission format
- Teammate name, demo repo URL
