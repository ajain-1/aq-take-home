"""Reads an agent's turn-by-turn trajectory from a terminal-bench trial directory."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EPISODE_DIR_PATTERN = re.compile(r"^episode-(\d+)$")


@dataclass(frozen=True)
class Episode:
    """One LLM turn: the prompt the agent saw and the response it gave. The terminal
    output that followed its commands is the next episode's prompt."""

    index: int
    prompt_path: Path
    response_path: Path
    prompt: str
    response: dict[str, Any]
    raw_response: str

    @property
    def commands(self) -> list[dict[str, Any]]:
        return self.response.get("commands", []) if self.response else []

    @property
    def is_task_complete(self) -> bool:
        return bool(self.response.get("is_task_complete"))


def read_recording(path: Path) -> str:
    """An asciinema v2 recording with any corrupt event lines dropped, so a player can
    load it even if the file was damaged while being written."""
    header, *lines = path.read_text(errors="replace").split("\n")
    kept = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, list) and len(event) == 3:
            kept.append(line)
    return "\n".join([header, *kept]) + "\n"


def _read(path: Path) -> str:
    return path.read_text(errors="replace") if path.is_file() else ""


def load_episodes(trial_dir: Path) -> list[Episode]:
    agent_logs = trial_dir / "agent-logs"
    if not agent_logs.is_dir():
        return []
    indexed = sorted(
        (int(match.group(1)), path)
        for path in agent_logs.iterdir()
        if path.is_dir() and (match := EPISODE_DIR_PATTERN.match(path.name))
    )

    episodes = []
    for index, path in indexed:
        raw_response = _read(path / "response.json")
        try:
            response = json.loads(raw_response) if raw_response else {}
        except json.JSONDecodeError:
            response = {}
        episodes.append(
            Episode(
                index=index,
                prompt_path=path / "prompt.txt",
                response_path=path / "response.json",
                prompt=_read(path / "prompt.txt"),
                response=response if isinstance(response, dict) else {},
                raw_response=raw_response,
            )
        )
    return episodes
