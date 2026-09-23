"""Versioned prompt files. The first line of each file is `version: <id>`; the rest is the template."""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).parent


def load_prompt(name: str) -> tuple[str, str]:
    """Return (version, body) for prompts/<name>.md."""
    text = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    first, _, body = text.partition("\n")
    if not first.startswith("version:"):
        raise ValueError(f"prompt {name} lacks a version line")
    return first.split(":", 1)[1].strip(), body.strip()
