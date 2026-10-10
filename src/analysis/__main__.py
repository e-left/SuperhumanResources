"""Run: python -m src.analysis --path demo-proj"""

import argparse
import json
from pathlib import Path
import sys

import dotenv

from src.analysis import agent
from src.analysis.repository import AnalysisError
from src.interview import loader


def main() -> int:
    parser = argparse.ArgumentParser(description="Let Gemini read a codebase and generate three interview questions.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--path", type=Path, help="local codebase directory")
    source.add_argument("--repo-url", help="public GitHub repository URL")
    parser.add_argument("--subdir", default="", help="project directory inside the repository")
    parser.add_argument("--role", default="Software Engineer")
    args = parser.parse_args()
    dotenv.load_dotenv(loader.ROOT / ".env")
    try:
        if args.path:
            result = agent.analyze(agent.project_root(args.path, args.subdir), args.role)
        else:
            result = agent.analyze_github(args.repo_url, args.role, args.subdir)
    except (AnalysisError, loader.SessionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Saved to data/{result['session_id']}/. Add candidate.md before starting the interview.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
