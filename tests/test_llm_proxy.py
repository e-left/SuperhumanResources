import json

from src.interview import llm_proxy, loader
from src.interview.flow import InterviewFlow


def _conversation():
    flow = InterviewFlow(loader.load_session("demo").questions)
    flow.candidate_spoke = True
    return llm_proxy.Conversation(flow)


def _call(name, args=None, call_id="c1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args or {})},
        "extra_content": {"google": {"thought_signature": "sig"}},
    }


def test_plain_text_reply_is_just_recorded():
    conv = _conversation()
    conv.add_user("[start]")
    assert conv.resolve("Hi Alex, I'm Harper.", []) is None
    assert [m["role"] for m in conv.history] == ["user", "assistant"]


def test_accepted_question_returns_the_exact_wording():
    conv = _conversation()
    say = conv.resolve("Glad to hear it.", [_call("start_question", {"question_id": "q1"})])
    assert say == conv.flow.questions[0].question
    assert conv.flow.question_id == "q1"
    # Gemini-side history keeps the tool call (with its signature), the result and what was said.
    roles = [m["role"] for m in conv.history]
    assert roles == ["assistant", "tool", "assistant"]
    assert conv.history[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig"
    assert json.loads(conv.history[1]["content"])["ok"] is True
    assert conv.history[2]["content"] == say


def test_followup_wording():
    conv = _conversation()
    conv.resolve("", [_call("start_question", {"question_id": "q1"})])
    assert conv.resolve("Got it.", [_call("ask_followup", call_id="c2")]) == (
        conv.flow.questions[0].followup.question
    )


def test_refused_tool_call_asks_the_model_again():
    conv = _conversation()
    assert conv.resolve("", [_call("start_question", {"question_id": "q2"})]) is None
    assert conv.history[-1]["role"] == "tool"  # the error goes back to the model
    assert "error" in json.loads(conv.history[-1]["content"])
    assert conv.flow.question_id is None


def test_goodbye_is_left_to_the_model():
    conv = _conversation()
    for question_id in ("q1", "q2", "q3"):
        conv.resolve("", [_call("start_question", {"question_id": question_id})])
    assert conv.resolve("", [_call("end_interview", call_id="c9")]) is None
    assert conv.flow.ended
    assert conv.history[-1]["role"] == "tool"


def test_silence_push_becomes_a_placeholder():
    conv = _conversation()
    conv.add_user("")
    assert conv.history[-1]["content"] == "..."


def test_collect_calls_handles_missing_index_and_fragments():
    calls: dict[int, dict] = {}
    whole = _call("ask_followup")  # Gemini style: no index, sent whole
    llm_proxy._collect_calls(calls, [whole])
    assert calls[0]["function"]["name"] == "ask_followup"
    assert calls[0]["extra_content"]

    fragments: dict[int, dict] = {}
    llm_proxy._collect_calls(fragments, [{"index": 0, "id": "x", "function": {"name": "start_question", "arguments": '{"question'}}])
    llm_proxy._collect_calls(fragments, [{"index": 0, "function": {"arguments": '_id": "q1"}'}}])
    assert json.loads(fragments[0]["function"]["arguments"]) == {"question_id": "q1"}


def test_second_chance_words_are_spoken_as_given():
    conv = _conversation()
    conv.resolve("", [_call("start_question", {"question_id": "q1"})])
    call = _call("second_chance", {"say": "Take another run at it.", "hint_given": False}, "c2")
    assert conv.resolve("", [call]) == "Take another run at it."
    # A third try is refused, so the model is asked again instead of speaking.
    again = _call("second_chance", {"say": "One more time?", "hint_given": False}, "c3")
    assert conv.resolve("", [again]) is None
    assert "never a third" in json.loads(conv.history[-1]["content"])["error"]


def test_time_up_note_is_added_once_and_only_while_running():
    conv = _conversation()
    conv.add_user("an answer")
    assert llm_proxy.TIME_UP_NOTE not in conv.history[-1]["content"]
    conv.flow.time_up = True
    conv.add_user("another answer")
    assert llm_proxy.TIME_UP_NOTE in conv.history[-1]["content"]
    conv.add_user("more")
    assert llm_proxy.TIME_UP_NOTE not in conv.history[-1]["content"]


def test_add_user_tells_speech_from_gradbot_pushes():
    conv = _conversation()
    assert conv.add_user("I would use an index.") is True
    for push in ("", "...", "[start]", None):
        assert conv.add_user(push) is False


def test_fillers_are_neutral_and_never_repeat_back_to_back():
    conv = _conversation()
    said = [conv.next_filler() for _ in range(40)]
    assert set(said) <= set(llm_proxy.FILLERS)
    assert all(a != b for a, b in zip(said, said[1:]))


def test_failed_model_call_leaves_no_empty_message():
    conv = _conversation()
    assert conv.resolve("", []) is None
    assert conv.history == []


# --- interruptions ----------------------------------------------------------

QUESTION = "Our order service retries a payment call when the provider times out. What could go wrong?"


def _cut(conv, heard="Thanks. Our order service"):
    conv.begin_reply()
    conv.note_spoken(f"Thanks. {QUESTION}")
    conv._reply_asked = True  # the reply carried a question
    conv.note_heard(heard)


def test_cut_off_question_is_reported_and_the_model_is_told_once():
    conv = _conversation()
    conv.resolve("", [_call("start_question", {"question_id": "q1"})])
    cuts = []
    conv.on_cut = lambda intended, heard: cuts.append((intended, heard))
    _cut(conv)
    assert conv.reply_was_cut()

    conv.add_user("Sorry, what was that?")
    assert cuts == [(f"Thanks. {QUESTION}", "Thanks. Our order service")]
    assert "cut off" in conv.history[-1]["content"]
    assert "Thanks. Our order service" in conv.history[-1]["content"]

    # Cut off again on the same question (noisy room): recorded, but the model is
    # not told to repeat a second time, or it would loop.
    _cut(conv)
    conv.add_user("no no put it over there")
    assert len(cuts) == 2 and "cut off" not in conv.history[-1]["content"]

    # A new thing asked gets its own single note.
    conv.resolve("", [_call("ask_followup", call_id="c2")])
    _cut(conv)
    conv.add_user("what?")
    assert "cut off" in conv.history[-1]["content"]


def test_a_greeting_that_was_cut_off_is_never_restarted():
    conv = _conversation()  # no question in progress yet
    conv.begin_reply()
    conv.note_spoken("Hi Alex, I'm Harper. How are you doing today?")
    conv.note_heard("Hi Alex")
    conv.add_user("each what no he's trying to reach it")
    assert conv.history[-1]["content"] == "each what no he's trying to reach it"


def test_fully_spoken_and_short_turns_are_not_cut():
    conv = _conversation()
    conv.begin_reply()
    conv.note_spoken(QUESTION)
    for word in QUESTION.split():
        conv.note_heard(word)
    assert not conv.reply_was_cut()

    conv.begin_reply()
    conv.note_spoken("Bye!")  # too short to judge
    assert not conv.reply_was_cut()

    conv.begin_reply()  # nothing said yet, e.g. before the first turn
    assert not conv.reply_was_cut()


def test_turn_cut_before_any_word_is_still_reported():
    conv = _conversation()
    cuts = []
    conv.on_cut = lambda intended, heard: cuts.append(heard)
    conv.begin_reply()
    conv.note_spoken("Hi Alex, I'm Harper. How are you doing today?")
    conv.add_user("Hi.")
    assert cuts == [""]


# --- the model asks a question without its tool call ------------------------


def test_spoken_next_question_advances_the_flow():
    conv = _conversation()
    q1 = conv.flow.questions[0]
    conv.resolve(f"Glad to hear it. {q1.question}", [])
    assert conv.flow.question_id == "q1"
    # Light rephrasing is still recognised.
    q2 = conv.flow.questions[1].question.replace("How would you", "How do you")
    conv.resolve(f"Thanks. {q2}", [])
    assert conv.flow.question_id == "q2"


def test_spoken_followup_is_recognised_once():
    conv = _conversation()
    conv.resolve("", [_call("start_question", {"question_id": "q1"})])
    followup = conv.flow.questions[0].followup.question
    conv.resolve(f"Got it. {followup}", [])
    assert conv.flow.in_followup
    assert not conv.flow.followup_available


def test_ordinary_talk_and_repeating_the_current_question_change_nothing():
    conv = _conversation()
    conv.resolve("", [_call("start_question", {"question_id": "q1"})])
    conv.resolve("Sure, take your time.", [])
    conv.resolve(conv.flow.questions[0].question, [])  # repeating q1 on request
    assert conv.flow.question_id == "q1" and not conv.flow.in_followup


def test_spoken_question_still_respects_the_rules():
    flow = InterviewFlow(loader.load_session("demo").questions)  # candidate has not spoken yet
    conv = llm_proxy.Conversation(flow)
    conv.resolve(flow.questions[0].question, [])
    assert flow.question_id is None


def test_a_cut_off_remark_that_was_not_a_question_triggers_no_repeat():
    conv = _conversation()
    conv.resolve("", [_call("start_question", {"question_id": "q1"})])
    conv.begin_reply()
    conv.note_spoken("Take your time, there is no rush at all.")  # never heard
    conv.add_user("So the main problem is the timeout.")
    assert "cut off" not in conv.history[-1]["content"]


# --- silence ----------------------------------------------------------------


def test_silence_gets_fixed_lines_then_the_model_decides():
    conv = _conversation()
    conv.resolve("", [_call("start_question", {"question_id": "q1"})])
    said = []
    for _ in range(3):
        conv.add_user("...")
        said.append(conv.silence_reply())
    assert said == [*llm_proxy.WAITING_FOR_ANSWER, None]
    assert llm_proxy.LONG_SILENCE_NOTE in conv.history[-1]["content"]
    assert conv.flow.question_id == "q1"  # silence never moves the interview on by itself

    conv.add_user("Sorry, I was thinking. It is the double charge.")
    conv.add_user("")
    assert conv.silence_reply() == llm_proxy.WAITING_FOR_ANSWER[0]  # counter starts again


def test_silence_before_the_hello_just_keeps_waiting():
    flow = InterviewFlow(loader.load_session("demo").questions)
    conv = llm_proxy.Conversation(flow)
    said = []
    for _ in range(4):
        conv.add_user("...")
        said.append(conv.silence_reply())
    assert said == [*llm_proxy.WAITING_FOR_HELLO, llm_proxy.WAITING_FOR_HELLO[-1], llm_proxy.WAITING_FOR_HELLO[-1]]


def test_no_fixed_lines_once_time_is_up_or_the_interview_is_over():
    conv = _conversation()
    conv.flow.time_up = True
    conv.add_user("...")
    assert conv.silence_reply() is None


def test_say_directly_is_recorded_as_the_interviewer_speaking():
    conv = _conversation()
    conv.say_directly("Take your time.")
    assert conv.history[-1] == {"role": "assistant", "content": "Take your time."}
    assert conv.last_reply == "Take your time."


# --- goodbye and fillers ----------------------------------------------------


def test_goodbye_in_the_same_response_needs_no_second_model_call():
    conv = _conversation()
    for question_id in ("q1", "q2", "q3"):
        conv.resolve("", [_call("start_question", {"question_id": question_id})])
    assert conv.resolve("Thank you, Alex. Goodbye!", [_call("end_interview", call_id="c9")]) == ""
    assert conv.flow.ended


def test_refused_end_with_text_still_goes_back_to_the_model():
    conv = _conversation()
    conv.resolve("", [_call("start_question", {"question_id": "q1"})])
    assert conv.resolve("Thanks, goodbye!", [_call("end_interview", call_id="c2")]) is None
    assert not conv.flow.ended


def test_leading_acknowledgement_is_dropped_after_a_filler():
    strip = lambda text: llm_proxy._LEADING_ACK.sub("", text, count=1)
    assert strip("Got it. Let's move on.") == "Let's move on."
    assert strip("Thanks. ") == ""
    assert strip("Got it.") == ""  # the acknowledgement was the whole text before a tool call
    # Only a whole acknowledgement sentence is dropped, never the start of a longer one.
    assert strip("Thank you, Sam, and goodbye!") == "Thank you, Sam, and goodbye!"
    assert strip("Glad to hear it. I have three questions.") == "Glad to hear it. I have three questions."
    assert strip("Rightly so, that matters.") == "Rightly so, that matters."
