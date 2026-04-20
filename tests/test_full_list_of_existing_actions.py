"""Tests for the FullListOfExistingActions scanner to verify file discovery and pattern matching."""

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

from gh_action_pulse.full_list_of_existing_actions import FullListOfExistingActions

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


# tmp_path: fixture which will provide a temporary directory unique to each test function
def test_full_list_of_existing__scan_for_actions(tmp_path: Path) -> None:
    """Test that the scanner correctly identifies 'uses:' statements in YAML files."""
    # Setup: Create a dummy directory structure and files
    workflow_dir: Path = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)

    file1: Path = workflow_dir / "ci.yml"
    file1.write_text(
        "name: CI\n"
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n"
    )

    file2 = workflow_dir / "lint.yml"
    file2.write_text(
        "name: Lint\njobs:\n  ruff:\n    steps:\n      - name: lint\n        uses: charliermarsh/ruff-action@v1\n"
    )

    # Non-matching file (wrong extension)
    file3 = workflow_dir / "readme.txt"
    file3.write_text("uses: nothing")

    file4 = workflow_dir / "empty_file.yml"
    file4.write_text("")

    search_configs = [(workflow_dir, "*.yml")]

    scanner = FullListOfExistingActions(search_configs)
    results = scanner.get_results()

    assert len(results) == 2
    assert file1 in results
    assert file2 in results

    # Verify line numbers and stripped content for file1
    # Line 5:       - uses: actions/checkout@v4
    # Line 6:       - uses: actions/setup-python@v5
    assert len(results[file1]) == 2
    assert results[file1][0] == {5: "- uses: actions/checkout@v4"}
    assert results[file1][1] == {6: "- uses: actions/setup-python@v5"}

    # Verify file2
    assert results[file2][0] == {6: "uses: charliermarsh/ruff-action@v1"}


def test_full_list_of_existing__os_error(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test that OSError is caught and logged during scanning."""
    workflow_dir: Path = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "error.yml").touch()

    search_configs = [(workflow_dir, "*.yml")]

    # Patching open to simulate a disk/permission error
    with (
        patch("pathlib.Path.open", side_effect=OSError("Read error")),
        caplog.at_level(logging.ERROR),
    ):
        scanner = FullListOfExistingActions(search_configs)
        assert len(scanner.get_results()) == 0

    assert "Could not read file" in caplog.text
    assert "Read error" in caplog.text


def test_full_list_of_existing__unicode_decode_error(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test that UnicodeDecodeError is caught and logged during scanning."""
    workflow_dir: Path = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "binary.yml").write_bytes(b"\x80\x81\x82")  # Invalid UTF-8

    search_configs = [(workflow_dir, "*.yml")]

    with caplog.at_level(logging.ERROR):
        scanner = FullListOfExistingActions(search_configs)
        assert len(scanner.get_results()) == 0

    assert "Could not read file" in caplog.text


def test_full_list_of_existing__len(tmp_path: Path) -> None:
    """Test that __len__ returns the correct number of files found with actions."""
    workflow_dir: Path = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)

    # File with actions
    (workflow_dir / "has_actions.yml").write_text("- uses: actions/checkout@v4")
    # Another file with actions
    (workflow_dir / "also_has_actions.yml").write_text("- uses: actions/setup-python@v5")
    # File without actions
    (workflow_dir / "no_actions.yml").write_text("name: My Workflow")

    search_configs = [(workflow_dir, "*.yml")]
    scanner = FullListOfExistingActions(search_configs)

    assert len(scanner) == 2
