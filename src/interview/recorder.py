"""Builds the Transcript from the text fragments Gradbot emits during a session."""

import datetime
import os
import pathlib
import re
import time

from src.shared.models import Transcript, Turn


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


class TranscriptRecorder:
    """Collects turns and keeps transcript.json on disk up to date.

    With a `directory`, the file is rewritten every time a new turn starts, so
    a crash loses at most the turn in progress.
    """

    def __init__(
        self, session_id: str, candidate_name: str, directory: pathlib.Path | None = None
    ):
        self.session_id = session_id
        self.candidate_name = candidate_name
        self.directory = directory
        self.started_at = _now()
        self._t0 = time.monotonic()
        self.turns: list[Turn] = []

    def add(
        self,
        speaker: str,
        text: str,
        question_id: str | None,
        followup: bool = False,
        second_chance: bool = False,
        hint: bool = False,
        t: float | None = None,
    ) -> None:
        """Append a fragment, merging it into the last turn when nothing changed."""
        text = " ".join(text.split())
        if not text:
            return
        tags = {
            "question_id": question_id,
            "followup": followup,
            "second_chance": second_chance,
            "hint": hint,
        }
        last = self.turns[-1] if self.turns else None
        if (
            last is not None
            and last.speaker == speaker
            and not last.interrupted
            and all(getattr(last, key) == value for key, value in tags.items())
        ):
            last.text = f"{last.text} {text}"
            return
        if t is None:
            t = time.monotonic() - self._t0
        self.turns.append(Turn(speaker=speaker, text=text, t=round(t, 1), **tags))
        self._write(None)

    def mark_interrupted(self, intended: str, heard: str) -> None:
        """The interviewer's latest turn was cut off after `heard`.

        The turn keeps the full wording it meant to say (`intended`) and
        records what was actually spoken. A turn of which nothing was spoken
        is not added: the transcript only holds what was said.
        """
        intended, heard = " ".join(intended.split()), " ".join(heard.split())
        if not heard:
            return
        # The candidate's interrupting words may already be recorded after it.
        index = len(self.turns)
        while index > 0 and self.turns[index - 1].speaker == "candidate":
            index -= 1
        turn = self.turns[index - 1] if index > 0 else None
        if turn is None or not _normalise(turn.text).endswith(_normalise(heard)):
            return  # cannot place it reliably; leave the transcript as heard
        # Keep anything said earlier in the same turn, replace the cut part.
        words_before = len(turn.text.split()) - len(heard.split())
        before = " ".join(turn.text.split()[: max(words_before, 0)])
        turn.text = f"{before} {intended}".strip()
        turn.heard = heard
        turn.interrupted = True
        self._write(None)

    def transcript(self, ended_reason: str | None = None) -> Transcript:
        return Transcript(
            session_id=self.session_id,
            candidate_name=self.candidate_name,
            started_at=self.started_at,
            ended_at=_now(),
            ended_reason=ended_reason,
            turns=self.turns,
        )

    def _write(self, ended_reason: str | None) -> pathlib.Path | None:
        if self.directory is None:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "transcript.json"
        # Write to a temporary file and swap it in, so a reader never sees half a file.
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            self.transcript(ended_reason).model_dump_json(indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)
        return path

    def save(self, ended_reason: str | None = None) -> pathlib.Path | None:
        """Final write, with the reason the interview ended."""
        return self._write(ended_reason)
