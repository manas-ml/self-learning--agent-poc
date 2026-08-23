"""Tiny dummy app so the skill generator has something real to profile."""

import json
from pathlib import Path


def load_config(path: str) -> dict:
    return json.loads(Path(path).read_text())


def main() -> None:
    print("hello from poc_project")


if __name__ == "__main__":
    main()
