"""Pydantic models for the contracts in CONTEXT.md section 6."""

from typing import Literal

import pydantic


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
    text: str
    t: float


class Transcript(pydantic.BaseModel):
    session_id: str
    candidate_name: str
    started_at: str
    ended_at: str
    turns: list[Turn]


# --- Evaluation -------------------------------------------------------------


class ProfileAlignment(pydantic.BaseModel):
    confirmed: list[str]
    contradicted: list[str]


# The two models below are Gemini's response schema: every field is required
# and has no default, which is what structured output handles most reliably.


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
    """The evaluator LLM's structured output. Code turns it into a Report."""

    per_question: list[QuestionJudgement]
    summary: str
    reasoning: str
    profile_alignment: ProfileAlignment
    red_flags: list[str]
    suggested_next_steps: list[str]
    communication: str


class QuestionReport(QuestionJudgement):
    question: str
    status: Literal["answered", "not_answered"]
    followup_asked: bool = False


class Report(pydantic.BaseModel):
    session_id: str
    candidate_name: str
    generated_at: str
    model: str
    overall_score: int
    recommendation: Literal["strong_hire", "hire", "no_hire"]
    summary: str
    reasoning: str
    interview_complete: bool
    needs_human_review: bool
    review_reasons: list[str]
    per_question: list[QuestionReport]
    profile_alignment: ProfileAlignment
    red_flags: list[str]
    suggested_next_steps: list[str]
    communication: str
