"""Load the interview inputs for a session: candidate profile + question docs.

Layout (under data/<session>/, falling back to fixtures/<session>/):

    candidate.md
    questions/q1.md  questions/q2.md  questions/q3.md
"""

import dataclasses
import pathlib
import re

from src.shared.models import Followup, Question

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
FIXTURES_DIR = ROOT / "fixtures"

NUM_QUESTIONS = 3
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_HEADING = re.compile(r"^(#{1,2})\s+(.+?)\s*#*\s*$")
_NAME_LINE = re.compile(r"^\W*name\W*:\W*(.+?)\W*$", re.IGNORECASE | re.MULTILINE)
_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class SessionError(Exception):
    """The session inputs are missing or malformed."""


@dataclasses.dataclass
class InterviewInputs:
    session_id: str
    candidate_name: str
    candidate_profile: str
    questions: list[Question]


def _key(heading: str) -> str:
    """Normalise a heading: 'Follow-up' / 'Follow up' / 'Followup' -> 'followup'."""
    return re.sub(r"[^a-z]", "", heading.lower())


def _sections(text: str) -> dict[str, str]:
    """Split a question doc into {'question': ..., 'followup.answer': ...}."""
    sections: dict[str, list[str]] = {}
    parent = ""
    current: str | None = None
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            level, key = len(match.group(1)), _key(match.group(2))
            if level == 1:
                parent = key
                current = key
            else:
                current = f"{parent}.{key}" if parent else key
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def parse_question(question_id: str, text: str) -> Question:
    sections = _sections(text)

    def required(key: str) -> str:
        value = sections.get(key, "")
        if not value:
            raise SessionError(f"{question_id}: missing or empty section '{key}'")
        return value

    followup = None
    if any(k == "followup" or k.startswith("followup.") for k in sections):
        followup = Followup(
            question=required("followup.question"),
            answer=required("followup.answer"),
            context=required("followup.context"),
        )
    return Question(
        id=question_id,
        question=required("question"),
        answer=required("answer"),
        context=required("context"),
        followup=followup,
    )


def candidate_name(profile: str) -> str:
    """Best-effort name from a free-form profile: a 'Name:' line, else the title."""
    match = _NAME_LINE.search(profile) or _H1.search(profile)
    return match.group(1).strip() if match else "Candidate"


def session_dir(session_id: str) -> pathlib.Path:
    if not _SESSION_ID.match(session_id):
        raise SessionError(f"invalid session id: {session_id!r}")
    for base in (DATA_DIR, FIXTURES_DIR):
        path = base / session_id
        if (path / "questions").is_dir():
            return path
    raise SessionError(f"no inputs found for session {session_id!r}")


def load_session(session_id: str) -> InterviewInputs:
    path = session_dir(session_id)

    profile_path = path / "candidate.md"
    if not profile_path.is_file():
        raise SessionError(f"missing {profile_path.relative_to(ROOT)}")
    profile = profile_path.read_text(encoding="utf-8").strip()

    docs = sorted((path / "questions").glob("*.md"))
    if len(docs) != NUM_QUESTIONS:
        raise SessionError(
            f"expected {NUM_QUESTIONS} question docs in "
            f"{(path / 'questions').relative_to(ROOT)}, found {len(docs)}"
        )
    questions = [
        parse_question(doc.stem, doc.read_text(encoding="utf-8")) for doc in docs
    ]
    return InterviewInputs(
        session_id=session_id,
        candidate_name=candidate_name(profile),
        candidate_profile=profile,
        questions=questions,
    )
