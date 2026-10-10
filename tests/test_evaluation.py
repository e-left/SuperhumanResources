import pytest

from src.evaluation import evaluator
from src.evaluation.prompt import build_prompt
from src.interview import loader
from src.shared.models import Judgement, ProfileAlignment, QuestionJudgement, Report, Transcript

MODEL = "test-model"


@pytest.fixture
def inputs():
    return loader.load_session("demo")


@pytest.fixture
def transcript():
    # Read the fixture directly: load_transcript() prefers data/demo once a real run exists.
    path = loader.FIXTURES_DIR / "demo" / "transcript.json"
    return Transcript.model_validate_json(path.read_text(encoding="utf-8"))


def _q(question_id, score, evidence):
    return QuestionJudgement(
        question_id=question_id,
        score=score,
        reasoning="because",
        covered_points=["a"],
        missed_points=["b"],
        strengths=["s"],
        gaps=["g"],
        evidence=evidence,
    )


def _judgement(*questions):
    return Judgement(
        per_question=list(questions),
        summary="Summary.",
        reasoning="Reasoning.",
        profile_alignment=ProfileAlignment(confirmed=[], contradicted=[]),
        red_flags=[],
        suggested_next_steps=[],
        communication="Clear.",
    )


GOOD = (
    _q("q1", 90, ["send an idempotency key with every attempt"]),
    _q("q2", 30, ["wrap both in a try except"]),
    _q("q3", 70, ["run explain analyze on it"]),
)


def test_overall_is_mean_and_recommendation_from_thresholds(inputs, transcript):
    report = evaluator.finalize(inputs, transcript, _judgement(*GOOD), MODEL)
    assert report.overall_score == 63  # mean of 90, 30, 70
    assert report.recommendation == "hire"
    assert report.interview_complete
    assert not report.needs_human_review
    assert [q.followup_asked for q in report.per_question] == [True, False, True]
    assert report.candidate_name == "Alex Meier"
    assert report.per_question[0].question == inputs.questions[0].question
    Report.model_validate_json(report.model_dump_json())


@pytest.mark.parametrize(
    "score, expected", [(100, "strong_hire"), (80, "strong_hire"), (79, "hire"), (60, "hire"), (59, "no_hire"), (0, "no_hire")]
)
def test_thresholds(score, expected):
    assert evaluator.recommendation(score) == expected


def test_quote_match_ignores_case_and_punctuation(inputs, transcript):
    judgement = _judgement(_q("q1", 90, ["Send an idempotency key, with EVERY attempt!"]), *GOOD[1:])
    report = evaluator.finalize(inputs, transcript, judgement, MODEL)
    assert len(report.per_question[0].evidence) == 1
    assert not report.needs_human_review


def test_fabricated_and_interviewer_quotes_are_dropped(inputs, transcript):
    judgement = _judgement(
        _q("q1", 90, ["I would use a transactional outbox", "Where would you store the idempotency key"]),
        *GOOD[1:],
    )
    report = evaluator.finalize(inputs, transcript, judgement, MODEL)
    assert report.per_question[0].evidence == []
    assert report.needs_human_review
    assert any("2 quote(s)" in r for r in report.review_reasons)
    assert any("without a verified quote" in r for r in report.review_reasons)


def test_unanswered_question_scores_zero_whatever_the_model_says(inputs, transcript):
    transcript.turns = [
        t for t in transcript.turns if not (t.question_id == "q3" and t.speaker == "candidate")
    ]
    report = evaluator.finalize(inputs, transcript, _judgement(*GOOD), MODEL)
    q3 = report.per_question[2]
    assert q3.status == "not_answered" and q3.score == 0 and q3.evidence == []
    assert "asked but got no answer" in q3.reasoning
    assert report.overall_score == 40  # mean of 90, 30, 0
    assert report.recommendation == "no_hire"
    assert not report.interview_complete
    assert report.needs_human_review
    assert report.summary.startswith("Incomplete interview: q3")


def test_question_never_reached(inputs, transcript):
    transcript.turns = [t for t in transcript.turns if t.question_id != "q3"]
    report = evaluator.finalize(inputs, transcript, _judgement(*GOOD[:2]), MODEL)
    assert "never reached" in report.per_question[2].reasoning
    assert report.per_question[2].score == 0


def test_missing_judgement_and_out_of_range_score(inputs, transcript):
    judgement = _judgement(_q("q1", 140, ["send an idempotency key"]), GOOD[1])
    report = evaluator.finalize(inputs, transcript, judgement, MODEL)
    assert report.per_question[0].score == 100
    assert report.per_question[2].score == 0
    assert any("q3 has no judgement" in r for r in report.review_reasons)


def test_prompt_has_everything_the_evaluator_needs(inputs, transcript):
    prompt = build_prompt(inputs, transcript)
    assert "Alex Meier" in prompt
    for question in inputs.questions:
        assert question.answer in prompt
    assert "Candidate [follow-up]: In the orders database" in prompt
    assert "Candidate: Thanks, bye." in prompt
    # q2 has no follow-up in the fixture
    assert prompt.count("Prepared follow-up:") == 2


def test_prompt_marks_unreached_question(inputs, transcript):
    transcript.turns = [t for t in transcript.turns if t.question_id != "q3"]
    assert "(this question was never reached)" in build_prompt(inputs, transcript)


def test_missing_transcript():
    with pytest.raises(loader.SessionError):
        evaluator.load_transcript("nope")
