import pytest

from src.interview import loader

DOC = """\
# Question
What is it?

# Answer
It is this.

# Context
From `a.py`.
"""

FOLLOWUP = """
# Follow up
## Question
And then?
## Answer
Then that.
## Context
From `b.py`.
"""


def test_demo_fixture_loads():
    inputs = loader.load_session("demo")
    assert [q.id for q in inputs.questions] == ["q1", "q2", "q3"]
    assert inputs.candidate_name == "Alex Meier"
    assert inputs.questions[0].followup is not None
    assert inputs.questions[1].followup is None


def test_parse_without_followup():
    question = loader.parse_question("q1", DOC)
    assert question.question == "What is it?"
    assert question.answer == "It is this."
    assert question.followup is None


def test_parse_with_followup():
    question = loader.parse_question("q1", DOC + FOLLOWUP)
    assert question.followup.question == "And then?"
    assert question.followup.context == "From `b.py`."
    # the follow-up's sections must not overwrite the main ones
    assert question.answer == "It is this."


def test_missing_answer_is_rejected():
    with pytest.raises(loader.SessionError, match="answer"):
        loader.parse_question("q1", DOC.replace("# Answer\nIt is this.\n", ""))


def test_incomplete_followup_is_rejected():
    with pytest.raises(loader.SessionError, match="followup.answer"):
        loader.parse_question("q1", DOC + "\n# Follow-up\n## Question\nAnd then?\n")


@pytest.mark.parametrize("session_id", ["../demo", "nope", ""])
def test_bad_session_id(session_id):
    with pytest.raises(loader.SessionError):
        loader.load_session(session_id)


def test_candidate_name_falls_back_to_title():
    assert loader.candidate_name("# Jo Smith\n\nSome text") == "Jo Smith"
    assert loader.candidate_name("no headings here") == "Candidate"


def test_example_fixture_loads():
    inputs = loader.load_session("example")
    assert inputs.candidate_name == "Sam Rivera"
    assert [q.followup is not None for q in inputs.questions] == [True, True, False]
