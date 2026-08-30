"""Wires ReflectiveMemory and SkillGenerator into Claude Agent SDK hook callbacks.

Hook callback signature (per the SDK): (input_data, tool_use_id, context) -> dict
"""

from __future__ import annotations

from typing import Any

from .reflective_memory import ReflectiveMemory
from .skill_generator import SkillGenerator


class SelfLearningHooks:
    """Bundles the reflective-memory + skill-generation hook callbacks.

    `last_turn_text` is updated live by agent_runner.py as assistant text
    streams in, so it holds the most recent turn's text by the time the
    Stop hook fires.
    """

    def __init__(self, memory: ReflectiveMemory, skills: SkillGenerator):
        self.memory = memory
        self.skills = skills
        self.last_turn_text = ""

    async def inject_context_on_prompt(
        self, input_data: dict, tool_use_id: str | None, context: Any
    ) -> dict:
        """UserPromptSubmit hook: prepend learned memory + project skills to context."""
        blocks = [self.memory.get_context_block(), self.skills.get_context_block()]
        combined = "\n\n".join(block for block in blocks if block)
        if not combined:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": combined,
            }
        }

    async def capture_tool_failure(
        self, input_data: dict, tool_use_id: str | None, context: Any
    ) -> dict:
        """PostToolUseFailure hook: buffer the failure for this turn's reflection."""
        tool_name = input_data.get("tool_name", "unknown")
        tool_input = input_data.get("tool_input") or {}
        error = input_data.get("error", "") or ""
        self.memory.record_failure(tool_name, tool_input, error)
        return {}

    async def on_stop_reflect(
        self, input_data: dict, tool_use_id: str | None, context: Any
    ) -> dict:
        """Stop hook: persist this turn's reflection and check for project drift."""
        self.memory.reflect_and_persist(self.last_turn_text)
        self.last_turn_text = ""

        drift_detected = self.skills.check_drift()
        if drift_detected:
            return {
                "systemMessage": (
                    "Project skill file refreshed: detected stack drift in "
                    "project-conventions.md"
                )
            }
        return {}
