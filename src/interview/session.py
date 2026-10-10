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
import time

import fastapi
import gradbot

from src.interview import loader
from src.interview.flow import TOOLS, InterviewFlow
from src.interview.prompt import build_instructions
from src.interview.recorder import TranscriptRecorder

logger = logging.getLogger("interview")

VOICE = "Harper"
MAX_INTERVIEW_S = 10 * 60
# After end_interview: stop once the goodbye audio has been quiet this long.
GOODBYE_QUIET_S = 2.5
GOODBYE_MAX_S = 20.0
# Time for the browser to play out buffered audio before the socket closes.
PLAYOUT_GRACE_S = 4.0


class ConfigError(Exception):
    pass


def _run_kwargs(port: int) -> dict:
    """Gradbot client settings, using the env names from CONTEXT.md section 9.

    The LLM goes through our own proxy (src/api/llm_proxy.py), which makes
    Gemini's tool calls readable by Gradbot. Set LLM_BASE_URL to bypass it.
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
    proxy = f"http://127.0.0.1:{port}/llm"
    kwargs["llm_base_url"] = (os.environ.get("LLM_BASE_URL") or proxy).rstrip("/")
    return kwargs


def _session_config(inputs: loader.InterviewInputs) -> gradbot.SessionConfig:
    voice = gradbot.flagship_voice(VOICE)
    return gradbot.SessionConfig(
        voice_id=voice.voice_id,
        language=voice.language,
        instructions=build_instructions(inputs),
        tools=TOOLS,
        assistant_speaks_first=True,
        # Optional JSON passed to the LLM request, e.g. {"reasoning_effort": "none"}
        llm_extra_config=os.environ.get("LLM_EXTRA_CONFIG") or None,
    )


async def run_interview(websocket: fastapi.WebSocket, session_id: str) -> None:
    await websocket.accept()
    try:
        inputs = loader.load_session(session_id)
        run_kwargs = _run_kwargs(websocket.url.port or 80)
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
    recorder = TranscriptRecorder(session_id, inputs.candidate_name)
    stop = asyncio.Event()
    started = time.monotonic()
    last_audio = started
    ended_at: float | None = None

    input_handle, output_handle = await gradbot.run(
        **run_kwargs,
        session_config=_session_config(inputs),
        input_format=gradbot.AudioFormat.OggOpus,
        output_format=gradbot.AudioFormat.OggOpus,
    )
    logger.info("interview %s started", session_id)

    async def on_tool_call(msg: gradbot.MsgOut) -> None:
        nonlocal ended_at
        handle = gradbot.ToolHandle(msg.tool_call_handle, msg.tool_call)
        result = flow.handle(handle.name, handle.args)
        logger.info("tool %s(%s) -> %s", handle.name, handle.args, result)
        if flow.ended and ended_at is None:
            ended_at = time.monotonic()
        await handle.send_json(result)

    async def output_loop() -> None:
        nonlocal last_audio
        try:
            while not stop.is_set():
                msg = await output_handle.receive()
                if msg is None:
                    break
                if msg.msg_type == "tool_call":
                    await on_tool_call(msg)
                    continue
                schema = gradbot.schemas.from_msg(msg)
                if schema is None:
                    continue
                if msg.msg_type in ("stt_text", "tts_text"):
                    speaker = "candidate" if msg.msg_type == "stt_text" else "agent"
                    recorder.add(speaker, schema.text, flow.question_id, flow.in_followup)
                    continue  # voice only: no text goes to the browser
                await websocket.send_json(schema.model_dump())
                if msg.msg_type == "audio":
                    last_audio = time.monotonic()
                    await websocket.send_bytes(msg.data)
        finally:
            stop.set()

    async def input_loop() -> None:
        try:
            while not stop.is_set():
                raw = await websocket.receive()
                if raw.get("type") == "websocket.disconnect":
                    break
                if raw.get("bytes") is not None:
                    await input_handle.send_audio(raw["bytes"])
                elif raw.get("text") and json.loads(raw["text"]).get("type") == "stop":
                    break
        finally:
            stop.set()

    async def watchdog() -> None:
        """Ends the session after the goodbye, or at the time cap."""
        try:
            while not stop.is_set():
                await asyncio.sleep(0.25)
                now = time.monotonic()
                if now - started > MAX_INTERVIEW_S:
                    logger.warning("interview %s hit the time cap", session_id)
                    break
                if ended_at is not None:
                    said_goodbye = last_audio > ended_at and now - last_audio > GOODBYE_QUIET_S
                    if said_goodbye or now - ended_at > GOODBYE_MAX_S:
                        break
        finally:
            stop.set()

    tasks = [asyncio.create_task(c()) for c in (output_loop, input_loop, watchdog)]
    try:
        await stop.wait()
    finally:
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

        path = recorder.save(loader.DATA_DIR / session_id)
        logger.info("interview %s: %d turns written to %s", session_id, len(recorder.turns), path)

        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "interview_finished", "completed": flow.ended})
            if flow.ended:
                await asyncio.sleep(PLAYOUT_GRACE_S)
            await websocket.close()
