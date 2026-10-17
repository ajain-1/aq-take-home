import importlib.util
import json
from pathlib import Path

from runner.trajectory import read_recording

HEADER = json.dumps({"version": 2, "width": 80, "height": 24})
HANDLER_PATH = Path(__file__).resolve().parents[1] / "terminal_bench" / "handlers" / "asciinema_handler.py"


def load_handler_module():
    # Loaded by path: importing the terminal_bench package pulls in the whole harness.
    spec = importlib.util.spec_from_file_location("asciinema_handler", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_read_recording_drops_corrupt_event_lines(tmp_path: Path):
    cast = tmp_path / "agent.cast"
    cast.write_text(f'{HEADER}\n[0.1, "o", "ok"]\n[0.2, "o", "trunc\n"ated"]\n[0.3, "m", "turn"]\n')
    header, *events = read_recording(cast).strip().split("\n")
    assert json.loads(header)["version"] == 2
    assert [json.loads(e)[2] for e in events] == ["ok", "turn"]


def test_merge_markers_survives_a_recorder_still_writing(tmp_path: Path):
    cast = tmp_path / "agent.cast"
    cast.write_text(f'{HEADER}\n[0.1, "o", "a"]\n[2.0, "o", "b"]\n[2.5, "o", "partial')
    recorder = cast.open("a")  # asciinema keeps its file open while the harness merges

    load_handler_module().AsciinemaHandler([(1.0, "turn 1")], cast).merge_markers()
    recorder.write('"]\n[3.0, "o", "late"]\n')
    recorder.close()

    header, *lines = cast.read_text().strip().split("\n")
    events = [json.loads(line) for line in lines]
    assert [e[2] for e in events] == ["a", "turn 1", "b"]
    assert events[1][1] == "m"
