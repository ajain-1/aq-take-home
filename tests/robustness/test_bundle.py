import pytest
from conftest import make_zip, task_files, task_zip

from runner import bundle


def _extract(tmp_path, data: bytes, max_bytes: int = 10**7):
    zip_path = tmp_path / "upload.zip"
    zip_path.write_bytes(data)
    bundle.extract_zip(zip_path, tmp_path / "tasks", max_bytes)
    return bundle.load_task_spec(bundle.locate_task_dir(tmp_path / "tasks"))


def test_valid_bundle_is_accepted(tmp_path):
    spec = _extract(tmp_path, task_zip(agent_timeout=42, resource_class="large"))
    assert (spec.task_id, spec.max_agent_timeout_sec, spec.resource_class) == ("tiny-task", 42, "large")


def test_nested_task_dir_is_located(tmp_path):
    entries = {f"outer/tiny-task/{name}": body for name, body in task_files().items()}
    assert _extract(tmp_path, make_zip(entries)).task_id == "tiny-task"


@pytest.mark.parametrize(
    ("entries", "symlinks", "message"),
    [
        ({"../evil.txt": "x"}, None, "unsafe path"),
        ({"/abs/evil.txt": "x"}, None, "unsafe path"),
        ({"tiny-task/x": "x"}, {"tiny-task/link": "/etc/passwd"}, "symlinks are not allowed"),
        ({"tiny-task/Dockerfile": "FROM scratch"}, None, "does not contain a task.yaml"),
        ({name: body for name, body in task_files().items()}, None, "single top-level task directory"),
    ],
)
def test_unsafe_or_malformed_archives_are_rejected(tmp_path, entries, symlinks, message):
    with pytest.raises(bundle.InvalidTaskBundle, match=message):
        _extract(tmp_path, make_zip(entries, symlinks))


def test_traversal_never_writes_outside_destination(tmp_path):
    with pytest.raises(bundle.InvalidTaskBundle):
        _extract(tmp_path, make_zip({"tiny-task/ok": "x", "../../escaped.txt": "x"}))
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_expanded_size_cap(tmp_path):
    with pytest.raises(bundle.InvalidTaskBundle, match="expands beyond"):
        _extract(tmp_path, task_zip(), max_bytes=10)


def test_not_a_zip(tmp_path):
    with pytest.raises(bundle.InvalidTaskBundle, match="not a valid ZIP"):
        _extract(tmp_path, b"definitely not a zip")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda files: files.pop("run-tests.sh"), "missing required files: run-tests.sh"),
        (lambda files: files.update({"task.yaml": "instruction: [unclosed"}), "not valid YAML"),
        (lambda files: files.update({"task.yaml": "- a list"}), "must be a mapping"),
        (lambda files: files.update({"task.yaml": "difficulty: easy"}), "task.yaml is invalid"),
        (lambda files: files.update({"task.yaml": "instruction: x\nresource_class: huge"}), "unknown resource_class"),
    ],
)
def test_invalid_task_contents_are_rejected(tmp_path, mutate, message):
    files = task_files()
    mutate(files)
    with pytest.raises(bundle.InvalidTaskBundle, match=message):
        _extract(tmp_path, make_zip({f"tiny-task/{name}": body for name, body in files.items()}))


def test_task_id_must_be_docker_safe(tmp_path):
    with pytest.raises(bundle.InvalidTaskBundle, match="must be lowercase"):
        _extract(tmp_path, task_zip(task_id="Bad Task"))


def test_compose_file_pins_image_limits_and_labels(tmp_path):
    import yaml

    from runner.config import RESOURCE_CLASSES

    bundle.write_compose_file(tmp_path, "aq-task-abc:latest", "abc", RESOURCE_CLASSES["small"])
    compose = yaml.safe_load((tmp_path / "docker-compose.yaml").read_text())
    client = compose["services"]["client"]
    assert "build" not in client
    assert (client["image"], client["cpus"], client["mem_limit"]) == ("aq-task-abc:latest", 1.0, "1g")
    assert client["labels"]["aq.submission"] == "abc"
    assert all(volume.startswith("${AQ_HOST_PATH_PREFIX:-}") for volume in client["volumes"])
    assert compose["networks"]["default"]["labels"]["aq.submission"] == "abc"
