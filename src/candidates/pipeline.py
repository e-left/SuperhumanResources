"""Prepare a candidate for their interview: profile, then questions written for them."""

import json
import logging

from src.analysis import agent
from src.analysis.repository import AnalysisError
from src.candidates import cv, github, profile, store

logger = logging.getLogger("interview")


def _stage(record, text: str) -> None:
    record.stage = text
    store.write(record)


def prepare(session_id: str) -> None:
    """Runs in the background after POST /api/candidates. Never raises."""
    record = store.read(session_id)
    folder = store.directory(session_id)
    try:
        _stage(record, "Reading the candidate's profile")
        github_data = cv_text = None
        if record.github_url:
            try:
                github_data = github.fetch_profile(record.github_url)
            except github.GithubError as exc:
                record.warnings.append(f"GitHub profile not used: {exc}")
        if record.cv_filename:
            try:
                cv_text = cv.extract_text(
                    record.cv_filename, (folder / record.cv_filename).read_bytes()
                )
            except (cv.CvError, OSError) as exc:
                record.warnings.append(f"CV not used: {exc}")
        (folder / "profile_sources.json").write_text(
            json.dumps({"github": github_data, "cv_text": cv_text}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if github_data is None and cv_text is None:
            # Nothing to read (not given, or not accessible): carry on without a
            # background, and say so, rather than refusing to prepare the interview.
            record.warnings.append(
                "No GitHub profile or CV could be used; the questions are based on the "
                "role and the codebase only."
            )
            markdown = profile.render_minimal(record)
        else:
            summary = profile.summarise(record, github_data, cv_text)
            markdown = profile.render(record, summary, github_data, cv_text is not None)
        (folder / "candidate.md").write_text(markdown, encoding="utf-8")

        _stage(record, "Reading the codebase and writing the questions")
        agent.analyze_github(
            record.repo_url,
            record.role,
            record.subdir,
            looking_for=record.looking_for,
            candidate_profile=markdown,
            session_id=session_id,
        )
        record.preparation = "ready"
        record.stage = ""
        store.write(record)
        logger.info("candidate %s (%s) is ready: /?session=%s", record.name, session_id, session_id)
    except (AnalysisError, profile.ProfileError) as exc:
        _fail(record, str(exc))
    except Exception as exc:  # anything else must still leave a readable status
        logger.exception("preparing candidate %s failed", session_id)
        _fail(record, f"unexpected error ({type(exc).__name__})")


def _fail(record, message: str) -> None:
    record.preparation = "failed"
    record.stage = ""
    record.error = message
    store.write(record)
    logger.error("candidate %s could not be prepared: %s", record.session_id, message)
