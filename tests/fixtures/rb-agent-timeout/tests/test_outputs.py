from pathlib import Path


def test_output_written():
    assert Path("/app/out.txt").read_text().strip() == "ok"
