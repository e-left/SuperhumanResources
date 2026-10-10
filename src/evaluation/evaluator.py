"""Evaluation agent: transcript + question docs + profile -> Report.

The model judges, the code decides:

1. judge_runs()     Gemini grades each answer, several times in parallel.
   merge()          Code keeps, per question, the run with the median score.
2. assess()         Code checks the judgement against the transcript, applies
                    the scoring rules and fixes the decision (Assessment).
3. write_decision() Gemini explains the decision that code made (Writeup).
4. finalize()       Code assembles the Report.
"""

import concurrent.futures
import dataclasses
import datetime
import logging
import os
import pathlib
import re
import statistics

from src.evaluation import prompt
from src.interview import loader
from src.interview.loader import InterviewInputs
from src.shared.models import (
    Judgement,
    QuestionJudgement,
    QuestionReport,
    Report,
    Transcript,
    Writeup,
)

logger = logging.getLogger("interview")

# Overall score needed to move on to the next round. One constant for now.
ADVANCE_MIN = 60
# A question that needed a second chance cannot score above these.
SECOND_CHANCE_CAP = 70
HINT_CAP = 55
# Grading is repeated and the median taken, so one unusual run cannot flip a decision.
JUDGE_RUNS = 3
# Runs further apart than this on one question are reported for review.
MAX_RUN_SPREAD = 20
# Within this many points of ADVANCE_MIN, a person should confirm the decision.
BORDERLINE_MARGIN = 5


class EvaluationError(Exception):
    pass


@dataclasses.dataclass
class Assessment:
    per_question: list[QuestionReport]
    overall_score: int
    decision: str
    borderline: bool
    interview_complete: bool
    review_reasons: list[str]


def load_transcript(session_id: str) -> Transcript:
    loader.session_dir(session_id)  # validates the id
    for base in (loader.DATA_DIR, loader.FIXTURES_DIR):
        path = base / session_id / "transcript.json"
        if path.is_file():
            return Transcript.model_validate_json(path.read_text(encoding="utf-8"))
    raise EvaluationError(f"no transcript found for session {session_id!r}")


def _generate(model: str, system: str, contents: str, schema):
    """One Gemini call with structured output."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise EvaluationError("missing environment variable: GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.1,
        ),
    )
    if isinstance(response.parsed, schema):
        return response.parsed
    try:
        return schema.model_validate_json(response.text or "")
    except ValueError as exc:
        raise EvaluationError(f"evaluator returned invalid JSON: {exc}") from exc


def judge(inputs: InterviewInputs, transcript: Transcript, model: str) -> Judgement:
    """Ask Gemini to grade each answer, once."""
    contents = prompt.build_judge_prompt(inputs, transcript)
    return _generate(model, prompt.JUDGE_SYSTEM, contents, Judgement)


def judge_runs(
    inputs: InterviewInputs, transcript: Transcript, model: str, runs: int = JUDGE_RUNS
) -> list[Judgement]:
    """Grade the interview `runs` times in parallel. Failed runs are dropped."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=runs) as pool:
        futures = [pool.submit(judge, inputs, transcript, model) for _ in range(runs)]
    judgements, error = [], None
    for future in futures:
        try:
            judgements.append(future.result())
        except Exception as exc:
            error = exc
            logger.warning("a grading run failed: %s", exc)
    if not judgements:
        raise EvaluationError(f"all grading runs failed: {error}")
    return judgements


def merge(judgements: list[Judgement]) -> tuple[Judgement, dict[str, list[int]]]:
    """Combine several grading runs into one judgement.

    Per question, keep the whole entry (score, reasoning, quotes) from the run
    whose score is the median, so the text always matches the number. Returns
    the merged judgement and every run's score per question.
    """
    question_ids: list[str] = []
    for judgement in judgements:
        for entry in judgement.per_question:
            if entry.question_id not in question_ids:
                question_ids.append(entry.question_id)

    per_question, score_runs = [], {}
    for question_id in question_ids:
        entries = [e for j in judgements for e in j.per_question if e.question_id == question_id]
        scores = [e.score for e in entries]
        median = statistics.median_low(scores)
        per_question.append(next(e for e in entries if e.score == median))
        score_runs[question_id] = scores

    # Profile notes and the communication remark come from the middle run overall.
    totals = [sum(e.score for e in j.per_question) for j in judgements]
    middle = judgements[totals.index(statistics.median_low(totals))]
    # Red flags are kept if any run raised them. The runs word the same concern
    # differently, so take them from the run that raised the most, not all runs.
    red_flags = max((j.red_flags for j in judgements), key=len)
    merged = Judgement(
        per_question=per_question,
        profile_alignment=middle.profile_alignment,
        red_flags=red_flags,
        communication=middle.communication,
    )
    return merged, score_runs


def write_decision(
    assessment: Assessment, transcript: Transcript, judgement: Judgement, model: str
) -> Writeup:
    """Ask Gemini to explain the decision that assess() made."""
    contents = prompt.build_writeup_prompt(
        assessment.decision,
        assessment.overall_score,
        ADVANCE_MIN,
        assessment.per_question,
        transcript.ended_reason,
        judgement.red_flags,
        assessment.borderline,
    )
    return _generate(model, prompt.WRITEUP_SYSTEM, contents, Writeup)


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _sentence(text: str) -> str:
    """Tidy model prose: one line, capitalised, ending with punctuation."""
    text = " ".join(str(text).split()).lstrip("-•* ").strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _points(items: list[str]) -> list[str]:
    """Tidy a list of points and drop empty or repeated ones."""
    seen, result = set(), []
    for item in items:
        point = _sentence(item)
        key = _normalise(point)
        if key and key not in seen:
            seen.add(key)
            result.append(point)
    return result


def decide(overall_score: int) -> str:
    return "advance" if overall_score >= ADVANCE_MIN else "reject"


def _empty(question_id: str, reasoning: str, gaps: list[str]) -> QuestionJudgement:
    return QuestionJudgement(
        question_id=question_id,
        score=0,
        reasoning=reasoning,
        covered_points=[],
        missed_points=[],
        strengths=[],
        gaps=gaps,
        evidence=[],
    )


def assess(
    inputs: InterviewInputs,
    transcript: Transcript,
    judgement: Judgement,
    score_runs: dict[str, list[int]] | None = None,
) -> Assessment:
    judged = {j.question_id: j for j in judgement.per_question}
    score_runs = score_runs or {}
    # Quotes are checked against everything the candidate said, not only the
    # turns tagged with that question: tagging can be off by a turn.
    spoken = _normalise(" ".join(t.text for t in transcript.turns if t.speaker == "candidate"))
    review_reasons: list[str] = []
    per_question: list[QuestionReport] = []

    for question in inputs.questions:
        turns = [t for t in transcript.turns if t.question_id == question.id]
        asked = any(t.speaker == "agent" for t in turns)
        answered = any(t.speaker == "candidate" and _normalise(t.text) for t in turns)
        facts = {
            "question": question.question,
            "followup_asked": any(t.followup for t in turns),
            "second_chance_given": any(t.second_chance for t in turns),
            "hint_given": any(t.hint for t in turns),
        }
        result = judged.get(question.id)
        label = question.id.upper()
        if any(t.speaker == "agent" and t.interrupted for t in turns):
            review_reasons.append(
                f"{label}: the interviewer was interrupted while speaking; check that the "
                "candidate heard the whole question."
            )

        if not answered:
            why = "was asked but got no answer" if asked else "was never reached"
            empty = _empty(
                question.id,
                f"This question {why}, so there is nothing to grade. It scores 0.",
                ["No answer was given."],
            )
            per_question.append(
                QuestionReport(**empty.model_dump(), status="not_answered", **facts)
            )
            review_reasons.append(f"{question.id.upper()} {why}.")
            continue

        if result is None:
            result = _empty(
                question.id, "The evaluator returned no judgement for this question.", []
            )
            review_reasons.append(f"{question.id.upper()} has no judgement from the evaluator.")

        evidence = [
            " ".join(q.split()) for q in result.evidence if _normalise(q) and _normalise(q) in spoken
        ]
        dropped = len(result.evidence) - len(evidence)
        if dropped:
            quotes = "1 quote was" if dropped == 1 else f"{dropped} quotes were"
            review_reasons.append(
                f"{question.id.upper()}: {quotes} removed because the transcript does not contain them."
            )

        runs = score_runs.get(question.id, [])
        if runs and max(runs) - min(runs) > MAX_RUN_SPREAD:
            review_reasons.append(
                f"{label}: the grading runs disagreed ({', '.join(map(str, runs))}); "
                "the median was used."
            )

        score = max(0, min(100, result.score))
        score_before_cap = None
        if facts["second_chance_given"]:
            cap = HINT_CAP if facts["hint_given"] else SECOND_CHANCE_CAP
            if score > cap:
                score_before_cap, score = score, cap
        if score > 0 and not evidence:
            review_reasons.append(f"{question.id.upper()} is scored without a verified quote.")

        per_question.append(
            QuestionReport(
                question_id=question.id,
                score=score,
                score_before_cap=score_before_cap,
                reasoning=_sentence(result.reasoning),
                covered_points=_points(result.covered_points),
                missed_points=_points(result.missed_points),
                strengths=_points(result.strengths),
                gaps=_points(result.gaps),
                evidence=evidence,
                score_runs=runs,
                status="answered",
                **facts,
            )
        )

    flags = len(_points(judgement.red_flags))
    if flags:
        review_reasons.append(
            "1 red flag was raised." if flags == 1 else f"{flags} red flags were raised."
        )
    if transcript.ended_reason not in (None, "completed"):
        review_reasons.append(prompt.ENDINGS[transcript.ended_reason])

    overall = round(statistics.mean(q.score for q in per_question))
    borderline = abs(overall - ADVANCE_MIN) <= BORDERLINE_MARGIN
    if borderline:
        review_reasons.append(
            f"The overall score is within {BORDERLINE_MARGIN} points of the advance bar "
            f"({ADVANCE_MIN}); a person should confirm the decision."
        )
    return Assessment(
        per_question=per_question,
        overall_score=overall,
        decision=decide(overall),
        borderline=borderline,
        interview_complete=all(q.status == "answered" for q in per_question),
        review_reasons=review_reasons,
    )


def _duration(transcript: Transcript) -> int | None:
    try:
        started = datetime.datetime.fromisoformat(transcript.started_at)
        ended = datetime.datetime.fromisoformat(transcript.ended_at)
    except ValueError:
        return None
    return max(0, round((ended - started).total_seconds()))


def finalize(
    assessment: Assessment,
    transcript: Transcript,
    judgement: Judgement,
    writeup: Writeup,
    model: str,
) -> Report:
    advance = assessment.decision == "advance"
    return Report(
        session_id=transcript.session_id,
        candidate_name=transcript.candidate_name,
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        model=model,
        overall_score=assessment.overall_score,
        decision=assessment.decision,
        borderline=assessment.borderline,
        summary=" ".join(writeup.summary.split()),
        reasoning=" ".join(writeup.reasoning.split()),
        strengths=_points(writeup.strengths),
        # Each decision shows only its own section, whatever the model returned.
        next_interview_focus=_points(writeup.next_interview_focus) if advance else [],
        rejection_reasons=[] if advance else _points(writeup.rejection_reasons),
        interview_complete=assessment.interview_complete,
        ended_reason=transcript.ended_reason,
        duration_s=_duration(transcript),
        needs_human_review=bool(assessment.review_reasons),
        review_reasons=assessment.review_reasons,
        per_question=assessment.per_question,
        profile_alignment=judgement.profile_alignment.model_copy(
            update={
                "confirmed": _points(judgement.profile_alignment.confirmed),
                "contradicted": _points(judgement.profile_alignment.contradicted),
            }
        ),
        red_flags=_points(judgement.red_flags),
        communication=_sentence(judgement.communication),
    )


def report_path(session_id: str) -> pathlib.Path:
    return loader.DATA_DIR / session_id / "report.json"


def load_report(session_id: str) -> Report | None:
    loader.session_dir(session_id)  # validates the id
    path = report_path(session_id)
    if not path.is_file():
        return None
    try:
        return Report.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None  # written by an older version of the report contract


def evaluate(session_id: str) -> Report:
    """Run the full evaluation for a session and write data/<session>/report.json."""
    inputs = loader.load_session(session_id)
    transcript = load_transcript(session_id)
    model = os.environ.get("GEMINI_MODEL", "").strip()
    if not model:
        raise EvaluationError("missing environment variable: GEMINI_MODEL")
    judgement, score_runs = merge(judge_runs(inputs, transcript, model))
    assessment = assess(inputs, transcript, judgement, score_runs)
    writeup = write_decision(assessment, transcript, judgement, model)
    report = finalize(assessment, transcript, judgement, writeup, model)
    path = report_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report
