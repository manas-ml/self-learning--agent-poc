"""Entrypoint: wires ReflectiveMemory + SkillGenerator into a live SDK agent.

Usage:
    export ANTHROPIC_API_KEY=...
    python -m self_learning_poc.agent_runner "your prompt" ["another prompt"]

Environment variables:
    POC_PROJECT_DIR   -- project the agent works on (default: ./poc_project)
    AGENT_MEMORY_DIR  -- reflective memory store (default: ./.agent-memory)
    AGENT_SKILLS_DIR  -- generated skills store (default: ./.agent-skills)
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    SystemMessage,
    TextBlock,
)

from .hooks import SelfLearningHooks
from .reflective_memory import ReflectiveMemory
from .skill_generator import SkillGenerator

DEFAULT_PROMPT = "List the files in this project and summarize the tech stack you detect."


async def main() -> None:
    project_dir = Path(os.environ.get("POC_PROJECT_DIR", "./poc_project")).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    memory_dir = Path(os.environ.get("AGENT_MEMORY_DIR", "./.agent-memory")).resolve()
    skills_dir = Path(os.environ.get("AGENT_SKILLS_DIR", "./.agent-skills")).resolve()

    memory = ReflectiveMemory(memory_dir)
    skills = SkillGenerator(project_dir, skills_dir)

    # SessionStart isn't a native Python SDK hook, so profiling happens here,
    # as a manual pre-flight step before the client opens.
    if skills.needs_profiling():
        print(f"[agent_runner] Profiling project at {project_dir} ...")
        skills.profile_project()

    hooks_obj = SelfLearningHooks(memory, skills)

    options = ClaudeAgentOptions(
        cwd=str(project_dir),
        hooks={
            "UserPromptSubmit": [HookMatcher(hooks=[hooks_obj.inject_context_on_prompt])],
            "PostToolUseFailure": [HookMatcher(hooks=[hooks_obj.capture_tool_failure])],
            "Stop": [HookMatcher(hooks=[hooks_obj.on_stop_reflect])],
        },
    )

    prompts = sys.argv[1:] or [DEFAULT_PROMPT]

    async with ClaudeSDKClient(options=options) as client:
        for prompt in prompts:
            print(f"\n=== USER: {prompt} ===")
            await client.query(prompt)

            turn_text_parts: list[str] = []
            hooks_obj.last_turn_text = ""
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(block.text, end="", flush=True)
                            turn_text_parts.append(block.text)
                            # Kept live so the Stop hook (fired by the SDK as
                            # the turn wraps up) sees the latest text.
                            hooks_obj.last_turn_text = "".join(turn_text_parts).strip()[:2000]
                elif isinstance(message, SystemMessage) and message.subtype == "informational":
                    # Surfaces the Stop hook's systemMessage, e.g. drift-detected notices.
                    print(f"\n[system] {message.data.get('content', '')}")
            print()

    print("\n--- Inspect generated artifacts ---")
    print(f"Memory dir:  {memory_dir}")
    print(f"  CORE.md:   {memory.core_path}")
    print(f"  daily/:    {memory.daily_dir}")
    print(f"Skills dir:  {skills_dir}")
    print(f"  skill:     {skills.skill_path}")
    print(f"  profile:   {skills.profile_path}")


if __name__ == "__main__":
    asyncio.run(main())
