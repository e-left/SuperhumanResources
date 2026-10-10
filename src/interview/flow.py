"""Interview flow state, driven by the interviewer's tool calls.

The LLM asks for each step through a tool. The state lives here, so the order
of questions, the one-follow-up limit, the one-second-chance limit and the
time limit are enforced by code, not by the prompt. Every method returns the
JSON-able tool result sent back to the LLM.
"""

import json

import gradbot

from src.shared.models import Question

_NO_ARGS = json.dumps({"type": "object", "properties": {}})

TOOLS = [
    gradbot.ToolDef(
        "start_question",
        "Ask the next main interview question. The question is spoken for you, word for word.",
        json.dumps(
            {
                "type": "object",
                "properties": {
                    "question_id": {
                        "type": "string",
                        "description": "Id of the question to ask, e.g. q1",
                    }
                },
                "required": ["question_id"],
            }
        ),
    ),
    gradbot.ToolDef(
        "ask_followup",
        "Ask the prepared follow-up of the current question. It is spoken for you, word for word.",
        _NO_ARGS,
    ),
    gradbot.ToolDef(
        "second_chance",
        "Give the candidate one more try at what was just asked, because their answer was "
        "clearly wrong, off target, or they were stuck. Allowed once per question or follow-up.",
        json.dumps(
            {
                "type": "object",
                "properties": {
                    "say": {
                        "type": "string",
                        "description": "The one or two sentences to speak: invite another try, "
                        "optionally with a small hint. Never part of the reference answer.",
                    },
                    "hint_given": {
                        "type": "boolean",
                        "description": "True if `say` contains a hint.",
                    },
                },
                "required": ["say", "hint_given"],
            }
        ),
    ),
    gradbot.ToolDef(
        "end_interview",
        "Close the interview: after the last question has been answered, or when told the "
        "time is up.",
        _NO_ARGS,
    ),
]

_TIME_UP = "The time limit has been reached. Do not ask anything else: call end_interview."


class InterviewFlow:
    def __init__(self, questions: list[Question]):
        self.questions = questions
        self._index = -1
        # Set by the session once the candidate has said anything: the first
        # question may not start before the hello has been exchanged.
        self.candidate_spoke = False
        # Set by the session when the wrap-up time is reached.
        self.time_up = False
        self.in_followup = False
        self._followup_used = False
        # Second chance state for the thing currently asked (question or follow-up).
        self.in_second_chance = False
        self.hint = False
        self._second_chance_used = False
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

    @property
    def remaining(self) -> list[str]:
        return [q.id for q in self.questions[self._index + 1 :]]

    @property
    def next_question(self) -> Question | None:
        return self.questions[self._index + 1] if self.remaining else None

    @property
    def followup_available(self) -> bool:
        question = self.current
        return bool(question and question.followup and not self._followup_used)

    @property
    def ended_reason(self) -> str:
        return "time_limit" if self.time_up and self.remaining else "completed"

    def _new_item(self) -> None:
        self.in_second_chance = False
        self.hint = False
        self._second_chance_used = False

    def start_question(self, question_id: str) -> dict:
        if self.ended:
            return {"error": "The interview has already ended."}
        if self.time_up:
            return {"error": _TIME_UP}
        if not self.remaining:
            return {"error": "All questions have been asked. Call end_interview."}
        if not self.candidate_spoke:
            return {
                "error": "Say hello and introduce yourself first, then wait for the "
                "candidate to reply. Do not ask a question yet."
            }
        expected = self.questions[self._index + 1]
        if question_id != expected.id:
            return {"error": f"Questions go in order. The next one is {expected.id}."}
        self._index += 1
        self.in_followup = False
        self._followup_used = False
        self._new_item()
        return {"ok": True, "say": expected.question}

    def ask_followup(self) -> dict:
        question = self.current
        if self.ended or question is None:
            return {"error": "No question is in progress."}
        if self.time_up:
            return {"error": _TIME_UP}
        if question.followup is None:
            return {"error": f"{question.id} has no follow-up. Move on."}
        if self._followup_used:
            return {"error": f"The follow-up for {question.id} was already asked. Move on."}
        self._followup_used = True
        self.in_followup = True
        self._new_item()
        return {"ok": True, "say": question.followup.question}

    def second_chance(self, say: str, hint_given: bool) -> dict:
        if self.ended or self.current is None:
            return {"error": "No question is in progress."}
        if self.time_up:
            return {"error": _TIME_UP}
        if self._second_chance_used:
            return {
                "error": "A second chance was already given here and there is never a third. "
                "Accept the answer and move on."
            }
        say = " ".join(str(say or "").split())
        if not say:
            return {"error": "`say` is empty. Provide the words to speak."}
        self._second_chance_used = True
        self.in_second_chance = True
        self.hint = bool(hint_given)
        return {"ok": True, "say": say}

    def end_interview(self) -> dict:
        if self.ended:
            return {"ok": True}
        if self.remaining and not self.time_up:
            return {"error": f"Not finished. Still to ask: {', '.join(self.remaining)}."}
        instruction = "Thank the candidate and say goodbye in one sentence."
        if self.time_up and self.remaining:
            instruction = (
                "Tell the candidate kindly that the time is up, thank them and say goodbye, "
                "in two sentences at most."
            )
        self.ended = True
        self.in_followup = False
        self.in_second_chance = False
        self.hint = False
        return {"ok": True, "say": instruction}

    def handle(self, name: str, args: dict) -> dict:
        if name == "start_question":
            return self.start_question(str(args.get("question_id", "")))
        if name == "ask_followup":
            return self.ask_followup()
        if name == "second_chance":
            return self.second_chance(args.get("say", ""), bool(args.get("hint_given")))
        if name == "end_interview":
            return self.end_interview()
        return {"error": f"Unknown tool: {name}"}
