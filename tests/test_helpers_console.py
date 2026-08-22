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

"""Tests for shared Rich console helpers."""

import pytest

from gh_action_pulse.helpers.console import (
    console,
    error,
    format_duration,
    format_status_with_ignored,
    phase,
    phase_status,
    success,
    warn,
)


class TestConsoleHelpers:
    """Unit tests for styled console helpers."""

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0.004, "4ms"),
            (0.999, "999ms"),
            (1, "1.0s"),
            (12.34, "12.3s"),
            (59.9, "59.9s"),
            (60, "1m 0s"),
            (75.4, "1m 15s"),
            (135, "2m 15s"),
        ],
    )
    def test_formats_duration(self, seconds: float, expected: str) -> None:
        """Durations are rendered as milliseconds, seconds, or minutes."""
        assert format_duration(seconds) == expected

    def test_phase_prints_cyan_bullet(self) -> None:
        """In-progress phase labels use a cyan bullet."""
        with console.capture() as capture:
            phase("Scanning…")

        assert "Scanning…" in capture.get()

    def test_phase_status_includes_elapsed_time(self) -> None:
        """Completion lines can include a compact elapsed duration."""
        with console.capture() as capture:
            phase_status("Scanning…", "OK", elapsed=0.004)

        output = capture.get()
        assert "Scanning…" in output
        assert "OK" in output
        assert "4ms" in output

    def test_phase_status_omits_timing_when_elapsed_is_missing(self) -> None:
        """Completion lines stay compact when no duration is provided."""
        with console.capture() as capture:
            phase_status("Scanning…", "OK")

        assert "(" not in capture.get()

    def test_format_status_with_ignored(self) -> None:
        """Ignored counts are appended only when at least one check was skipped."""
        assert format_status_with_ignored("OK", 0) == "OK"
        assert format_status_with_ignored("OK", 2) == "OK (2 ignored)"

    def test_success_warn_and_error_print_messages(self) -> None:
        """Success, warning, and error helpers emit their messages."""
        with console.capture() as capture:
            success("done")
            warn("careful")
            error("failed")

        output = capture.get()
        assert "done" in output
        assert "careful" in output
        assert "failed" in output
