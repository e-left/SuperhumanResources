from src.interview import loader
from src.interview.flow import InterviewFlow
from src.interview.prompt import build_instructions
from src.interview.recorder import TranscriptRecorder
from src.shared.models import Transcript


def _flow():
    flow = InterviewFlow(loader.load_session("demo").questions)
    flow.candidate_spoke = True  # the hello has been exchanged
    return flow


def test_first_question_waits_for_the_hello():
    flow = InterviewFlow(loader.load_session("demo").questions)
    assert "error" in flow.start_question("q1")
    assert flow.question_id is None
    flow.candidate_spoke = True
    assert flow.start_question("q1")["ok"]


def test_questions_must_go_in_order():
    flow = _flow()
    assert flow.question_id is None
    assert "error" in flow.start_question("q2")
    assert flow.start_question("q1")["ok"]
    assert flow.question_id == "q1"
    assert "error" in flow.start_question("q3")


def test_one_followup_per_question():
    flow = _flow()
    assert "error" in flow.ask_followup()  # nothing in progress
    flow.start_question("q1")
    assert flow.ask_followup()["ok"]
    assert flow.in_followup
    assert "error" in flow.ask_followup()  # second one refused
    flow.start_question("q2")
    assert not flow.in_followup
    assert "error" in flow.ask_followup()  # q2 has none


def test_cannot_end_early():
    flow = _flow()
    flow.start_question("q1")
    assert "error" in flow.end_interview()
    flow.start_question("q2")
    flow.start_question("q3")
    assert flow.end_interview()["ok"]
    assert flow.ended and flow.question_id is None
    assert "error" in flow.start_question("q1")


def test_unknown_tool():
    assert "error" in _flow().handle("grade_candidate", {})


def test_recorder_merges_fragments_and_tags_turns(tmp_path):
    flow = _flow()
    rec = TranscriptRecorder("s1", "Alex Meier", tmp_path / "s1")

    def say(speaker, text):
        rec.add(speaker, text, flow.question_id, flow.in_followup)

    say("agent", "Hi Alex,")
    say("agent", "I'm Ada.")
    flow.start_question("q1")
    say("agent", "Question one?")
    say("candidate", "Well,")
    say("candidate", " I think   so. ")
    say("candidate", "   ")
    flow.ask_followup()
    say("agent", "And where?")
    say("candidate", "In the database.")
    flow.start_question("q2")
    say("agent", "Question two?")

    turns = [(t.speaker, t.question_id, t.followup, t.text) for t in rec.turns]
    assert turns == [
        ("agent", None, False, "Hi Alex, I'm Ada."),
        ("agent", "q1", False, "Question one?"),
        ("candidate", "q1", False, "Well, I think so."),
        ("agent", "q1", True, "And where?"),
        ("candidate", "q1", True, "In the database."),
        ("agent", "q2", False, "Question two?"),
    ]

    path = rec.save("completed")
    saved = Transcript.model_validate_json(path.read_text())
    assert saved.candidate_name == "Alex Meier"
    assert len(saved.turns) == 6


def test_prompt_contains_inputs():
    inputs = loader.load_session("demo")
    prompt = build_instructions(inputs)
    assert "Alex Meier" in prompt
    for question in inputs.questions:
        assert question.question in prompt
        assert question.answer in prompt
    assert "Prepared follow-up: none" in prompt


def test_one_second_chance_per_item_never_a_third():
    flow = _flow()
    assert "error" in flow.second_chance("Try again?", False)  # nothing asked yet
    flow.start_question("q1")
    assert "error" in flow.second_chance("   ", False)  # needs words to say
    result = flow.second_chance("Want to take  another run at that?", False)
    assert result == {"ok": True, "say": "Want to take another run at that?"}
    assert flow.in_second_chance and not flow.hint
    assert "never a third" in flow.second_chance("Once more?", True)["error"]

    # The follow-up is a new thing asked, so it gets its own single second chance.
    flow.ask_followup()
    assert not flow.in_second_chance
    assert flow.second_chance("Think about where the key lives.", True)["ok"]
    assert flow.in_second_chance and flow.hint
    assert "error" in flow.second_chance("Again?", False)

    flow.start_question("q2")
    assert not flow.in_second_chance and not flow.hint


def test_time_up_blocks_new_steps_and_allows_an_early_close():
    flow = _flow()
    flow.start_question("q1")
    flow.time_up = True
    for result in (flow.start_question("q2"), flow.ask_followup(), flow.second_chance("x", False)):
        assert "time limit" in result["error"]
    closing = flow.end_interview()
    assert closing["ok"] and "time is up" in closing["say"]
    assert flow.ended and flow.ended_reason == "time_limit"


def test_ended_reason_is_completed_when_everything_was_asked():
    flow = _flow()
    for question_id in ("q1", "q2", "q3"):
        flow.start_question(question_id)
    flow.time_up = True  # ran long, but nothing was left to ask
    flow.end_interview()
    assert flow.ended_reason == "completed"


def test_recorder_tags_second_chance_turns(tmp_path):
    flow = _flow()
    rec = TranscriptRecorder("s1", "Alex Meier", tmp_path)

    def say(speaker, text):
        rec.add(speaker, text, flow.question_id, flow.in_followup, flow.in_second_chance, flow.hint)

    flow.start_question("q1")
    say("agent", "Question one?")
    say("candidate", "No idea.")
    flow.second_chance("Think about the customer's card.", True)
    say("agent", "Think about the customer's card.")
    say("candidate", "Oh, a double charge.")
    flow.start_question("q2")
    say("agent", "Question two?")

    flags = [(t.question_id, t.second_chance, t.hint) for t in rec.turns]
    assert flags == [
        ("q1", False, False),
        ("q1", False, False),
        ("q1", True, True),
        ("q1", True, True),
        ("q2", False, False),
    ]
    saved = Transcript.model_validate_json(rec.save("completed").read_text())
    assert saved.ended_reason == "completed"


def test_transcript_is_on_disk_before_the_interview_ends(tmp_path):
    rec = TranscriptRecorder("s1", "Alex Meier", tmp_path)
    rec.add("agent", "Hi Alex.", None)
    rec.add("candidate", "Hello.", None)
    rec.add("candidate", "How are you?", None)  # merged: file is rewritten on the next new turn
    rec.add("agent", "Question one?", "q1")
    on_disk = Transcript.model_validate_json((tmp_path / "transcript.json").read_text())
    assert [t.text for t in on_disk.turns] == ["Hi Alex.", "Hello. How are you?", "Question one?"]
    assert on_disk.ended_reason is None  # still in progress
    assert not list(tmp_path.glob("*.tmp"))


def test_interrupted_turn_keeps_the_full_wording(tmp_path):
    rec = TranscriptRecorder("s1", "Alex Meier", tmp_path)
    rec.add("agent", "Thanks. Our order service retries", "q1")
    rec.add("candidate", "Sorry, go on.", "q1")
    rec.mark_interrupted(
        "Thanks. Our order service retries a payment call. What could go wrong?",
        "Thanks. Our order service retries",
    )
    agent, candidate = rec.turns
    assert agent.interrupted and agent.heard == "Thanks. Our order service retries"
    assert agent.text == "Thanks. Our order service retries a payment call. What could go wrong?"
    assert candidate.text == "Sorry, go on."
    # Later speech starts a new turn instead of being glued onto the interrupted one.
    rec.add("agent", "Our order service retries a payment call.", "q1")
    assert len(rec.turns) == 3


def test_turn_of_which_nothing_was_spoken_is_not_added(tmp_path):
    rec = TranscriptRecorder("s1", "Alex Meier", tmp_path)
    rec.add("candidate", "Hi.", None)
    rec.mark_interrupted("Hi Alex, I'm Ada. How are you doing today?", "")
    assert [t.speaker for t in rec.turns] == ["candidate"]
