# Copyright (C) 2026  Jean-Yves LENHOF
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Tests for the FullListOfExistingActions scanner to verify file discovery and pattern matching."""

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

from gh_action_pulse.full_list_of_existing_actions import FullListOfExistingActions
from gh_action_pulse.helpers.uses_line import UsesOccurrence

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

    # Verify line numbers and parsed uses-line fields for file1
    # Line 5:       - uses: actions/checkout@v4
    # Line 6:       - uses: actions/setup-python@v5
    assert results[file1] == [
        UsesOccurrence(
            file=file1,
            line_number=5,
            raw_line="      - uses: actions/checkout@v4",
            name="actions/checkout",
            reference="v4",
            description=None,
            comments=[],
        ),
        UsesOccurrence(
            file=file1,
            line_number=6,
            raw_line="      - uses: actions/setup-python@v5",
            name="actions/setup-python",
            reference="v5",
            description=None,
            comments=[],
        ),
    ]

    # Verify file2
    assert results[file2] == [
        UsesOccurrence(
            file=file2,
            line_number=6,
            raw_line="        uses: charliermarsh/ruff-action@v1",
            name="charliermarsh/ruff-action",
            reference="v1",
            description=None,
            comments=[],
        )
    ]


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


def test_full_list_skips_local_and_docker_refs_without_at(tmp_path: Path) -> None:
    """Docker and local `./` refs that fail the `@` pattern drop out at scan time."""
    workflow_dir: Path = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    file1: Path = workflow_dir / "ci.yml"
    file1.write_text(
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: ./local-action\n"
        "      - uses: docker://alpine:3.8\n"
        "      - uses: ./.github/actions/foo\n"
    )

    scanner = FullListOfExistingActions([(workflow_dir, "*.yml")])
    results = scanner.get_results()

    assert results[file1] == [
        UsesOccurrence(
            file=file1,
            line_number=4,
            raw_line="      - uses: actions/checkout@v4",
            name="actions/checkout",
            reference="v4",
            description=None,
            comments=[],
        )
    ]


def test_full_list_parses_trailing_comments_at_scan_time(tmp_path: Path) -> None:
    """Trailing comments are split during scan so later stages can use them as-is."""
    workflow_dir: Path = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    file1: Path = workflow_dir / "ci.yml"
    file1.write_text("- uses: actions/checkout@abc123 # v4.2.2 # extra note\n")

    scanner = FullListOfExistingActions([(workflow_dir, "*.yml")])
    results = scanner.get_results()

    assert results[file1][0].description == "v4.2.2"
    assert results[file1][0].comments == ["v4.2.2", "extra note"]
