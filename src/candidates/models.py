"""Models for candidates: one candidate is one session folder under data/."""

from typing import Literal

import pydantic

from src.shared.models import Question, Report, Transcript

Preparation = Literal["preparing", "ready", "failed"]
# What the recruiter sees. Derived from the files in the session folder.
Status = Literal[
    "preparing", "failed", "invited", "in_progress", "interviewed", "advance", "reject"
]


class CandidateRecord(pydantic.BaseModel):
    """data/<session_id>/candidate.json: what the recruiter entered, plus preparation state."""

    session_id: str
    created_at: str
    first_name: str
    last_name: str
    github_url: str | None = None
    cv_filename: str | None = None
    role: str
    looking_for: str = ""
    repo_url: str
    subdir: str = ""
    preparation: Preparation = "preparing"
    # How many times the interview has been started through the candidate's link.
    attempts: int = 0
    # What the preparation is doing right now, for the progress line in the UI.
    stage: str = ""
    error: str | None = None
    warnings: list[str] = []

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class CandidateSummary(pydantic.BaseModel):
    """One row of the candidates list."""

    session_id: str
    created_at: str
    first_name: str
    last_name: str
    role: str
    status: Status
    stage: str = ""
    error: str | None = None
    warnings: list[str] = []
    interview_url: str
    interviewed_at: str | None = None
    duration_s: int | None = None
    overall_score: int | None = None
    borderline: bool = False
    needs_human_review: bool = False


class CandidateDetail(pydantic.BaseModel):
    """Everything about one candidate. Parts are null until they exist."""

    summary: CandidateSummary
    record: CandidateRecord
    profile: str | None = None
    context: dict | None = None
    questions: list[Question] | None = None
    transcript: Transcript | None = None
    report: Report | None = None


class ProfileSummary(pydantic.BaseModel):
    """Gemini's structured summary of a candidate's GitHub profile and CV."""

    headline: str
    summary: str
    skills: list[str]
    experience: list[str]
    notable_projects: list[str]
    open_points: list[str]
