from pathlib import Path


def test_allocation_was_oom_killed():
    assert Path("/app/alloc_exit.txt").read_text().strip() == "137"
