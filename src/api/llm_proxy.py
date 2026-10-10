"""Local OpenAI-compatible proxy between Gradbot and Gemini.

Gradbot's streaming parser and Gemini's OpenAI-compatible endpoint disagree on
tool calls, so the interviewer's tools never fire when they talk directly:

- Gemini omits `index` on streamed tool calls; Gradbot requires it.
- Gemini 3 attaches a thought signature to each tool call (`extra_content`) and
  expects it back on the next request; Gradbot does not echo unknown fields.

This proxy adds the index, remembers the signatures and re-attaches them. It
also retries when Gemini answers 429/503 before the stream starts.
"""

import asyncio
import json
import logging
import os

import fastapi
import fastapi.responses
import httpx

logger = logging.getLogger("interview.llm")
router = fastapi.APIRouter()

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
RETRY_STATUS = {429, 500, 503}
MAX_ATTEMPTS = 3
MAX_REMEMBERED = 2000

# tool call id -> extra_content (thought signature) to send back to Gemini
_extra_content: dict[str, dict] = {}
_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))


def _remember(call_id: str, extra: dict) -> None:
    if len(_extra_content) >= MAX_REMEMBERED:
        _extra_content.pop(next(iter(_extra_content)))
    _extra_content[call_id] = extra


def fix_request(body: dict) -> dict:
    """Re-attach the thought signatures Gemini expects on earlier tool calls."""
    for message in body.get("messages", []):
        for call in message.get("tool_calls") or []:
            extra = _extra_content.get(call.get("id", ""))
            if extra and "extra_content" not in call:
                call["extra_content"] = extra
    # Thinking adds seconds of silence on a voice call; keep it low unless asked otherwise.
    body.setdefault("reasoning_effort", os.environ.get("GEMINI_REASONING_EFFORT", "low"))
    return body


def fix_chunk(chunk: dict) -> dict:
    """Make a streamed chunk parseable by Gradbot."""
    for choice in chunk.get("choices", []):
        delta = choice.get("delta") or choice.get("message") or {}
        for position, call in enumerate(delta.get("tool_calls") or []):
            call.setdefault("index", position)
            extra = call.pop("extra_content", None)
            if extra and call.get("id"):
                _remember(call["id"], extra)
    return chunk


def fix_sse_line(line: str) -> str:
    if not line.startswith("data:"):
        return line
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return line
    try:
        return "data: " + json.dumps(fix_chunk(json.loads(payload)))
    except ValueError:
        return line


@router.post("/llm/chat/completions")
async def chat_completions(request: fastapi.Request):
    body = fix_request(await request.json())
    headers = {
        "Authorization": f"Bearer {os.environ.get('GEMINI_API_KEY', '')}",
        "Content-Type": "application/json",
    }
    url = f"{GEMINI_OPENAI_BASE_URL}/chat/completions"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        upstream = await _client.send(
            _client.build_request("POST", url, headers=headers, json=body), stream=True
        )
        if upstream.status_code not in RETRY_STATUS or attempt == MAX_ATTEMPTS:
            break
        logger.warning("Gemini returned %s, retrying (%d)", upstream.status_code, attempt)
        await upstream.aclose()
        await asyncio.sleep(0.4 * attempt)

    if upstream.status_code != 200:
        detail = (await upstream.aread()).decode("utf-8", "replace")
        await upstream.aclose()
        logger.error("Gemini error %s: %s", upstream.status_code, detail[:500])
        return fastapi.responses.Response(
            detail, status_code=upstream.status_code, media_type="application/json"
        )

    if not body.get("stream"):
        data = json.loads(await upstream.aread())
        await upstream.aclose()
        return fastapi.responses.JSONResponse(fix_chunk(data))

    async def stream():
        try:
            async for line in upstream.aiter_lines():
                yield fix_sse_line(line) + "\n"
        finally:
            await upstream.aclose()

    return fastapi.responses.StreamingResponse(stream(), media_type="text/event-stream")
