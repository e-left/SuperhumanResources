import json

from src.api import llm_proxy

GEMINI_CHUNK = {
    "choices": [
        {
            "delta": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "extra_content": {"google": {"thought_signature": "sig"}},
                        "function": {"arguments": "{}", "name": "ask_followup"},
                        "id": "call_1",
                        "type": "function",
                    }
                ],
            },
            "index": 0,
        }
    ]
}


def test_tool_call_gets_index_and_signature_round_trips():
    line = llm_proxy.fix_sse_line("data: " + json.dumps(GEMINI_CHUNK))
    call = json.loads(line[6:])["choices"][0]["delta"]["tool_calls"][0]
    assert call["index"] == 0
    assert "extra_content" not in call  # Gradbot never sees it

    # Gradbot's next request echoes the call without the signature; the proxy restores it.
    body = llm_proxy.fix_request(
        {"messages": [{"role": "assistant", "tool_calls": [{"id": "call_1", "type": "function"}]}]}
    )
    assert body["messages"][0]["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "sig"}
    }
    assert body["reasoning_effort"] == "low"


def test_explicit_reasoning_effort_is_kept():
    assert llm_proxy.fix_request({"messages": [], "reasoning_effort": "high"})["reasoning_effort"] == "high"


def test_other_lines_pass_through():
    for line in ["", ": keep-alive", "data: [DONE]", "data: not json"]:
        assert llm_proxy.fix_sse_line(line) == line
    text = 'data: {"choices": [{"delta": {"content": "Hi"}, "index": 0}]}'
    assert json.loads(llm_proxy.fix_sse_line(text)[6:])["choices"][0]["delta"]["content"] == "Hi"
