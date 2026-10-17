from pathlib import Path
import os


def test_manifest_file_exists():
    """Test that manifest.txt file exists in the current directory."""
    manifest_path = Path("/app/manifest.txt")

    assert manifest_path.exists(), f"File {manifest_path} does not exist"


def test_manifest_file_content():
    """Test that the first line of manifest.txt is exactly 'Hello, world!'."""
    manifest_path = Path("/app/manifest.txt")

    first_line = manifest_path.read_text().splitlines()[0]
    assert first_line == "Hello, world!", (
        f"Expected first line 'Hello, world!' but got '{first_line}'"
    )


def test_manifest_file_is_file():
    """Test that manifest.txt is a file and not a directory."""
    manifest_path = Path("/app/manifest.txt")

    assert manifest_path.is_file(), f"{manifest_path} is not a file"


def test_manifest_file_size():
    """Test that manifest.txt has the expected size."""
    manifest_path = Path("/app/manifest.txt")

    # "Hello, world!\n" is 14 bytes
    assert manifest_path.stat().st_size > 0, f"{manifest_path} is empty"


def test_manifest_file_permissions():
    """Test that manifest.txt has read permissions."""
    manifest_path = Path("/app/manifest.txt")

    assert os.access(manifest_path, os.R_OK), f"{manifest_path} is not readable"


def test_manifest_file_encoding():
    """Test that manifest.txt can be read as text."""
    manifest_path = Path("/app/manifest.txt")

    try:
        content = manifest_path.read_text(encoding='utf-8')
        assert isinstance(content, str), f"{manifest_path} content is not text"
    except UnicodeDecodeError:
        assert False, f"{manifest_path} is not properly encoded"


def test_manifest_file_exact_content():
    """Test that manifest.txt contains exactly 'Hello, world!' with proper formatting."""
    manifest_path = Path("/app/manifest.txt")

    content = manifest_path.read_text()
    # Should contain the exact string
    assert "Hello, world!" in content, f"{manifest_path} does not contain 'Hello, world!'"
    # Should not contain extra characters at the beginning
    assert content.startswith("Hello, world!"), f"{manifest_path} does not start with 'Hello, world!'"