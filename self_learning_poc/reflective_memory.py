"""Pattern 1: Reflective memory.

Remembers mistakes and fixes across sessions, stored as git-versioned
markdown, ranked by frequency and recency, and re-injected into context
every turn. Pure file + git logic -- no network calls, no vector store.
"""

from __future__ import annotations

import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


class ReflectiveMemory:
    """Tracks tool failures across turns/sessions and curates a ranked digest."""

    def __init__(self, root: Path, top_n: int = 8):
        self.root = Path(root)
        self.daily_dir = self.root / "daily"
        self.core_path = self.root / "CORE.md"
        self.long_term_path = self.root / "long-term-memory.md"
        self.top_n = top_n
        self._buffer: list[dict[str, Any]] = []
        self._ensure_repo()

    # -- setup -----------------------------------------------------------

    def _ensure_repo(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            self._git("init", "-q")
        # Idempotent: make sure a headless commit identity always exists.
        self._git("config", "user.name", "reflective-memory-bot", check=False)
        self._git("config", "user.email", "reflective-memory@local", check=False)

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result

    # -- recording ---------------------------------------------------------

    def record_failure(self, tool_name: str, tool_input: dict | None, error: str) -> None:
        """Buffer a failure observed during the current turn."""
        self._buffer.append(
            {
                "tool_name": tool_name or "unknown",
                "tool_input": tool_input or {},
                "error": (error or "").strip(),
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )

    # -- persistence ---------------------------------------------------------

    def reflect_and_persist(self, turn_summary: str = "") -> None:
        """Flush buffered failures + a turn summary to disk, re-rank CORE.md, commit."""
        turn_summary = (turn_summary or "").strip()
        if not self._buffer and not turn_summary:
            return  # nothing happened this turn -- avoid empty commits

        today = date.today().isoformat()
        daily_path = self.daily_dir / f"{today}.md"
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

        block_lines: list[str] = [f"\n## {timestamp}\n"]
        if self._buffer:
            block_lines.append("### Failures\n")
            for failure in self._buffer:
                first_line = (
                    failure["error"].splitlines()[0][:200]
                    if failure["error"]
                    else "(no error message)"
                )
                block_lines.append(f"- `{failure['tool_name']}`: {first_line}\n")
            block_lines.append("\n")
        if turn_summary:
            block_lines.append("### Turn summary\n")
            block_lines.append(f"{turn_summary}\n")

        with daily_path.open("a", encoding="utf-8") as fh:
            fh.writelines(block_lines)

        with self.long_term_path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n# {today}\n")
            fh.writelines(block_lines)

        self._promote_to_core()

        n_failures = len(self._buffer)
        self._commit(f"reflect: {today} {timestamp} -- {n_failures} failure(s) recorded")
        self._buffer.clear()

    def _commit(self, message: str) -> None:
        status = self._git("status", "--porcelain").stdout.strip()
        if not status:
            return
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)

    # -- ranking ---------------------------------------------------------

    _SIG_RE = re.compile(r"^- `([^`]+)`: (.+)$")

    def _promote_to_core(self) -> None:
        """Recompute CORE.md: top-N failure signatures by recency-weighted frequency."""
        today = date.today()
        scores: dict[str, dict[str, Any]] = {}

        for path in sorted(self.daily_dir.glob("*.md")):
            try:
                file_date = date.fromisoformat(path.stem)
            except ValueError:
                continue
            age_days = max((today - file_date).days, 0)
            weight = 0.85**age_days

            for raw_line in path.read_text(encoding="utf-8").splitlines():
                match = self._SIG_RE.match(raw_line.strip())
                if not match:
                    continue
                tool_name, detail = match.group(1), match.group(2)
                normalized = re.sub(r"\d+", "#", detail).strip().lower()[:120]
                sig = f"{tool_name}::{normalized}"

                entry = scores.setdefault(
                    sig,
                    {
                        "score": 0.0,
                        "count": 0,
                        "tool": tool_name,
                        "detail": detail,
                        "last_seen": file_date,
                    },
                )
                entry["score"] += weight
                entry["count"] += 1
                if file_date >= entry["last_seen"]:
                    entry["last_seen"] = file_date
                    entry["detail"] = detail

        ranked = sorted(
            scores.values(), key=lambda e: (e["score"], e["count"]), reverse=True
        )[: self.top_n]
        self._write_core(ranked)

    def _write_core(self, ranked: list[dict[str, Any]]) -> None:
        generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
        lines = [
            "# Learned Memory (Core Lessons)\n\n",
            f"_Auto-generated by ReflectiveMemory -- top {self.top_n} lessons ranked by "
            "recency-weighted frequency._\n",
            f"_Last updated: {generated}_\n\n",
        ]
        if not ranked:
            lines.append("_No recorded failures yet._\n")
        else:
            for i, entry in enumerate(ranked, 1):
                lines.append(
                    f"{i}. **`{entry['tool']}`** (score: {entry['score']:.2f}, "
                    f"seen {entry['count']}x, last seen {entry['last_seen'].isoformat()}) "
                    f"-- {entry['detail']}\n"
                )
        self.core_path.write_text("".join(lines), encoding="utf-8")

    # -- context injection ---------------------------------------------------

    def get_context_block(self) -> str:
        if not self.core_path.exists():
            return ""
        content = self.core_path.read_text(encoding="utf-8").strip()
        if not content:
            return ""
        return f"<learned-memory>\n{content}\n</learned-memory>"
