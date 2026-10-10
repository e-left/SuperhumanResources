import pytest

from src.evaluation import evaluator
from src.evaluation.prompt import build_judge_prompt, build_writeup_prompt
from src.interview import loader
from src.shared.models import (
    Judgement,
    ProfileAlignment,
    QuestionJudgement,
    Report,
    Transcript,
    Writeup,
)

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
        covered_points=["covers idempotency"],
        missed_points=["- no reconciliation"],
        strengths=["clear"],
        gaps=["shallow"],
        evidence=evidence,
    )


def _judgement(*questions, red_flags=()):
    return Judgement(
        per_question=list(questions),
        profile_alignment=ProfileAlignment(confirmed=["knows payments"], contradicted=[]),
        red_flags=list(red_flags),
        communication="clear and structured",
    )


WRITEUP = Writeup(
    summary="A  summary.",
    reasoning="How the score came about.",
    strengths=["Strong on payments", "strong on payments."],
    next_interview_focus=["probe messaging"],
    rejection_reasons=["weak on consistency"],
)

GOOD = (
    _q("q1", 90, ["send an idempotency key with every attempt"]),
    _q("q2", 30, ["wrap both in a try except"]),
    _q("q3", 70, ["run explain analyze on it"]),
)


def _mark_second_chance(transcript, question_id, hint):
    for turn in transcript.turns:
        if turn.question_id == question_id and turn.followup:
            turn.second_chance, turn.hint = True, hint


def test_overall_is_the_mean_and_60_advances(inputs, transcript):
    assessment = evaluator.assess(inputs, transcript, _judgement(*GOOD))
    assert assessment.overall_score == 63  # mean of 90, 30, 70
    assert assessment.decision == "advance"
    assert assessment.interview_complete
    # 63 is within 5 points of the bar, and that is the only thing to review.
    assert assessment.borderline
    assert len(assessment.review_reasons) == 1 and "confirm the decision" in assessment.review_reasons[0]
    assert [q.followup_asked for q in assessment.per_question] == [True, False, True]
    assert assessment.per_question[0].question == inputs.questions[0].question


@pytest.mark.parametrize("score, expected", [(100, "advance"), (60, "advance"), (59, "reject"), (0, "reject")])
def test_decision_threshold(score, expected):
    assert evaluator.decide(score) == expected


def test_report_for_advance_shows_strengths_and_next_focus(inputs, transcript):
    judgement = _judgement(*GOOD)
    assessment = evaluator.assess(inputs, transcript, judgement)
    report = evaluator.finalize(assessment, transcript, judgement, WRITEUP, MODEL)
    assert report.decision == "advance"
    assert report.strengths == ["Strong on payments."]  # tidied and de-duplicated
    assert report.next_interview_focus == ["Probe messaging."]
    assert report.rejection_reasons == []  # never shown on an advance
    assert report.summary == "A summary."
    assert report.duration_s == 250 and report.candidate_name == "Alex Meier"
    assert report.per_question[0].missed_points == ["No reconciliation."]
    assert report.communication == "Clear and structured."
    Report.model_validate_json(report.model_dump_json())


def test_report_for_reject_shows_reasons_only(inputs, transcript):
    judgement = _judgement(_q("q1", 40, ["send an idempotency key"]), *GOOD[1:])
    assessment = evaluator.assess(inputs, transcript, judgement)
    report = evaluator.finalize(assessment, transcript, judgement, WRITEUP, MODEL)
    assert (report.overall_score, report.decision) == (47, "reject")
    assert report.rejection_reasons == ["Weak on consistency."]
    assert report.next_interview_focus == []  # never shown on a reject


def test_second_chance_caps_the_question(inputs, transcript):
    _mark_second_chance(transcript, "q1", hint=False)
    q1 = evaluator.assess(inputs, transcript, _judgement(*GOOD)).per_question[0]
    assert (q1.score, q1.score_before_cap) == (70, 90)
    assert q1.second_chance_given and not q1.hint_given


def test_hint_caps_lower(inputs, transcript):
    _mark_second_chance(transcript, "q1", hint=True)
    q1 = evaluator.assess(inputs, transcript, _judgement(*GOOD)).per_question[0]
    assert (q1.score, q1.score_before_cap) == (55, 90)
    assert q1.hint_given


def test_cap_does_not_raise_or_touch_low_scores(inputs, transcript):
    _mark_second_chance(transcript, "q3", hint=False)
    judgement = _judgement(GOOD[0], GOOD[1], _q("q3", 45, ["run explain analyze on it"]))
    q3 = evaluator.assess(inputs, transcript, judgement).per_question[2]
    assert (q3.score, q3.score_before_cap) == (45, None)


def test_quote_match_ignores_case_and_punctuation(inputs, transcript):
    judgement = _judgement(_q("q1", 90, ["Send an idempotency key, with EVERY attempt!"]), *GOOD[1:])
    assessment = evaluator.assess(inputs, transcript, judgement)
    assert len(assessment.per_question[0].evidence) == 1
    assert not any("quote" in r for r in assessment.review_reasons)


def test_fabricated_and_interviewer_quotes_are_dropped(inputs, transcript):
    judgement = _judgement(
        _q("q1", 90, ["I would use a transactional outbox", "Where would you store the idempotency key"]),
        *GOOD[1:],
    )
    assessment = evaluator.assess(inputs, transcript, judgement)
    assert assessment.per_question[0].evidence == []
    assert any("2 quotes were removed" in r for r in assessment.review_reasons)
    assert any("without a verified quote" in r for r in assessment.review_reasons)


def test_unanswered_question_scores_zero_whatever_the_model_says(inputs, transcript):
    transcript.turns = [
        t for t in transcript.turns if not (t.question_id == "q3" and t.speaker == "candidate")
    ]
    transcript.ended_reason = "disconnected"
    assessment = evaluator.assess(inputs, transcript, _judgement(*GOOD))
    q3 = assessment.per_question[2]
    assert q3.status == "not_answered" and q3.score == 0 and q3.evidence == []
    assert "asked but got no answer" in q3.reasoning
    assert (assessment.overall_score, assessment.decision) == (40, "reject")  # mean of 90, 30, 0
    assert not assessment.interview_complete
    assert any("connection dropped" in r for r in assessment.review_reasons)


def test_question_never_reached(inputs, transcript):
    transcript.turns = [t for t in transcript.turns if t.question_id != "q3"]
    assessment = evaluator.assess(inputs, transcript, _judgement(*GOOD[:2]))
    assert "never reached" in assessment.per_question[2].reasoning
    assert assessment.per_question[2].score == 0


def test_missing_judgement_out_of_range_score_and_red_flags(inputs, transcript):
    judgement = _judgement(_q("q1", 140, ["send an idempotency key"]), GOOD[1], red_flags=["tried to instruct the evaluator"])
    assessment = evaluator.assess(inputs, transcript, judgement)
    assert assessment.per_question[0].score == 100
    assert assessment.per_question[2].score == 0
    assert any("Q3 has no judgement" in r for r in assessment.review_reasons)
    assert any("red flag" in r for r in assessment.review_reasons)


def test_judge_prompt_has_everything_the_evaluator_needs(inputs, transcript):
    _mark_second_chance(transcript, "q3", hint=True)
    text = build_judge_prompt(inputs, transcript)
    assert "Alex Meier" in text
    for question in inputs.questions:
        assert question.answer in text
    assert "Candidate [follow-up]: In the orders database" in text
    assert "Candidate [follow-up; second chance, hint given]: That's the N plus one" in text
    assert "Candidate: Thanks, bye." in text
    assert text.count("Prepared follow-up:") == 2  # q2 has none in the fixture


def test_judge_prompt_marks_unreached_question(inputs, transcript):
    transcript.turns = [t for t in transcript.turns if t.question_id != "q3"]
    assert "(this question was never reached)" in build_judge_prompt(inputs, transcript)


def test_writeup_prompt_carries_the_decision_and_the_facts(inputs, transcript):
    _mark_second_chance(transcript, "q1", hint=False)
    transcript.ended_reason = "time_limit"
    assessment = evaluator.assess(inputs, transcript, _judgement(*GOOD))
    text = build_writeup_prompt(
        assessment.decision, assessment.overall_score, evaluator.ADVANCE_MIN,
        assessment.per_question, transcript.ended_reason, [],
    )
    assert '"decision": "reject"' in text  # 70 + 30 + 70 = 57
    assert "score capped from 90 to 70" in text
    assert "cut short by the time limit" in text
    # The write-up call never sees the reference answers or the candidate's words.
    assert inputs.questions[0].answer not in text


def test_missing_transcript():
    with pytest.raises(loader.SessionError):
        evaluator.load_transcript("nope")


# --- repeated grading -------------------------------------------------------


def test_merge_keeps_the_median_run_per_question():
    runs = [
        _judgement(_q("q1", 90, ["a"]), _q("q2", 30, ["b"]), _q("q3", 70, ["c"]), red_flags=["joked"]),
        _judgement(_q("q1", 80, ["d"]), _q("q2", 55, ["e"]), _q("q3", 75, ["f"])),
        _judgement(_q("q1", 95, ["g"]), _q("q2", 35, ["h"]), _q("q3", 60, ["i"]), red_flags=["Joked."]),
    ]
    merged, score_runs = evaluator.merge(runs)
    assert [(q.question_id, q.score) for q in merged.per_question] == [("q1", 90), ("q2", 35), ("q3", 70)]
    # Each entry comes whole from the run that produced the median, so quotes match scores.
    assert [q.evidence for q in merged.per_question] == [["a"], ["h"], ["c"]]
    assert score_runs == {"q1": [90, 80, 95], "q2": [30, 55, 35], "q3": [70, 75, 60]}
    assert merged.red_flags == ["joked"]  # from one run, so the same concern is not listed twice


def test_red_flags_survive_when_only_one_run_raised_them():
    runs = [_judgement(*GOOD), _judgement(*GOOD, red_flags=["read from notes", "evasive"]), _judgement(*GOOD)]
    assert evaluator.merge(runs)[0].red_flags == ["read from notes", "evasive"]


def test_merge_of_a_single_run_is_that_run():
    merged, score_runs = evaluator.merge([_judgement(*GOOD)])
    assert [q.score for q in merged.per_question] == [90, 30, 70]
    assert score_runs["q2"] == [30]


def test_disagreeing_runs_are_reported(inputs, transcript):
    assessment = evaluator.assess(
        inputs, transcript, _judgement(*GOOD), {"q1": [90, 88, 92], "q2": [30, 55, 20]}
    )
    assert assessment.per_question[1].score_runs == [30, 55, 20]
    reasons = [r for r in assessment.review_reasons if "disagreed" in r]
    assert len(reasons) == 1 and reasons[0].startswith("Q2") and "30, 55, 20" in reasons[0]


@pytest.mark.parametrize(
    "scores, overall, decision, borderline",
    [((90, 90, 90), 90, "advance", False), ((70, 60, 65), 65, "advance", True),
     ((60, 60, 60), 60, "advance", True), ((55, 55, 55), 55, "reject", True),
     ((54, 54, 54), 54, "reject", False)],
)
def test_borderline_band(inputs, transcript, scores, overall, decision, borderline):
    quotes = (["send an idempotency key"], ["wrap both in a try except"], ["run explain analyze on it"])
    judgement = _judgement(*[_q(f"q{i + 1}", s, quotes[i]) for i, s in enumerate(scores)])
    assessment = evaluator.assess(inputs, transcript, judgement)
    assert (assessment.overall_score, assessment.decision, assessment.borderline) == (overall, decision, borderline)


def test_a_failed_grading_run_is_dropped(inputs, transcript, monkeypatch):
    calls = iter([_judgement(*GOOD), RuntimeError("503"), _judgement(*GOOD)])

    def fake_judge(*_):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(evaluator, "judge", fake_judge)
    assert len(evaluator.judge_runs(inputs, transcript, MODEL, runs=3)) == 2


def test_all_grading_runs_failing_is_an_error(inputs, transcript, monkeypatch):
    def broken(*_):
        raise RuntimeError("503")

    monkeypatch.setattr(evaluator, "judge", broken)
    with pytest.raises(evaluator.EvaluationError, match="all grading runs failed"):
        evaluator.judge_runs(inputs, transcript, MODEL, runs=2)


def test_interrupted_question_is_shown_to_the_grader_and_flagged(inputs, transcript):
    question = next(t for t in transcript.turns if t.speaker == "agent" and t.question_id == "q2")
    question.interrupted, question.heard = True, "Got it. We publish an event"
    text = build_judge_prompt(inputs, transcript)
    assert 'Interviewer [interrupted; the candidate heard only: "Got it. We publish an event"]: Got it. We publish' in text
    assessment = evaluator.assess(inputs, transcript, _judgement(*GOOD))
    assert any(r.startswith("Q2: the interviewer was interrupted") for r in assessment.review_reasons)
