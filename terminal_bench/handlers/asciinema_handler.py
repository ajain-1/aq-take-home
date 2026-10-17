import json
import os
from pathlib import Path


def read_events(lines: list[str]) -> list[list]:
    """Parse asciinema v2 event lines, skipping any that are partial or corrupt."""
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, list) and len(event) == 3:
            events.append(event)
    return events


class AsciinemaHandler:
    """Merges agent markers into an asciinema v2 recording as "m" events."""

    def __init__(self, markers: list[tuple[float, str]], recording_path: Path):
        self._markers = sorted(markers, key=lambda marker: marker[0])
        self._recording_path = recording_path

    def merge_markers(self) -> None:
        if not self._markers or not self._recording_path.exists():
            return

        header, *event_lines = self._recording_path.read_text().split("\n")
        events = read_events(event_lines)
        events.extend([timestamp, "m", text] for timestamp, text in self._markers)
        events.sort(key=lambda event: event[0])

        # asciinema may still be recording into this file; replacing it atomically sends
        # any late writes to the old inode instead of interleaving them with the merge.
        merged = self._recording_path.with_suffix(".merged")
        merged.write_text("\n".join([header, *(json.dumps(event) for event in events)]) + "\n")
        os.replace(merged, self._recording_path)
