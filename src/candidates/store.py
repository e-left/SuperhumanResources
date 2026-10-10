"""Candidate records on disk, and the status derived from a session folder."""

import datetime
import json
import pathlib
import re
import uuid

from src.candidates.models import CandidateDetail, CandidateRecord, CandidateSummary
from src.interview import loader
from src.shared.models import Report, Transcript

_SESSION_ID = re.compile(r"^[a-f0-9]{32}$")
# A preparation still marked as running after this long was lost (server restart).
STALE_AFTER_S = 5 * 60
# Interviews that ended this way are over for good.
FINAL_ENDINGS = ("completed", "time_limit")
# The interview may be started twice at most: once, plus one retake that is only
# allowed when the first attempt ended before any question was answered.
MAX_ATTEMPTS = 2


class NotFound(Exception):
    pass


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def directory(session_id: str) -> pathlib.Path:
    if not _SESSION_ID.match(session_id):
        raise NotFound(f"no candidate {session_id!r}")
    return loader.DATA_DIR / session_id


def create(**fields) -> CandidateRecord:
    record = CandidateRecord(
        session_id=uuid.uuid4().hex, created_at=_now().isoformat(timespec="seconds"), **fields
    )
    directory(record.session_id).mkdir(parents=True)
    write(record)
    return record


def write(record: CandidateRecord) -> None:
    path = directory(record.session_id) / "candidate.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def read(session_id: str) -> CandidateRecord:
    path = directory(session_id) / "candidate.json"
    if not path.is_file():
        raise NotFound(f"no candidate {session_id!r}")
    return CandidateRecord.model_validate_json(path.read_text(encoding="utf-8"))


def exists(session_id: str) -> bool:
    try:
        return (directory(session_id) / "candidate.json").is_file()
    except NotFound:
        return False


def list_records() -> list[CandidateRecord]:
    records = []
    if loader.DATA_DIR.is_dir():
        for path in loader.DATA_DIR.glob("*/candidate.json"):
            try:
                records.append(CandidateRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError:
                continue  # a half-written or foreign file; skip it
    return sorted(records, key=lambda r: r.created_at, reverse=True)


def _load(path: pathlib.Path, model):
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def transcript(session_id: str) -> Transcript | None:
    return _load(directory(session_id) / "transcript.json", Transcript)


def report(session_id: str) -> Report | None:
    return _load(directory(session_id) / "report.json", Report)


def answered_a_question(found: Transcript | None) -> bool:
    """The candidate said something in reply to a question (not just the hello)."""
    return found is not None and any(
        turn.speaker == "candidate" and turn.question_id is not None for turn in found.turns
    )


def interview_state(session_id: str) -> str:
    """Whether a candidate's link can start an interview.

    'not_ready'  the questions are still being prepared (or preparation failed)
    'ready'      the interview can start: the first time, or the one retake
                 allowed when the earlier attempt ended (connection dropped or
                 stopped) before the candidate answered any question
    'done'       the interview ran to the end or hit the time limit
    'closed'     it ended early and cannot be restarted: a question had already
                 been answered, or the one retake has been used
    """
    record = read(session_id)
    if record.preparation != "ready":
        return "not_ready"
    found = transcript(session_id)
    if found is not None and found.ended_reason in FINAL_ENDINGS:
        return "done"
    if record.attempts == 0:
        return "ready"
    if answered_a_question(found) or record.attempts >= MAX_ATTEMPTS:
        return "closed"
    return "ready"


def start_attempt(session_id: str) -> int:
    """Count an interview start. Returns the attempt number (1 or 2)."""
    record = read(session_id)
    record.attempts += 1
    write(record)
    return record.attempts


def _duration(found: Transcript) -> int | None:
    try:
        started = datetime.datetime.fromisoformat(found.started_at)
        ended = datetime.datetime.fromisoformat(found.ended_at)
    except ValueError:
        return None
    return max(0, round((ended - started).total_seconds()))


def summarize(record: CandidateRecord) -> CandidateSummary:
    found_transcript = transcript(record.session_id)
    found_report = report(record.session_id)
    if record.preparation != "ready":
        status = record.preparation
    elif found_transcript is None:
        status = "invited"
    elif found_transcript.ended_reason is None:
        status = "in_progress"
    elif found_report is None and interview_state(record.session_id) == "ready":
        # The attempt dropped before any question was answered and the retake is
        # still open: nothing to evaluate yet, the candidate can start again.
        status = "invited"
    elif found_report is None:
        status = "interviewed"
    else:
        status = found_report.decision
    return CandidateSummary(
        session_id=record.session_id,
        created_at=record.created_at,
        first_name=record.first_name,
        last_name=record.last_name,
        role=record.role,
        status=status,
        stage=record.stage if status == "preparing" else "",
        error=record.error,
        warnings=record.warnings,
        interview_url=f"/?session={record.session_id}",
        interviewed_at=found_transcript.started_at if found_transcript else None,
        duration_s=_duration(found_transcript) if found_transcript else None,
        overall_score=found_report.overall_score if found_report else None,
        borderline=found_report.borderline if found_report else False,
        needs_human_review=found_report.needs_human_review if found_report else False,
    )


def detail(record: CandidateRecord) -> CandidateDetail:
    folder = directory(record.session_id)
    profile = context = questions = None
    if (folder / "candidate.md").is_file():
        profile = (folder / "candidate.md").read_text(encoding="utf-8")
    if (folder / "context.json").is_file():
        try:
            context = json.loads((folder / "context.json").read_text(encoding="utf-8"))
        except ValueError:
            context = None
    if (folder / "questions").is_dir():
        try:
            questions = [
                loader.parse_question(doc.stem, doc.read_text(encoding="utf-8"))
                for doc in sorted((folder / "questions").glob("*.md"))
            ]
        except loader.SessionError:
            questions = None
    return CandidateDetail(
        summary=summarize(record),
        record=record,
        profile=profile,
        context=context,
        questions=questions,
        transcript=transcript(record.session_id),
        report=report(record.session_id),
    )


def fail_stale() -> int:
    """Mark preparations that were interrupted (e.g. by a restart) as failed."""
    count = 0
    for record in list_records():
        if record.preparation != "preparing":
            continue
        age = (_now() - datetime.datetime.fromisoformat(record.created_at)).total_seconds()
        if age > STALE_AFTER_S:
            record.preparation = "failed"
            record.error = "Preparation was interrupted. Create the candidate again."
            write(record)
            count += 1
    return count
