# Self-Learning Agent PoC

A Claude Agent SDK agent forgets everything the moment a session ends: the
same mistake gets repeated next time, and it re-learns a project's stack and
conventions from scratch on every run. This PoC gives an agent two
lightweight, purely local self-improvement capabilities, both implemented
entirely through the SDK's **hook system** — no fine-tuning, no vector DB,
no external services. Persistence is plain markdown/JSON, versioned with git.

1. **Reflective memory** (`reflective_memory.py`) — remembers tool failures
   across turns *and* across process restarts. A curated, ranked digest of
   the most frequent/recent failures is re-injected into every prompt.
2. **Skill generation** (`skill_generator.py`) — profiles the project
   directory (languages, marker files) once, writes a reusable skill file
   describing it, and regenerates that file when it detects the project's
   stack has drifted (e.g. files were added/removed that change the
   detected language set).

## How the patterns map to hook events

| Hook event           | Callback                    | Module               | Responsibility |
|-----------------------|------------------------------|-----------------------|----------------|
| `UserPromptSubmit`     | `inject_context_on_prompt`   | `hooks.py`             | Injects `<learned-memory>` + `<project-skills>` as `additionalContext` before every turn |
| `PostToolUseFailure`   | `capture_tool_failure`       | `hooks.py` → `reflective_memory.py` | Buffers a failed tool call's name/input/error for this turn |
| `Stop`                 | `on_stop_reflect`            | `hooks.py` → `reflective_memory.py` + `skill_generator.py` | Flushes buffered failures + turn summary to the daily log, re-ranks `CORE.md`, commits to git, and checks project drift |

`SessionStart`/`SessionEnd` are **not** exposed as native callback hooks in
the Python Claude Agent SDK (TypeScript-only). Project profiling is
therefore done as a manual pre-flight step in `agent_runner.py`, before the
`ClaudeSDKClient` is opened, rather than as a hook.

## Files

```
self_learning_poc/
├── reflective_memory.py   # ReflectiveMemory: daily logs, CORE.md ranking, git persistence
├── skill_generator.py     # SkillGenerator: project scan, PROFILE.json, drift detection
├── hooks.py                # SelfLearningHooks: the three async hook callbacks
├── agent_runner.py         # Entrypoint: builds ClaudeAgentOptions, runs queries
└── README.md               # This file
```

## Running the demo

```bash
pip install claude-agent-sdk
export ANTHROPIC_API_KEY=...   # or run under an already-authenticated `claude` CLI

# Default prompt: lists poc_project's files and summarizes the detected stack
python -m self_learning_poc.agent_runner

# Or pass your own prompt(s) as CLI args
python -m self_learning_poc.agent_runner "Use Bash to run 'ls ./does-not-exist'"
```

Environment variables (all optional):

| Variable            | Default            | Purpose |
|---------------------|---------------------|---------|
| `POC_PROJECT_DIR`   | `./poc_project`      | The project the agent works on / that gets profiled |
| `AGENT_MEMORY_DIR`  | `./.agent-memory`    | Where `ReflectiveMemory` stores its git repo |
| `AGENT_SKILLS_DIR`  | `./.agent-skills`    | Where `SkillGenerator` stores `PROFILE.json` + the skill file |

## What to inspect afterward

- **`.agent-memory/CORE.md`** — the top-N curated lessons, ranked by
  recency-weighted frequency of failure signatures. Regenerated every turn.
- **`.agent-memory/daily/YYYY-MM-DD.md`** — raw append-only log of every
  failure + turn summary for that day.
- **`.agent-memory/long-term-memory.md`** — full unfiltered history (audit trail).
- **`.agent-memory` git log** (`git -C .agent-memory log`) — one commit per
  turn, with the day's reflection content in the diff.
- **`.agent-skills/project-conventions.md`** — the generated skill file
  (YAML-ish frontmatter + a description of the detected stack).
- **`.agent-skills/PROFILE.json`** — the raw profile snapshot used for drift comparison.

Run the script twice in a row against the same directories to see `CORE.md`
and the git log grow — memory persists across process runs, not just within
a session. Delete a file that changes the detected language set (e.g. remove
all `.py` files and any Python marker files) and run again to see
`check_drift()` fire: it prints a `[system] Stop says: ...` notice and
rewrites `project-conventions.md`.

## Design notes

- **No network calls** for memory ranking or skill detection — only the
  actual Claude API calls made by `ClaudeSDKClient` hit the network.
  Everything else (failure recording, ranking, project scanning, git
  commits) is local file/subprocess logic.
- **Lazy directory creation** — `ReflectiveMemory` and `SkillGenerator`
  create their storage directories on first use, not at import time.
- **No empty commits** — `reflect_and_persist()` is a no-op if there were no
  buffered failures and no turn summary; the git commit is skipped entirely
  if `git status --porcelain` reports nothing changed.
- **Defensive `.get()` access** — hook callbacks read `tool_name`,
  `tool_input`, and `error` via `.get(..., default)`, so a malformed or
  partial `PostToolUseFailure` payload can't crash the turn.
- **Ranking is a naive local heuristic**, not a Claude call: failure
  signatures are `tool_name` + a lightly-normalized first line of the error
  (digits collapsed to `#`), scored by `0.85 ** age_in_days` summed per
  occurrence across all daily logs, and the top N are kept. See the stretch
  goals below for a higher-quality alternative.

## Deviations from the spec

- `SessionStart`/`SessionEnd` hooks don't exist in the Python SDK, so
  profiling happens as a manual pre-flight call in `agent_runner.py` (spec
  explicitly anticipates and allows this).
- The three hook functions are implemented as bound methods on a
  `SelfLearningHooks` class (`hooks.py`) rather than free functions, so they
  can close over shared `ReflectiveMemory`/`SkillGenerator` instances and a
  `last_turn_text` buffer without module-level globals. Signatures still
  match `(input_data, tool_use_id, context) -> dict` exactly.
- `on_stop_reflect`'s turn-summary text is accumulated *live* into
  `hooks_obj.last_turn_text` as `TextBlock`s stream in `agent_runner.py`,
  rather than being passed in after `receive_response()` finishes — the
  `Stop` hook can fire before the caller's iteration loop exits, so the text
  must already be available when it runs.

## Stretch goals (not implemented)

The base spec's stretch goals — replacing the frequency counter with a
Claude-based summarizer/deduplicator, an `instructionMode`
(`strict`/`advisory`/`off`) setting, and a DynamoDB/S3-backed store for a
Bedrock Agents port — were left for follow-up work; the base PoC's
acceptance criteria don't require them, and keeping the ranking/storage
layer pure-local keeps this PoC's zero-network-except-Claude-calls property
easy to verify.
