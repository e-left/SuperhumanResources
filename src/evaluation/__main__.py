"""CLI: python -m src.evaluation <session>"""

import sys

import dotenv

from src.evaluation import evaluator
from src.interview import loader


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m src.evaluation <session>", file=sys.stderr)
        return 2
    dotenv.load_dotenv(loader.ROOT / ".env")
    try:
        report = evaluator.evaluate(sys.argv[1])
    except (evaluator.EvaluationError, loader.SessionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{report.candidate_name}: {report.overall_score}/100, {report.recommendation}")
    for question in report.per_question:
        print(f"  {question.question_id}: {question.score} ({question.status})")
    for reason in report.review_reasons:
        print(f"  review: {reason}")
    print(f"written to {evaluator.report_path(report.session_id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
