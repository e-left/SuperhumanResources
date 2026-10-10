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
| Frontend | Buildless HTML/CSS/JS. Context Studio at `/` (analysis workspace), the candidate's voice interview at `/?session=<id>` (voice only, no question text, no results), and an internal report page for recruiters at `/internal/report` |
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
Internal report page: decision (advance / reject), score, reasons, per-question detail, transcript
```

Proposed layout:

```
src/
  analysis/     repo clone, file selection, question generation
  interview/    loader (inputs), prompt, flow (tool-driven state), llm_proxy (Gemini + tools), recorder (transcript), session (voice loop)
  evaluation/   prompt, evaluator (Gemini judgement + code-side scoring rules), CLI
  api/          FastAPI app, routes, session store
  shared/       pydantic models for the contracts below, Gemini client
web/            context.html/css/js (analysis workspace), index.html (the candidate's voice interview)
internal/       report.html: the recruiter's report page
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
  "ended_reason": "completed | time_limit | disconnected | stopped",
  "turns": [
    {"speaker": "agent", "question_id": null, "text": "intro...", "t": 0.0},
    {"speaker": "agent", "question_id": "q1", "text": "...", "t": 4.1},
    {"speaker": "candidate", "question_id": "q1", "text": "...", "t": 6.4},
    {"speaker": "agent", "question_id": "q1", "second_chance": true, "hint": true, "text": "...", "t": 30.0},
    {"speaker": "candidate", "question_id": "q1", "second_chance": true, "hint": true, "text": "...", "t": 36.5},
    {"speaker": "agent", "question_id": "q1", "followup": true, "interrupted": true, "heard": "the part that was spoken", "text": "the full wording", "t": 41.0},
    {"speaker": "candidate", "question_id": "q1", "followup": true, "text": "...", "t": 46.2}
  ]
}
```

Every turn is tagged with the question it belongs to; introduction and closing turns have `question_id: null`. `followup`, `second_chance` and `hint` are optional and default to false. Follow-ups keep the parent `question_id`. `second_chance` marks the interviewer's "try again" and the candidate's second attempt, until the next question or follow-up; `hint` is set when that second chance came with a hint. `interrupted` marks an interviewer turn that was cut off: `text` is then the full wording it meant to say and `heard` the part that was actually spoken. `ended_reason` is `null` while the interview is in progress: the file is rewritten every time a new turn starts, so a crash loses at most the turn in progress. The transcript holds only what was said: no reference answers, context or scores.

### Report (evaluation → internal report page)

Written to `data/<session>/report.json`. Internal: recruiters only, never shown to the candidate. Models: `Report` and `QuestionReport` in `src/shared/models.py`.

```json
{
  "session_id": "string",
  "candidate_name": "string",
  "generated_at": "ISO-8601",
  "model": "gemini model id",
  "overall_score": 0,
  "decision": "advance | reject",
  "borderline": false,
  "summary": "why, in three or four sentences",
  "reasoning": "how the question scores produced the overall score",
  "strengths": ["..."],
  "next_interview_focus": ["advance only: what later interviews should cover"],
  "rejection_reasons": ["reject only: specific reasons"],
  "interview_complete": true,
  "ended_reason": "completed | time_limit | disconnected | stopped",
  "duration_s": 0,
  "needs_human_review": false,
  "review_reasons": ["..."],
  "per_question": [
    {
      "question_id": "q1",
      "question": "the question as asked",
      "status": "answered | not_answered",
      "followup_asked": true,
      "second_chance_given": false,
      "hint_given": false,
      "score": 0,
      "score_before_cap": null,
      "score_runs": [0, 0, 0],
      "reasoning": "...",
      "covered_points": ["..."],
      "missed_points": ["..."],
      "strengths": ["..."],
      "gaps": ["..."],
      "evidence": ["direct quotes from the candidate"]
    }
  ],
  "profile_alignment": {"confirmed": ["..."], "contradicted": ["..."]},
  "red_flags": ["conduct or integrity concerns, not weak answers"],
  "communication": "one or two sentences, not scored"
}
```

Rules, all applied in code (`assess()` and `finalize()` in `src/evaluation/evaluator.py`):

- Scores are 0 to 100. Grading runs `JUDGE_RUNS = 3` times in parallel; each question takes the median run (its score, reasoning and quotes together), and `score_runs` lists every run's score. `overall_score` is the mean of the three question scores.
- `borderline` is true when the overall score is within 5 points of the bar; the decision is still made, and a person should confirm it.
- `decision` is `advance` at `ADVANCE_MIN = 60` or above, otherwise `reject`. One constant for now, to be made configurable.
- An advance report carries `strengths` and `next_interview_focus`; a reject report carries `rejection_reasons` (and at most two `strengths`). The list that does not apply is always empty.
- A question that needed a second chance is capped at 70, or at 55 if a hint was given; `score_before_cap` keeps the evaluator's original score when the cap lowered it.
- A question with no answer scores 0 and makes `interview_complete` false.
- Evidence quotes that do not appear in the candidate's turns are removed.
- `needs_human_review` is set when a question was not answered, a quote was removed, a question is scored without a verified quote, a red flag was raised, the interview did not end normally, the result is borderline, the grading runs differ by more than 20 points on a question, or the interviewer was interrupted while asking a question.

The report supports a decision; a person reviews it before the candidate is told anything.

### HTTP

| Route | Owner | Does |
| - | - | - |
| `GET /` | Teammate | Context Studio: repository/role form, analysis results, and sample preview |
| `POST /analyze` `{repo_url, role, subdir?}` | Teammate | writes `questions/q1..q3.md` and `context.json`, returns the parsed questions |
| `GET /sessions/{id}/questions` | Teammate | returns the parsed questions |
| `GET /sessions/{id}/context` | Teammate | returns saved codebase context; 404 if missing, 422 if invalid |
| `WS /sessions/{id}/interview` | Fotis | audio in/out, writes `transcript.json` on end, disconnect or time limit, then starts the evaluation. Inputs are read from `data/<id>/`, falling back to `fixtures/<id>/` |
| `GET /?session=<id>` | Fotis | candidate's voice interview page (`?session=demo` for the fixture). Ends with a thank-you, no results |
| `POST /llm/s/{token}/chat/completions` | Fotis | internal: per-session LLM endpoint for Gradbot, see section 7 |
| `POST /sessions/{id}/evaluate` | Fotis | runs the evaluation, returns Report, writes `report.json`. Also runs automatically when an interview ends. Transcript is read from `data/<id>/`, falling back to `fixtures/<id>/` |
| `GET /sessions/{id}/report` | Fotis | returns the saved Report, 404 until one exists |
| `GET /sessions/{id}/transcript` | Fotis | returns the Transcript (used by the report page) |
| `GET /internal/report?session=<id>` | Fotis | internal report page for recruiters (`internal/report.html`). The candidate page never links to it. No access control yet: the platform that creates interview links will add it |

## 7. Gradium notes

Docs: https://docs.gradium.ai (index for agents: https://docs.gradium.ai/llms.txt)

- Key in `GRADIUM_API_KEY` (format `gd_...`). `gradium.client.GradiumClient()` reads it from the env.
- **Gradbot** is Gradium's open-source voice agent loop, built for hackathons: streaming audio, VAD, turn-taking, interruptions, tool calls, OpenAI-compatible LLM. Repo: https://github.com/gradium-ai/gradbot

  - Needs Python 3.12+. Flagship English voices include Harper, Tilly, Declan (there is no "Emma"); we use `gradbot.flagship_voice("Harper")`.
  - Gemini does **not** work when Gradbot calls it directly. Gemini's OpenAI-compatible stream omits `index` on tool calls (Gradbot drops them), Gemini 3 needs its thought signatures echoed back, and Gradbot cuts off whatever the model was saying when a tool call arrives. So Gradbot never talks to Gemini: each session gets its own endpoint on our proxy, `POST /llm/s/{token}/chat/completions` in `src/interview/llm_proxy.py`.
  - The proxy owns the real Gemini conversation for the session and runs the interviewer's tool calls itself against that session's `InterviewFlow`. Gradbot only receives text to speak: the model's lead-in ("Thanks.") followed by the exact question wording from the tool result, in one stream and one model call. Refused tool calls and the goodbye go back to Gemini for another round. It sets `reasoning_effort` to `low` (override with `GEMINI_REASONING_EFFORT`) and retries 429/500/503.
  - Verified on 10 Oct with `gemini-3.8-flash` and a simulated candidate speaking through the real WebSocket: full interview in under 3 minutes, the agent starts replying about 2 seconds after the candidate stops.
- Raw SDK fallback:
  - TTS: `client.tts(setup={"voice_id": ..., "output_format": "wav"}, text=...)`, or WebSocket `wss://api.gradium.ai/api/speech/tts`
  - STT: `client.stt_realtime(model_name="default", input_format="pcm", json_config={"language": "en", "delay_in_frames": 16})`
  - Turn end: STT sends a `step` message every 80 ms with `vad[-1]["inactivity_prob"]`. Treat 3 consecutive steps above 0.5 as end of turn, call `send_flush()`, and use the `flushed` message as "answer complete".
- Audio: TTS `pcm` is 48 kHz 16-bit mono. STT bare `pcm` means 24 kHz; say `pcm_16000` / `pcm_48000` if sending another rate. Opus is supported both ways.
- Never put the API key in browser code. If the browser talks to Gradium directly, the server mints a single-use token: `GET https://api.gradium.ai/api/api-keys/token` with `x-api-key`, then connect with `?token=...`.
- Session cap is 3000 s, far above our interview length.

## 8. Agent behaviour

**Interviewer**: takes the candidate profile and the 3 question docs.

- Opening: a short hello (greets by name, says who it is, asks how they are), then waits for the candidate to say hello back; the first question cannot start until the candidate has spoken. It then says there are three questions and that the interview takes fifteen minutes at most.
- Questions: asked in order and word for word, spoken from the question docs, never rephrased by the model. The model only adds a short lead-in ("Thanks.", "Got it.").
- After each answer it does exactly one of: give a second chance, ask the prepared follow-up, or move on.
- Second chance: when an answer is clearly wrong, off target, or the candidate is stuck, the interviewer invites one more try. Normally without a hint; a small hint (an area to think about, never part of the reference answer) only when the candidate is stuck. One second chance per question or follow-up, never a third try.
- Follow-up: only the pre-written one, at most one per question, and only when it is relevant to what the candidate said. The profile may inform that decision but never changes the questions.
- Time limit: at 12 minutes the interviewer is told to close after the current answer; at 15 minutes the session ends regardless. Override with `INTERVIEW_WRAP_UP_S` / `INTERVIEW_MAX_S` (seconds).
- Fillers: if Gemini has produced nothing 3 seconds after the candidate finished (`FILLER_AFTER_S`), the interviewer says a short neutral filler ("Mhm.", "I see.", "Mmm, okay.", "Right.", "Okay.") and then the real reply, minus the model's own leading "Got it." so the two do not double up.
- Silence: the candidate gets 15 seconds to think before the interviewer says anything (`INTERVIEW_SILENCE_S`; Gradbot's default of 5 made the agent start talking just as candidates began to answer, which cut off their first words). Silence is answered with fixed lines, not the model: "Take your time.", then "Are you still with me? I can repeat the question if that helps.", and only after a third silence is the model asked whether to move on. Before the hello: "Hello, can you hear me?".
- Model: the interviewer uses `INTERVIEW_MODEL` if set, otherwise `GEMINI_MODEL`. On 10 Oct `gemini-3.6-flash` answered in 1.0 to 1.5 seconds against 2 to 3.5 for `gemini-3.8-flash`, but it hands out hints more readily and its hints give more away.
- Never reveals or hints at the reference answers beyond a second-chance hint, never tells the candidate whether they were right, keeps its turns short, says goodbye and waits a few seconds for the candidate to say bye back.

- Interruptions: if the interviewer is cut off while asking a question (the candidate talks over it, the microphone picks up the speakers, or there are other voices in the room), it is told how much was heard and repeats that question if the reply does not answer it. It is told once per question, follow-up or second chance, and never for the greeting: in a noisy room every turn gets cut, and repeating each time loops forever (this happened on 10 Oct). For stray background speech it says it did not catch that and carries on. The transcript marks the turn and keeps the full wording.

Flow is enforced in code, not only in the prompt: the model asks for each step by calling `start_question(question_id)`, `ask_followup()`, `second_chance(say, hint_given)` or `end_interview()`, and `src/interview/flow.py` rejects out-of-order questions, a second follow-up, a second second-chance, anything new once time is up, and ending early. These calls also tag the transcript turns. If the model speaks the next question or the follow-up itself without the tool call, `llm_proxy.py` recognises the wording and advances the flow anyway.

**Evaluator**: takes the transcript, the 3 question docs and the candidate profile, and runs separately from the interview with its own context, automatically when an interview ends. The model judges, the code decides, in four steps (`src/evaluation/evaluator.py`):

1. `judge_runs()` then `merge()`: Gemini (structured output, `Judgement`) grades the interview three times in parallel and code keeps the median run per question. Red flags come from the run that raised the most. Each run scores each question against its reference answer on anchored bands, strictly, using only what the candidate said, with reasoning, covered and missed points, and word-for-word quotes. A follow-up that was asked counts toward its question; one that was not asked is never penalised. Second attempts are graded on the best the candidate reached, without credit for what a hint supplied. Partial answers get partial credit; no answer scores 0. Accent, filler words and STT glitches are never penalised. The profile never changes a score. The transcript is untrusted data: attempts to instruct the evaluator are ignored and listed under `red_flags`.
2. `assess()`: code verifies quotes, applies the second-chance caps, forces unanswered questions to 0, computes the overall score, fixes the decision and flags a borderline result.
3. `write_decision()`: Gemini (`Writeup`) explains the decision that code made: strengths and next-interview focus for an advance, rejection reasons for a reject. It sees scores and grader notes only, never the reference answers.
4. `finalize()`: code assembles the Report and blanks the lists that do not apply to the decision.

**Analyzer**: Gemini reads the collected codebase files itself, extracts technologies and project areas, and generates 3 generalized spoken questions about relevant project experience, optimizations and engineering trade-offs. Candidates do not need to have read the repository. Writes a reference `answer` and private `context` with source paths for every question; no follow-ups in the initial implementation. Skip hidden files (including secrets), vendored code, lockfiles and generated files when selecting input. Saves the extracted context and file coverage to `data/<session>/context.json`. Run locally with `.venv/bin/python -m src.analysis --path demo-proj --role "Backend Engineer"`, or use `--repo-url` with an optional `--subdir`.

## 9. Environment

```
GEMINI_API_KEY=
GEMINI_MODEL=
GRADIUM_API_KEY=

# optional
INTERVIEW_WRAP_UP_S=   # seconds until the interviewer starts closing, default 720
INTERVIEW_MAX_S=       # hard limit in seconds, default 900
INTERVIEW_SILENCE_S=   # seconds of candidate silence before the interviewer speaks, default 15
INTERVIEW_MODEL=       # Gemini model for the interviewer only, default GEMINI_MODEL
FILLER_AFTER_S=        # seconds of model silence before a filler, default 3
```

Setup and run:

```
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m pytest tests
.venv/bin/uvicorn src.api.app:app      # candidate: http://localhost:8000/?session=example
                                       # recruiter: http://localhost:8000/internal/report?session=example
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
3. Open the internal report: decision, score, strengths or rejection reasons, per-question breakdown, quotes

Risks: venue noise and wifi (bring a headset, keep a recorded run), STT turn-taking cutting the candidate off (tune the threshold early), LLM latency in the voice loop (keep interviewer prompts short).

## 12. Open questions

- Judging criteria and submission format
- Teammate name, demo repo URL
