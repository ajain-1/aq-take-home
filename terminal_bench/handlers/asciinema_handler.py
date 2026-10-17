import json
from pathlib import Path


class AsciinemaHandler:
    """Merges agent markers into an asciinema v2 recording as "m" events."""

    def __init__(self, markers: list[tuple[float, str]], recording_path: Path):
        self._markers = sorted(markers, key=lambda marker: marker[0])
        self._recording_path = recording_path

    def merge_markers(self) -> None:
        if not self._markers or not self._recording_path.exists():
            return

        header, *event_lines = self._recording_path.read_text().splitlines()
        events = [json.loads(line) for line in event_lines if line.strip()]
        events.extend([timestamp, "m", text] for timestamp, text in self._markers)
        events.sort(key=lambda event: event[0])

        lines = [header, *(json.dumps(event) for event in events)]
        self._recording_path.write_text("\n".join(lines) + "\n")
