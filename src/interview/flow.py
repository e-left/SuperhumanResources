"""Interview flow state, driven by the interviewer's tool calls.

The LLM calls a tool before each step. The state lives here, so the order of
questions and the one-follow-up limit are enforced by code, not by the prompt.
Every method returns the JSON-able tool result sent back to the LLM.
"""

import json

import gradbot

from src.shared.models import Question

_NO_ARGS = json.dumps({"type": "object", "properties": {}})

TOOLS = [
    gradbot.ToolDef(
        "start_question",
        "Call this right before asking each main interview question. "
        "Returns the exact wording to say.",
        json.dumps(
            {
                "type": "object",
                "properties": {
                    "question_id": {
                        "type": "string",
                        "description": "Id of the question you are about to ask, e.g. q1",
                    }
                },
                "required": ["question_id"],
            }
        ),
    ),
    gradbot.ToolDef(
        "ask_followup",
        "Call this right before asking the prepared follow-up of the current "
        "question. Returns the exact wording to say.",
        _NO_ARGS,
    ),
    gradbot.ToolDef(
        "end_interview",
        "Call this after the candidate has answered the last question, right "
        "before your closing words.",
        _NO_ARGS,
    ),
]


class InterviewFlow:
    def __init__(self, questions: list[Question]):
        self.questions = questions
        self._index = -1
        self.in_followup = False
        self._followup_used = False
        self.ended = False

    @property
    def current(self) -> Question | None:
        return self.questions[self._index] if self._index >= 0 else None

    @property
    def question_id(self) -> str | None:
        """Tag for transcript turns: None before the first question and after the end."""
        if self.ended or self.current is None:
            return None
        return self.current.id

    def start_question(self, question_id: str) -> dict:
        if self.ended:
            return {"error": "The interview has already ended."}
        if self._index + 1 >= len(self.questions):
            return {"error": "All questions have been asked. Call end_interview."}
        expected = self.questions[self._index + 1]
        if question_id != expected.id:
            return {"error": f"Questions go in order. The next one is {expected.id}."}
        self._index += 1
        self.in_followup = False
        self._followup_used = False
        return {"ok": True, "say": expected.question}

    def ask_followup(self) -> dict:
        question = self.current
        if self.ended or question is None:
            return {"error": "No question is in progress."}
        if question.followup is None:
            return {"error": f"{question.id} has no follow-up. Move on."}
        if self._followup_used:
            return {"error": f"The follow-up for {question.id} was already asked. Move on."}
        self._followup_used = True
        self.in_followup = True
        return {"ok": True, "say": question.followup.question}

    def end_interview(self) -> dict:
        if self.ended:
            return {"ok": True}
        remaining = [q.id for q in self.questions[self._index + 1 :]]
        if remaining:
            return {"error": f"Not finished. Still to ask: {', '.join(remaining)}."}
        self.ended = True
        self.in_followup = False
        return {"ok": True, "say": "Thank the candidate and say goodbye in one sentence."}

    def handle(self, name: str, args: dict) -> dict:
        if name == "start_question":
            return self.start_question(str(args.get("question_id", "")))
        if name == "ask_followup":
            return self.ask_followup()
        if name == "end_interview":
            return self.end_interview()
        return {"error": f"Unknown tool: {name}"}
