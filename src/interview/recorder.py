"""Builds the Transcript from the text fragments Gradbot emits during a session."""

import datetime
import pathlib
import time

from src.shared.models import Transcript, Turn


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class TranscriptRecorder:
    def __init__(self, session_id: str, candidate_name: str):
        self.session_id = session_id
        self.candidate_name = candidate_name
        self.started_at = _now()
        self._t0 = time.monotonic()
        self.turns: list[Turn] = []

    def add(
        self,
        speaker: str,
        text: str,
        question_id: str | None,
        followup: bool = False,
        t: float | None = None,
    ) -> None:
        """Append a fragment, merging it into the last turn when nothing changed."""
        text = " ".join(text.split())
        if not text:
            return
        last = self.turns[-1] if self.turns else None
        if (
            last is not None
            and last.speaker == speaker
            and last.question_id == question_id
            and last.followup == followup
        ):
            last.text = f"{last.text} {text}"
            return
        if t is None:
            t = time.monotonic() - self._t0
        self.turns.append(
            Turn(
                speaker=speaker,
                question_id=question_id,
                followup=followup,
                text=text,
                t=round(t, 1),
            )
        )

    def transcript(self) -> Transcript:
        return Transcript(
            session_id=self.session_id,
            candidate_name=self.candidate_name,
            started_at=self.started_at,
            ended_at=_now(),
            turns=self.turns,
        )

    def save(self, directory: pathlib.Path) -> pathlib.Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "transcript.json"
        path.write_text(self.transcript().model_dump_json(indent=2), encoding="utf-8")
        return path
