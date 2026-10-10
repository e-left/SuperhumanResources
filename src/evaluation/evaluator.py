"""Evaluation agent: transcript + question docs + profile -> Report.

The LLM judges each answer (judge). Code then decides everything that should be
deterministic or checkable (finalize): the overall score, the recommendation,
which questions were actually answered, and whether each quote is real.
"""

import datetime
import os
import re
import statistics

from src.evaluation.prompt import SYSTEM, build_prompt
from src.interview import loader
from src.interview.loader import InterviewInputs
from src.shared.models import (
    Judgement,
    QuestionJudgement,
    QuestionReport,
    Report,
    Transcript,
)

STRONG_HIRE_MIN = 80
HIRE_MIN = 60


class EvaluationError(Exception):
    pass


def load_transcript(session_id: str) -> Transcript:
    loader.session_dir(session_id)  # validates the id
    for base in (loader.DATA_DIR, loader.FIXTURES_DIR):
        path = base / session_id / "transcript.json"
        if path.is_file():
            return Transcript.model_validate_json(path.read_text(encoding="utf-8"))
    raise EvaluationError(f"no transcript found for session {session_id!r}")


def judge(inputs: InterviewInputs, transcript: Transcript, model: str) -> Judgement:
    """Ask Gemini for a structured judgement of the interview."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise EvaluationError("missing environment variable: GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=build_prompt(inputs, transcript),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=Judgement,
            temperature=0.1,
        ),
    )
    if isinstance(response.parsed, Judgement):
        return response.parsed
    try:
        return Judgement.model_validate_json(response.text or "")
    except ValueError as exc:
        raise EvaluationError(f"evaluator returned invalid JSON: {exc}") from exc


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def recommendation(score: int) -> str:
    if score >= STRONG_HIRE_MIN:
        return "strong_hire"
    if score >= HIRE_MIN:
        return "hire"
    return "no_hire"


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


def finalize(
    inputs: InterviewInputs, transcript: Transcript, judgement: Judgement, model: str
) -> Report:
    judged = {j.question_id: j for j in judgement.per_question}
    # Quotes are checked against everything the candidate said, not only the
    # turns tagged with that question: tagging can be off by a turn.
    spoken = _normalise(" ".join(t.text for t in transcript.turns if t.speaker == "candidate"))
    review_reasons: list[str] = []
    per_question: list[QuestionReport] = []

    for question in inputs.questions:
        turns = [t for t in transcript.turns if t.question_id == question.id]
        asked = any(t.speaker == "agent" for t in turns)
        answered = any(t.speaker == "candidate" and _normalise(t.text) for t in turns)
        followup_asked = any(t.followup for t in turns)
        result = judged.get(question.id)

        if not answered:
            why = "was asked but got no answer" if asked else "was never reached"
            empty = _empty(
                question.id,
                f"This question {why}, so there is nothing to grade. It scores 0.",
                ["No answer given"],
            )
            per_question.append(
                QuestionReport(
                    **empty.model_dump(),
                    question=question.question,
                    status="not_answered",
                    followup_asked=followup_asked,
                )
            )
            review_reasons.append(f"{question.id} {why}")
            continue

        if result is None:
            result = _empty(
                question.id, "The evaluator returned no judgement for this question.", []
            )
            review_reasons.append(f"{question.id} has no judgement from the evaluator")

        evidence = [q for q in result.evidence if _normalise(q) and _normalise(q) in spoken]
        dropped = len(result.evidence) - len(evidence)
        if dropped:
            review_reasons.append(
                f"{question.id}: {dropped} quote(s) not found in the transcript were removed"
            )
        score = max(0, min(100, result.score))
        if score > 0 and not evidence:
            review_reasons.append(f"{question.id} is scored without a verified quote")

        per_question.append(
            QuestionReport(
                **result.model_dump(exclude={"score", "evidence"}),
                score=score,
                evidence=evidence,
                question=question.question,
                status="answered",
                followup_asked=followup_asked,
            )
        )

    if judgement.red_flags:
        review_reasons.append(f"{len(judgement.red_flags)} red flag(s) raised")

    complete = all(q.status == "answered" for q in per_question)
    overall = round(statistics.mean(q.score for q in per_question))
    summary = judgement.summary
    if not complete:
        missing = ", ".join(q.question_id for q in per_question if q.status != "answered")
        summary = (
            f"Incomplete interview: {missing} not answered and scored 0, which weighs "
            f"heavily on the result. {summary}"
        )

    return Report(
        session_id=transcript.session_id,
        candidate_name=transcript.candidate_name,
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        model=model,
        overall_score=overall,
        recommendation=recommendation(overall),
        summary=summary,
        reasoning=judgement.reasoning,
        interview_complete=complete,
        needs_human_review=bool(review_reasons),
        review_reasons=review_reasons,
        per_question=per_question,
        profile_alignment=judgement.profile_alignment,
        red_flags=judgement.red_flags,
        suggested_next_steps=judgement.suggested_next_steps,
        communication=judgement.communication,
    )


def report_path(session_id: str):
    return loader.DATA_DIR / session_id / "report.json"


def load_report(session_id: str) -> Report | None:
    loader.session_dir(session_id)  # validates the id
    path = report_path(session_id)
    if not path.is_file():
        return None
    return Report.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate(session_id: str) -> Report:
    """Run the full evaluation for a session and write data/<session>/report.json."""
    inputs = loader.load_session(session_id)
    transcript = load_transcript(session_id)
    model = os.environ.get("GEMINI_MODEL", "").strip()
    if not model:
        raise EvaluationError("missing environment variable: GEMINI_MODEL")
    report = finalize(inputs, transcript, judge(inputs, transcript, model), model)
    path = report_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report
