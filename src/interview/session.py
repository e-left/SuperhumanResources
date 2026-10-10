"""One voice interview over a browser WebSocket.

Same wire protocol as gradbot.websocket.handle_session (start message, binary
audio frames, stop message), but with our own loop so every spoken turn is
recorded server-side and written to data/<session>/transcript.json.
"""

import asyncio
import contextlib
import json
import logging
import os
import secrets
import time

import fastapi
import gradbot

from src.evaluation import evaluator
from src.interview import llm_proxy, loader
from src.interview.flow import TOOLS, InterviewFlow
from src.interview.prompt import build_instructions
from src.interview.recorder import TranscriptRecorder

logger = logging.getLogger("interview")

VOICE = "Harper"
# Time limit. At the wrap-up mark the interviewer is told to close after the
# current answer; at the hard limit the session ends whatever is happening.
# Both can be overridden in seconds (INTERVIEW_WRAP_UP_S, INTERVIEW_MAX_S).
WRAP_UP_AFTER_S = 12 * 60
MAX_INTERVIEW_S = 15 * 60
# How long the candidate may stay silent before the interviewer says anything.
# Gradbot's default of 5 seconds is too short for an interview: people think
# before answering, and a prompt that starts just as they begin to speak cuts
# off their first words. Override with INTERVIEW_SILENCE_S.
SILENCE_TIMEOUT_S = 15.0
# After the goodbye has played, the candidate gets this long to start saying bye back.
GOODBYE_REPLY_WINDOW_S = 4.0
# Once they have replied, wait this long after their last word (and for any
# short answer from the agent to play out) before closing.
GOODBYE_REPLY_SETTLE_S = 5.0
GOODBYE_MAX_S = 25.0
# Margin for audio still buffered in the browser when the socket closes.
PLAYOUT_GRACE_S = 1.5


# Keeps background evaluation tasks alive until they finish.
_background: set[asyncio.Task] = set()


class ConfigError(Exception):
    pass


def _seconds(env: str, default: float) -> float:
    try:
        return float(os.environ.get(env) or default)
    except ValueError:
        return default


async def _evaluate(session_id: str, base_url: str) -> None:
    """Write the internal report once the interview is over."""
    try:
        report = await asyncio.to_thread(evaluator.evaluate, session_id)
    except Exception as exc:  # the interview itself is already saved
        logger.error("evaluation of %s failed: %s", session_id, exc)
        return
    logger.info(
        "report for %s ready (%s, %d/100): %s/internal/report?session=%s",
        session_id, report.decision, report.overall_score, base_url, session_id,
    )


def _run_kwargs(port: int, token: str) -> dict:
    """Gradbot client settings, using the env names from CONTEXT.md section 9.

    The LLM URL is this session's endpoint on our own proxy
    (src/interview/llm_proxy.py), which talks to Gemini and runs the tools.
    """
    required = {
        "gradium_api_key": "GRADIUM_API_KEY",
        "llm_api_key": "GEMINI_API_KEY",
        "llm_model_name": "GEMINI_MODEL",
    }
    kwargs = {key: os.environ.get(env, "").strip() for key, env in required.items()}
    missing = [required[key] for key, value in kwargs.items() if not value]
    if missing:
        raise ConfigError(f"missing environment variables: {', '.join(missing)}")
    # The interviewer can use a faster model than the evaluator (INTERVIEW_MODEL).
    kwargs["llm_model_name"] = os.environ.get("INTERVIEW_MODEL", "").strip() or kwargs["llm_model_name"]
    kwargs["llm_base_url"] = f"http://127.0.0.1:{port}/llm/s/{token}"
    return kwargs


def _session_config(inputs: loader.InterviewInputs) -> gradbot.SessionConfig:
    voice = gradbot.flagship_voice(VOICE)
    return gradbot.SessionConfig(
        voice_id=voice.voice_id,
        language=voice.language,
        instructions=build_instructions(inputs),
        tools=TOOLS,
        assistant_speaks_first=True,
        silence_timeout_s=_seconds("INTERVIEW_SILENCE_S", SILENCE_TIMEOUT_S),
    )


async def run_interview(websocket: fastapi.WebSocket, session_id: str) -> None:
    await websocket.accept()
    token = secrets.token_urlsafe(8)
    try:
        inputs = loader.load_session(session_id)
        run_kwargs = _run_kwargs(websocket.url.port or 80, token)
    except (loader.SessionError, ConfigError) as exc:
        logger.error("cannot start interview %s: %s", session_id, exc)
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=4001)
        return

    try:
        start_msg = await websocket.receive_json()
    except fastapi.WebSocketDisconnect:
        return
    if start_msg.get("type") != "start":
        await websocket.close(code=4000, reason="Expected start message")
        return

    flow = InterviewFlow(inputs.questions)
    # The proxy runs the interviewer's tool calls on this flow.
    conversation = llm_proxy.register(token, flow)
    recorder = TranscriptRecorder(session_id, inputs.candidate_name, loader.DATA_DIR / session_id)

    def on_cut(intended: str, heard: str) -> None:
        """The interviewer was interrupted: keep its full wording in the transcript."""
        recorder.mark_interrupted(intended, heard)

    conversation.on_cut = on_cut
    stop = asyncio.Event()
    started = time.monotonic()
    last_audio = started
    playout_until = started  # estimate of when the agent's audio finishes playing
    last_candidate = started
    ended_at: float | None = None
    stop_reason = "disconnected"  # why the session ended, if not by a goodbye
    wrap_up_after = _seconds("INTERVIEW_WRAP_UP_S", WRAP_UP_AFTER_S)
    max_duration = _seconds("INTERVIEW_MAX_S", MAX_INTERVIEW_S)

    input_handle, output_handle = await gradbot.run(
        **run_kwargs,
        session_config=_session_config(inputs),
        input_format=gradbot.AudioFormat.OggOpus,
        output_format=gradbot.AudioFormat.OggOpus,
    )
    logger.info("interview %s started", session_id)

    async def output_loop() -> None:
        nonlocal last_audio, playout_until, last_candidate
        try:
            while not stop.is_set():
                msg = await output_handle.receive()
                if msg is None:
                    break
                schema = gradbot.schemas.from_msg(msg)
                if schema is None:
                    continue
                if msg.msg_type in ("stt_text", "tts_text"):
                    speaker = "candidate" if msg.msg_type == "stt_text" else "agent"
                    if speaker == "candidate":
                        flow.candidate_spoke = True
                        last_candidate = time.monotonic()
                    else:
                        conversation.note_heard(schema.text)
                    recorder.add(
                        speaker,
                        schema.text,
                        flow.question_id,
                        flow.in_followup,
                        flow.in_second_chance,
                        flow.hint,
                    )
                    continue  # voice only: no text goes to the browser
                await websocket.send_json(schema.model_dump())
                if msg.msg_type == "audio":
                    last_audio = time.monotonic()
                    # Audio is generated faster than it is heard; track when it ends.
                    seconds = (msg.stop_s or 0.0) - (msg.start_s or 0.0)
                    playout_until = max(playout_until, last_audio) + max(seconds, 0.0)
                    await websocket.send_bytes(msg.data)
        finally:
            stop.set()

    async def input_loop() -> None:
        nonlocal stop_reason
        try:
            while not stop.is_set():
                raw = await websocket.receive()
                if raw.get("type") == "websocket.disconnect":
                    break
                if raw.get("bytes") is not None:
                    await input_handle.send_audio(raw["bytes"])
                elif raw.get("text") and json.loads(raw["text"]).get("type") == "stop":
                    stop_reason = "stopped"
                    break
        finally:
            stop.set()

    async def watchdog() -> None:
        """Starts the wrap-up, and ends the session after the goodbye or at the hard limit."""
        nonlocal ended_at, stop_reason
        try:
            while not stop.is_set():
                await asyncio.sleep(0.25)
                now = time.monotonic()
                if now - started > max_duration:
                    logger.warning("interview %s hit the hard time limit", session_id)
                    stop_reason = "time_limit"
                    break
                if now - started > wrap_up_after and not flow.time_up:
                    logger.info("interview %s reached the wrap-up time", session_id)
                    flow.time_up = True
                if flow.ended and ended_at is None:
                    ended_at = now
                if ended_at is not None:
                    goodbye_played = last_audio > ended_at and now > playout_until
                    replied = last_candidate > ended_at
                    if replied:
                        done = goodbye_played and now - last_candidate > GOODBYE_REPLY_SETTLE_S
                    else:
                        done = goodbye_played and now - playout_until > GOODBYE_REPLY_WINDOW_S
                    if done or now - ended_at > GOODBYE_MAX_S:
                        break
        finally:
            stop.set()

    tasks = [asyncio.create_task(c()) for c in (output_loop, input_loop, watchdog)]
    try:
        await stop.wait()
    finally:
        llm_proxy.unregister(token)
        with contextlib.suppress(Exception):
            await input_handle.close()
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) and not isinstance(
                result, (asyncio.CancelledError, fastapi.WebSocketDisconnect, RuntimeError)
            ):
                logger.error("interview %s task failed: %r", session_id, result)

        reason = flow.ended_reason if flow.ended else stop_reason
        path = recorder.save(reason)
        logger.info(
            "interview %s ended (%s): %d turns written to %s",
            session_id, reason, len(recorder.turns), path,
        )
        if any(turn.speaker == "candidate" for turn in recorder.turns):
            base_url = f"http://{websocket.url.hostname}:{websocket.url.port or 80}"
            task = asyncio.create_task(_evaluate(session_id, base_url))
            _background.add(task)
            task.add_done_callback(_background.discard)

        with contextlib.suppress(Exception):
            await websocket.send_json(
                {"type": "interview_finished", "completed": flow.ended, "reason": reason}
            )
            if flow.ended:
                await asyncio.sleep(PLAYOUT_GRACE_S)
            await websocket.close()
