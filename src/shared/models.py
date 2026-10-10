"""Pydantic models for the contracts in CONTEXT.md section 6."""

from typing import Literal

import pydantic

EndedReason = Literal["completed", "time_limit", "disconnected", "stopped"]
Decision = Literal["advance", "reject"]


class Followup(pydantic.BaseModel):
    question: str
    answer: str
    context: str


class Question(pydantic.BaseModel):
    id: str
    question: str
    answer: str
    context: str
    followup: Followup | None = None


class Turn(pydantic.BaseModel):
    speaker: Literal["agent", "candidate"]
    # None for turns outside any question (introduction, closing).
    question_id: str | None = None
    followup: bool = False
    # True from the interviewer's "try again" until the next question or follow-up.
    second_chance: bool = False
    # True when that second chance came with a hint.
    hint: bool = False
    # Agent turns only: the interviewer was cut off before finishing. `text` is
    # then the full wording it meant to say and `heard` the part that was spoken.
    interrupted: bool = False
    heard: str | None = None
    text: str
    t: float


class Transcript(pydantic.BaseModel):
    session_id: str
    candidate_name: str
    started_at: str
    ended_at: str
    ended_reason: EndedReason | None = None
    turns: list[Turn]


# --- Evaluation -------------------------------------------------------------
#
# Judgement and Writeup are Gemini response schemas: every field is required
# and has no default, which is what structured output handles most reliably.


class ProfileAlignment(pydantic.BaseModel):
    confirmed: list[str]
    contradicted: list[str]


class QuestionJudgement(pydantic.BaseModel):
    """What the evaluator LLM returns for one question."""

    question_id: str
    score: int
    reasoning: str
    covered_points: list[str]
    missed_points: list[str]
    strengths: list[str]
    gaps: list[str]
    evidence: list[str]


class Judgement(pydantic.BaseModel):
    """First evaluator call: grade each answer."""

    per_question: list[QuestionJudgement]
    profile_alignment: ProfileAlignment
    red_flags: list[str]
    communication: str


class Writeup(pydantic.BaseModel):
    """Second evaluator call: explain a decision that code has already made."""

    summary: str
    reasoning: str
    strengths: list[str]
    next_interview_focus: list[str]
    rejection_reasons: list[str]


class QuestionReport(QuestionJudgement):
    question: str
    status: Literal["answered", "not_answered"]
    followup_asked: bool = False
    second_chance_given: bool = False
    hint_given: bool = False
    # The evaluator's score before the second-chance cap, when the cap lowered it.
    score_before_cap: int | None = None
    # The score from each grading run; `score` starts from their median.
    score_runs: list[int] = []


class Report(pydantic.BaseModel):
    session_id: str
    candidate_name: str
    generated_at: str
    model: str
    overall_score: int
    decision: Decision
    # The overall score is close to the bar: a person should confirm the decision.
    borderline: bool = False
    summary: str
    reasoning: str
    # Filled when the decision is "advance".
    strengths: list[str]
    next_interview_focus: list[str]
    # Filled when the decision is "reject".
    rejection_reasons: list[str]
    interview_complete: bool
    ended_reason: EndedReason | None = None
    duration_s: int | None = None
    needs_human_review: bool
    review_reasons: list[str]
    per_question: list[QuestionReport]
    profile_alignment: ProfileAlignment
    red_flags: list[str]
    communication: str
