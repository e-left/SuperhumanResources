"""Local OpenAI-compatible LLM endpoint that Gradbot talks to instead of Gemini.

Why it exists. Gradbot and Gemini's OpenAI-compatible endpoint do not get along
on tool calls: Gemini omits `index` on streamed tool calls (Gradbot drops
them), Gemini 3 wants its thought signatures echoed back (Gradbot does not),
and Gradbot cuts off whatever the model was saying when a tool call arrives.
A tool round trip through Gradbot also costs a second model call, which is a
long silence on a voice call.

What it does. For each interview session the proxy owns the real conversation
with Gemini and resolves the interviewer's tool calls itself, against that
session's InterviewFlow. Gradbot only ever sees plain text to speak:

    Gemini:  "Thanks."  + start_question(q2)
    proxy:   runs the tool, appends the exact question wording
    Gradbot: "Thanks. <question, word for word>"   (one stream, one model call)

When a tool call is refused, or needs words only the model can produce (the
goodbye after end_interview), the proxy asks Gemini again with the tool result.

Two more things happen here because this is where the conversation lives:
- Fillers. If Gemini has said nothing a couple of seconds after the candidate
  finished, the proxy speaks a short filler ("Mhm.") first so there is no dead
  air, then continues with the real reply in the same stream.
- Time limit. Once the session marks the flow as out of time, the next request
  carries a note telling the model to close the interview.
- Interruptions. The proxy knows what the interviewer meant to say; the session
  tells it what was actually spoken. If a turn was cut off, the model is told so
  it can repeat the question, and the transcript keeps the full wording.
- Skipped tool calls. If the model speaks a question itself instead of calling
  the tool, the proxy recognises the wording and advances the flow anyway.
"""

import asyncio
import json
import logging
import os
import random
import re
import time
from typing import Callable

import fastapi
import fastapi.responses
import httpx

from src.interview.flow import InterviewFlow

logger = logging.getLogger("interview")
router = fastapi.APIRouter()

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
RETRY_STATUS = {429, 500, 503}
MAX_ATTEMPTS = 3
# Model calls allowed for one spoken turn (a refused tool call needs another).
MAX_ROUNDS = 4
# Tools whose successful result is the literal text to speak next.
SAY_TOOLS = {"start_question", "ask_followup", "second_chance"}
INTERVIEW_TOOLS = SAY_TOOLS | {"end_interview"}

# Spoken when Gemini is slow to answer the candidate. Neutral on purpose: the
# interviewer must not signal whether an answer was right.
FILLERS = ["Mhm.", "I see.", "Mmm, okay.", "Right.", "Okay."]
FILLER_AFTER_S = 3.0  # override with env FILLER_AFTER_S
# After a filler, the model's own opening acknowledgement would double up
# ("Mhm. Got it. ..."), so a leading one is dropped.
_LEADING_ACK = re.compile(
    r"^\s*(got it|thanks|thank you|okay|ok|understood|i see|right|mhm|alright|great|sure)"
    r"[.!](\s+|$)",
    re.IGNORECASE,
)
# What the interviewer says when the candidate stays silent, in order. Fixed
# lines: instant, and a silent candidate can never make the model skip ahead.
WAITING_FOR_HELLO = ["Hello, can you hear me?", "Whenever you're ready, just say hello."]
WAITING_FOR_ANSWER = [
    "Take your time.",
    "Are you still with me? I can repeat the question if that helps.",
]
LONG_SILENCE_NOTE = (
    "[Note from the interview system, not from the candidate: the candidate has been silent "
    "for a long time. Ask whether they would like to move on. If they were already asked, "
    "move on yourself.]"
)
# Gradbot's own pushes that are not something the candidate said.
NOT_AN_UTTERANCE = {"", "...", "[start]"}
TIME_UP_NOTE = (
    "[Note from the interview system, not from the candidate: the time limit has been "
    "reached. Do not ask anything else and do not give a second chance. Call end_interview "
    "now and, in the same response, tell the candidate kindly that the time is up, thank "
    "them and say goodbye.]"
)

INTERRUPTED_NOTE = (
    "[Note from the interview system, not from the candidate: you were cut off while asking "
    "the current question. The candidate heard only: \"{heard}\". If what they say now does "
    "not answer it, say the current question again in full, once, without calling a tool.]"
)
# A reply counts as cut off when less than this share of it was spoken.
CUT_BELOW = 0.85
# Replies shorter than this (normalised characters) are never treated as cut off.
CUT_MIN_LENGTH = 20
# Share of a question's distinctive words that must appear in a reply for the
# proxy to conclude the model asked that question without its tool call.
SPOKEN_QUESTION_OVERLAP = 0.7


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _asks(reply: str, question: str) -> bool:
    """True when `reply` contains the wording of `question`, allowing light rephrasing."""
    words = {w for w in _normalise(question).split() if len(w) > 3}
    if len(words) < 4:
        return False
    said = set(_normalise(reply).split())
    return len(words & said) / len(words) >= SPOKEN_QUESTION_OVERLAP


_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))


class Conversation:
    """The Gemini-side history of one interview, including tool calls."""

    def __init__(self, flow: InterviewFlow):
        self.flow = flow
        self.history: list[dict] = []  # everything after the system message
        self._time_note_sent = False
        self._last_filler: str | None = None
        # What the interviewer meant to say in its latest turn, and how much of it
        # was actually spoken (the session feeds `heard` from Gradbot's TTS text).
        self.last_reply = ""
        self.heard = ""
        # The things asked (question / follow-up / second chance) for which the model
        # was already told it had been cut off. Told once each: in a noisy room every
        # turn gets cut, and repeating every time would loop forever.
        self._cut_notes: set[tuple] = set()
        # True when the latest reply carried a question (the tool's wording).
        self._reply_asked = False
        # Silence prompts received in a row since the candidate last spoke.
        self._silences = 0
        # Called with (intended, heard) when a turn turns out to have been cut off.
        self.on_cut: Callable[[str, str], None] | None = None

    def begin_reply(self) -> None:
        self.last_reply = ""
        self.heard = ""
        self._reply_asked = False

    def silence_reply(self) -> str | None:
        """A fixed line for a silence prompt, or None to let the model handle it."""
        flow = self.flow
        if flow.ended or flow.time_up:
            return None
        lines = WAITING_FOR_ANSWER if flow.candidate_spoke else WAITING_FOR_HELLO
        if self._silences <= len(lines):
            return lines[self._silences - 1]
        # Before the hello there is nothing to move on to: keep waiting.
        return None if flow.candidate_spoke else lines[-1]

    def say_directly(self, text: str) -> None:
        """Record a fixed line spoken without asking the model."""
        self.begin_reply()
        self.note_spoken(text)
        self.history.append({"role": "assistant", "content": text})

    def note_spoken(self, text: str) -> None:
        """The proxy sent this text to be spoken."""
        self.last_reply += text

    def note_heard(self, text: str) -> None:
        """The session saw this text actually being spoken."""
        self.heard = f"{self.heard} {text}".strip()

    def reply_was_cut(self) -> bool:
        intended, heard = _normalise(self.last_reply), _normalise(self.heard)
        return len(intended) >= CUT_MIN_LENGTH and len(heard) < CUT_BELOW * len(intended)

    def add_user(self, text: str | None) -> bool:
        """Record what Gradbot pushed. Returns True if the candidate actually said something."""
        spoke = (text or "").strip() not in NOT_AN_UTTERANCE
        # Gradbot pushes "" or "..." when the candidate stays silent.
        content = text or "..."
        silent = (text or "").strip() in ("", "...")
        self._silences = self._silences + 1 if silent else 0
        if silent and self.flow.candidate_spoke and self._silences > len(WAITING_FOR_ANSWER):
            content = f"{content}\n\n{LONG_SILENCE_NOTE}"
        if self.reply_was_cut():
            intended, heard = " ".join(self.last_reply.split()), self.heard
            logger.info("the interviewer was cut off after %r", heard)
            if self.on_cut is not None:
                self.on_cut(intended, heard)
            # Only a question is worth repeating, and only once. A greeting or a
            # passing remark that got cut off is left alone.
            flow = self.flow
            asked = (flow.question_id, flow.in_followup, flow.in_second_chance)
            if spoke and self._reply_asked and asked not in self._cut_notes:
                self._cut_notes.add(asked)
                content = f"{content}\n\n{INTERRUPTED_NOTE.format(heard=heard)}"
            self.last_reply = self.heard = ""  # reported once
        if self.flow.time_up and not self.flow.ended and not self._time_note_sent:
            self._time_note_sent = True
            content = f"{content}\n\n{TIME_UP_NOTE}"
        self.history.append({"role": "user", "content": content})
        return spoke

    def next_filler(self) -> str:
        """A filler, never the same one twice in a row."""
        filler = random.choice([f for f in FILLERS if f != self._last_filler])
        self._last_filler = filler
        return filler

    def resolve(self, text: str, calls: list[dict]) -> str | None:
        """Record the model's reply, run its tool calls, return wording to append.

        Returns the exact wording to speak when the reply was a single,
        accepted start_question / ask_followup / second_chance, and "" when the
        turn is complete as it is. Returns None when there is nothing to
        append: if `calls` is non-empty the model must be asked again with the
        tool results now in the history.
        """
        if not calls:
            if text:  # empty when Gemini failed; nothing was said
                self.history.append({"role": "assistant", "content": text})
                self._catch_spoken_question(text)
                # Repeating the current question on request also counts as asking it.
                current = self.flow.current
                if current is not None and _asks(text, current.question):
                    self._reply_asked = True
            return None
        self.history.append({"role": "assistant", "content": text or None, "tool_calls": calls})
        say = None
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            result = self.flow.handle(name, args)
            logger.info("tool %s(%s) -> %s", name, args, result)
            self.history.append(
                {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)}
            )
            if name in SAY_TOOLS and result.get("ok"):
                say = result["say"]
            elif name == "end_interview" and result.get("ok") and text and len(calls) == 1:
                # The model already said its goodbye in this response: nothing to
                # add and no second model call needed.
                return ""
        if say is None or len(calls) != 1:
            return None
        self._reply_asked = True
        self.history.append({"role": "assistant", "content": say})
        return say


    def _catch_spoken_question(self, text: str) -> None:
        """The model asked a question itself, without the tool: keep the flow in step."""
        flow = self.flow
        if flow.ended:
            return
        upcoming = flow.next_question
        if upcoming is not None and _asks(text, upcoming.question):
            result = flow.start_question(upcoming.id)
            self._reply_asked = bool(result.get("ok"))
            logger.warning("model asked %s without start_question -> %s", upcoming.id, result)
        elif flow.followup_available and _asks(text, flow.current.followup.question):
            result = flow.ask_followup()
            self._reply_asked = bool(result.get("ok"))
            logger.warning("model asked the follow-up without ask_followup -> %s", result)


_conversations: dict[str, Conversation] = {}


def register(token: str, flow: InterviewFlow) -> Conversation:
    conversation = Conversation(flow)
    _conversations[token] = conversation
    return conversation


def unregister(token: str) -> None:
    _conversations.pop(token, None)


def _chunk(model: str, delta: dict, finish: str | None = None) -> str:
    payload = {
        "id": "interview",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload)}\n\n"


async def _open_gemini(body: dict) -> httpx.Response:
    """POST to Gemini with streaming, retrying transient errors before any output."""
    headers = {
        "Authorization": f"Bearer {os.environ.get('GEMINI_API_KEY', '')}",
        "Content-Type": "application/json",
    }
    url = f"{GEMINI_OPENAI_BASE_URL}/chat/completions"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = await _client.send(
            _client.build_request("POST", url, headers=headers, json=body), stream=True
        )
        if response.status_code not in RETRY_STATUS or attempt == MAX_ATTEMPTS:
            return response
        logger.warning("Gemini returned %s, retrying (%d)", response.status_code, attempt)
        await response.aclose()
        await asyncio.sleep(0.4 * attempt)
    return response


def _collect_calls(calls: dict[int, dict], deltas: list[dict]) -> None:
    """Merge streamed tool-call fragments (Gemini usually sends each call whole)."""
    for position, delta in enumerate(deltas):
        call = calls.setdefault(
            delta.get("index", position),
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        call["id"] = delta.get("id") or call["id"]
        function = delta.get("function") or {}
        call["function"]["name"] += function.get("name") or ""
        call["function"]["arguments"] += function.get("arguments") or ""
        if delta.get("extra_content"):  # Gemini's thought signature, must be sent back
            call["extra_content"] = delta["extra_content"]


async def _read_gemini(body: dict, queue: asyncio.Queue) -> None:
    """Stream one Gemini reply into the queue as ("delta", dict) items, then ("end", ok)."""
    ok = False
    try:
        upstream = await _open_gemini(body)
        try:
            if upstream.status_code != 200:
                detail = (await upstream.aread()).decode("utf-8", "replace")
                logger.error("Gemini error %s: %s", upstream.status_code, detail[:500])
                return
            async for line in upstream.aiter_lines():
                if not line.startswith("data:") or line[5:].strip() in ("", "[DONE]"):
                    continue
                try:
                    choices = json.loads(line[5:]).get("choices") or [{}]
                except ValueError:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content") or delta.get("tool_calls"):
                    await queue.put(("delta", delta))
            ok = True
        finally:
            await upstream.aclose()
    except httpx.HTTPError as exc:
        logger.error("Gemini request failed: %r", exc)
    finally:
        await queue.put(("end", ok))


def _filler_delay() -> float:
    try:
        return float(os.environ.get("FILLER_AFTER_S", FILLER_AFTER_S))
    except ValueError:
        return FILLER_AFTER_S


@router.post("/llm/s/{token}/chat/completions")
async def chat_completions(token: str, request: fastapi.Request):
    conversation = _conversations.get(token)
    if conversation is None:
        raise fastapi.HTTPException(status_code=404, detail="unknown interview session")
    body = await request.json()
    messages = body.get("messages") or []
    system = [m for m in messages if m.get("role") == "system"][:1]
    candidate_spoke = False
    model = body.get("model", "")
    if messages and messages[-1].get("role") == "user":
        pushed = messages[-1].get("content")
        candidate_spoke = conversation.add_user(pushed)
        if (pushed or "").strip() in ("", "..."):
            line = conversation.silence_reply()
            if line is not None:
                logger.info("candidate is silent, saying %r", line)
                conversation.say_directly(line)

                def fixed():
                    yield _chunk(model, {"content": line})
                    yield _chunk(model, {}, "stop")
                    yield "data: [DONE]\n\n"

                return fastapi.responses.StreamingResponse(fixed(), media_type="text/event-stream")
    tools = [
        t for t in body.get("tools") or [] if t.get("function", {}).get("name") in INTERVIEW_TOOLS
    ]
    # A filler only makes sense right after the candidate spoke, during the interview.
    filler_allowed = candidate_spoke and not conversation.flow.ended

    async def events():
        nonlocal filler_allowed
        conversation.begin_reply()
        for _ in range(MAX_ROUNDS):
            upstream_body = {
                "model": model,
                "messages": system + conversation.history,
                "tools": tools,
                "stream": True,
                "max_completion_tokens": body.get("max_completion_tokens", 4096),
                # Thinking is dead air on a voice call; keep it low unless asked otherwise.
                "reasoning_effort": body.get("reasoning_effort")
                or os.environ.get("GEMINI_REASONING_EFFORT", "low"),
            }
            queue: asyncio.Queue = asyncio.Queue()
            reader = asyncio.create_task(_read_gemini(upstream_body, queue))
            text, calls = "", {}
            # After a filler, hold back the start of the model's text until a
            # leading acknowledgement can be recognised and dropped.
            held: str | None = None
            try:
                while True:
                    if filler_allowed:
                        try:
                            kind, value = await asyncio.wait_for(queue.get(), _filler_delay())
                        except asyncio.TimeoutError:
                            filler = conversation.next_filler()
                            logger.info("Gemini is slow, saying filler %r", filler)
                            # Spoken, but kept out of the Gemini-side history: when the
                            # model sees fillers in its past turns it starts adding its own.
                            conversation.note_spoken(filler + " ")
                            yield _chunk(model, {"content": filler + " "})
                            filler_allowed = False
                            held = ""
                            continue
                    else:
                        kind, value = await queue.get()
                    filler_allowed = False  # something arrived: no filler this turn
                    piece = value.get("content") or "" if kind == "delta" else ""
                    if held is not None:
                        held += piece
                        # Release once there is enough text to judge, or nothing more is coming.
                        if kind == "end" or value.get("tool_calls") or len(held) >= 24:
                            piece, held = _LEADING_ACK.sub("", held, count=1), None
                        else:
                            piece = ""
                    if piece:
                        text += piece
                        conversation.note_spoken(piece)
                        yield _chunk(model, {"content": piece})
                    if kind == "end":
                        break
                    _collect_calls(calls, value.get("tool_calls") or [])
            finally:
                reader.cancel()

            ordered = [calls[key] for key in sorted(calls)]
            say = conversation.resolve(text.strip(), ordered)
            if say:
                space = " " if text and not text[-1].isspace() else ""
                conversation.note_spoken(space + say)
                yield _chunk(model, {"content": space + say})
            if say is not None or not ordered:
                break
            # Otherwise a tool was refused or needs the model's own words: ask again.
        yield _chunk(model, {}, "stop")
        yield "data: [DONE]\n\n"

    return fastapi.responses.StreamingResponse(events(), media_type="text/event-stream")
