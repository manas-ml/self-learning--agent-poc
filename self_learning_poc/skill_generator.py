"""Pattern 2: Skill generation.

Profiles the project being worked on, generates a reusable "skill" file
describing conventions/stack, and refreshes it when drift is detected.
Pure filesystem logic -- no network calls.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_IGNORED_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".agent-memory",
    ".agent-skills",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".idea",
    ".vscode",
}

_EXT_TO_LANG = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
}

_MARKER_TO_LANG = {
    "package.json": "JavaScript/Node.js",
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "go.mod": "Go",
    "Cargo.toml": "Rust",
    "Gemfile": "Ruby",
    "pom.xml": "Java",
    "build.gradle": "Java",
    "composer.json": "PHP",
}


class SkillGenerator:
    """Profiles a project directory and maintains a project-conventions skill file."""

    def __init__(self, project_dir: Path, skills_dir: Path):
        self.project_dir = Path(project_dir)
        self.skills_dir = Path(skills_dir)
        self.profile_path = self.skills_dir / "PROFILE.json"
        self.skill_path = self.skills_dir / "project-conventions.md"

    # -- scanning ---------------------------------------------------------

    def _scan(self) -> dict[str, Any]:
        languages: set[str] = set()
        markers: list[str] = []
        file_count = 0

        for dirpath, dirnames, filenames in os.walk(self.project_dir):
            dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS and not d.startswith(".")]
            for filename in filenames:
                file_count += 1
                ext = Path(filename).suffix
                if ext in _EXT_TO_LANG:
                    languages.add(_EXT_TO_LANG[ext])
                if filename in _MARKER_TO_LANG:
                    languages.add(_MARKER_TO_LANG[filename])
                    markers.append(filename)

        return {
            "languages": sorted(languages),
            "markers": sorted(set(markers)),
            "file_count": file_count,
            "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # -- profiling ---------------------------------------------------------

    def needs_profiling(self) -> bool:
        return not self.profile_path.exists()

    def profile_project(self) -> dict[str, Any]:
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        profile = self._scan()
        self.profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        self._write_skill_file(profile)
        return profile

    def check_drift(self) -> bool:
        """Re-scan and compare against the stored profile; refresh on drift."""
        if not self.profile_path.exists():
            self.profile_project()
            return True

        old_profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        new_profile = self._scan()

        if set(old_profile.get("languages", [])) != set(new_profile.get("languages", [])):
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            self.profile_path.write_text(json.dumps(new_profile, indent=2), encoding="utf-8")
            self._write_skill_file(new_profile)
            return True
        return False

    def _write_skill_file(self, profile: dict[str, Any]) -> None:
        langs = profile.get("languages") or ["Unknown"]
        frontmatter = (
            "---\n"
            "name: project-conventions\n"
            f"languages: [{', '.join(langs)}]\n"
            f"generated_at: {profile.get('scanned_at')}\n"
            "---\n\n"
        )
        body = (
            "# Project Conventions\n\n"
            "This project was auto-profiled by SkillGenerator.\n\n"
            f"- **Detected languages/stack:** {', '.join(langs)}\n"
            f"- **Marker files found:** {', '.join(profile.get('markers') or []) or 'none'}\n"
            f"- **File count scanned:** {profile.get('file_count')}\n"
            f"- **Last profiled:** {profile.get('scanned_at')}\n\n"
            "## Notes\n"
            "Match existing conventions (naming, formatting, dependency management) "
            "implied by the detected stack above when writing or editing code here.\n"
        )
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.skill_path.write_text(frontmatter + body, encoding="utf-8")

    # -- context injection ---------------------------------------------------

    def get_context_block(self) -> str:
        if not self.skill_path.exists():
            return ""
        content = self.skill_path.read_text(encoding="utf-8").strip()
        if not content:
            return ""
        return f"<project-skills>\n{content}\n</project-skills>"
