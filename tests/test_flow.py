from src.interview import loader
from src.interview.flow import InterviewFlow
from src.interview.prompt import build_instructions
from src.interview.recorder import TranscriptRecorder
from src.shared.models import Transcript


def _flow():
    return InterviewFlow(loader.load_session("demo").questions)


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
    rec = TranscriptRecorder("s1", "Alex Meier")

    def say(speaker, text):
        rec.add(speaker, text, flow.question_id, flow.in_followup)

    say("agent", "Hi Alex,")
    say("agent", "I'm Harper.")
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
        ("agent", None, False, "Hi Alex, I'm Harper."),
        ("agent", "q1", False, "Question one?"),
        ("candidate", "q1", False, "Well, I think so."),
        ("agent", "q1", True, "And where?"),
        ("candidate", "q1", True, "In the database."),
        ("agent", "q2", False, "Question two?"),
    ]

    path = rec.save(tmp_path / "s1")
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
