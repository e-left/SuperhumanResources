# SuperhumanResources — CONTEXT

Shared context for humans and coding agents. Read this first. Update it when a decision changes.

## 1. What we are building

An AI HR platform that runs a technical interview grounded in a company's own code.

1. **Analyze**: take a GitHub repo URL, read the codebase, produce 3 interview questions specific to it.
2. **Interview**: a voice agent (Gradium) asks the candidate those 3 questions and records the answers.
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
| Language | Python 3.10+ (Gradium SDK requirement) |
| Backend | FastAPI, one process |
| Frontend | Single thin browser page: mic capture, audio playback, shows questions and final report |
| LLM | Gemini for all three agents. Model id in `GEMINI_MODEL` env var. TODO: confirm which model the event credits cover |
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
[analysis]  clone → pick key files → Gemini → QuestionSet        data/<session>/questions.json
   │
   ▼
[interview] Gradium voice loop, asks Q1..Q3, one follow-up max   data/<session>/transcript.json
   │        browser mic ⇄ WebSocket ⇄ FastAPI ⇄ Gradium + Gemini
   ▼
[evaluation] Gemini scores each answer against its rubric        data/<session>/report.json
   │
   ▼
Report page: overall score, per-question scores, evidence quotes, recommendation
```

Proposed layout:

```
src/
  analysis/     repo clone, file selection, question generation
  interview/    voice session, interviewer prompt, transcript capture
  evaluation/   scoring prompt, report builder
  api/          FastAPI app, routes, session store
  shared/       pydantic models for the contracts below, Gemini client
web/            index.html + JS (mic, playback, report view)
data/           runtime session files (gitignored)
fixtures/       sample questions.json and transcript.json for working in parallel
```

## 6. Contracts

Pydantic models live in `src/shared/models.py`. These JSON shapes are the source of truth.

### QuestionSet (analysis → interview, evaluation)

```json
{
  "session_id": "string",
  "repo_url": "https://github.com/org/repo",
  "repo_summary": "2-3 sentences on what the codebase does and its stack",
  "role": "e.g. Backend Engineer",
  "questions": [
    {
      "id": "q1",
      "question": "Spoken-friendly wording, one or two sentences, no code read aloud",
      "context": "Why this question: the file/module/pattern it comes from",
      "source_files": ["path/in/repo.py"],
      "rubric": {
        "strong": ["points a strong answer covers"],
        "weak": ["signs of a shallow or wrong answer"]
      }
    }
  ]
}
```

Exactly 3 questions. `question` must be sayable out loud. `rubric` is required, the evaluator depends on it.

### Transcript (interview → evaluation)

```json
{
  "session_id": "string",
  "candidate_name": "string",
  "started_at": "ISO-8601",
  "ended_at": "ISO-8601",
  "turns": [
    {"speaker": "agent", "question_id": "q1", "text": "...", "t": 0.0},
    {"speaker": "candidate", "question_id": "q1", "text": "...", "t": 6.4}
  ]
}
```

Every turn is tagged with the question it belongs to. Follow-ups keep the parent `question_id`.

### Report (evaluation → UI)

```json
{
  "session_id": "string",
  "overall_score": 0,
  "recommendation": "strong_hire | hire | no_hire",
  "summary": "short paragraph",
  "per_question": [
    {
      "question_id": "q1",
      "score": 0,
      "strengths": ["..."],
      "gaps": ["..."],
      "evidence": ["direct quotes from the candidate"]
    }
  ]
}
```

Scores are 0 to 100. `overall_score` is the mean of the three. Every score needs at least one evidence quote.

### HTTP

| Route | Owner | Does |
| - | - | - |
| `POST /analyze` `{repo_url, role}` | Teammate | returns QuestionSet, writes `questions.json` |
| `GET /sessions/{id}/questions` | Teammate | returns QuestionSet |
| `WS /sessions/{id}/interview` | Fotis | audio in/out, writes `transcript.json` on end |
| `POST /sessions/{id}/evaluate` | Fotis | returns Report, writes `report.json` |
| `GET /sessions/{id}/report` | Fotis | returns Report |

## 7. Gradium notes

Docs: https://docs.gradium.ai (index for agents: https://docs.gradium.ai/llms.txt)

- Key in `GRADIUM_API_KEY` (format `gd_...`). `gradium.client.GradiumClient()` reads it from the env.
- **Gradbot** is Gradium's open-source voice agent loop, built for hackathons: streaming audio, VAD, turn-taking, interruptions, tool calls, OpenAI-compatible LLM. Repo: https://github.com/gradium-ai/gradbot

  ```python
  voice = gradbot.flagship_voice("Emma")
  config = gradbot.SessionConfig(voice_id=voice.voice_id, instructions="...", language=voice.language)
  input_handle, output_handle = await gradbot.run(
      session_config=config,
      input_format=gradbot.AudioFormat.OggOpus,
      output_format=gradbot.AudioFormat.OggOpus,
  )
  ```

  TODO: confirm from the Gradbot README how to point its LLM at Gemini. Gemini's OpenAI-compatible base URL is `https://generativelanguage.googleapis.com/v1beta/openai/`.
- Raw SDK fallback:
  - TTS: `client.tts(setup={"voice_id": ..., "output_format": "wav"}, text=...)`, or WebSocket `wss://api.gradium.ai/api/speech/tts`
  - STT: `client.stt_realtime(model_name="default", input_format="pcm", json_config={"language": "en", "delay_in_frames": 16})`
  - Turn end: STT sends a `step` message every 80 ms with `vad[-1]["inactivity_prob"]`. Treat 3 consecutive steps above 0.5 as end of turn, call `send_flush()`, and use the `flushed` message as "answer complete".
- Audio: TTS `pcm` is 48 kHz 16-bit mono. STT bare `pcm` means 24 kHz; say `pcm_16000` / `pcm_48000` if sending another rate. Opus is supported both ways.
- Never put the API key in browser code. If the browser talks to Gradium directly, the server mints a single-use token: `GET https://api.gradium.ai/api/api-keys/token` with `x-api-key`, then connect with `?token=...`.
- Session cap is 3000 s, far above our interview length.

## 8. Agent behaviour

**Interviewer**: introduces itself, asks the 3 questions in order, at most one follow-up per question when the answer is thin, never reveals the rubric or hints at the answer, keeps its own turns short, closes the interview and ends the session. Target length 5 to 8 minutes, about 3 for the demo.

**Evaluator**: scores only what the candidate said. Uses the rubric per question. Quotes evidence. Does not penalise accent, filler words or STT glitches. Returns the Report JSON and nothing else (use Gemini structured output).

**Analyzer**: questions must be answerable in speech, tied to real design decisions in the repo (architecture, trade-offs, failure modes), not trivia about file names. Skip vendored code, lockfiles and generated files when selecting input.

## 9. Environment

```
GEMINI_API_KEY=
GEMINI_MODEL=
GRADIUM_API_KEY=
```

Keep these in `.env` (gitignored). Add a `.env.example` with empty values.

## 10. Build order

Work in parallel against `fixtures/` so nobody blocks on anybody.

1. Shared models + fixtures (`questions.json`, `transcript.json`) — first, both people need them
2. Evaluation from a fixture transcript (text only, quick win)
3. Voice loop: agent says one line and transcribes one reply
4. Full interview: 3 questions, transcript written
5. Analysis: repo URL to QuestionSet
6. Wire the three together behind the API, one web page
7. Rehearse the demo twice on the demo repo. Record a backup video.

Cut line if time runs short: drop follow-up questions, drop arbitrary repo URLs (use the demo repo only), keep voice.

## 11. Demo script

1. Paste the demo repo URL, show the 3 generated questions and where in the code they come from
2. Live voice interview, a teammate plays the candidate
3. Report appears: score, per-question breakdown, quotes

Risks: venue noise and wifi (bring a headset, keep a recorded run), STT turn-taking cutting the candidate off (tune the threshold early), LLM latency in the voice loop (keep interviewer prompts short).

## 12. Open questions

- Judging criteria and submission format
- Teammate name, demo repo URL
- Gemini model id covered by the event credits
- Gradbot to Gemini configuration
