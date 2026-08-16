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

"""Tests for uses-line parsing helpers."""

from gh_action_pulse.helpers.uses_line import USES_LINE_PATTERN, parse_trailing_comments


class TestUsesLineHelpers:
    """Tests for uses-line parsing helpers."""

    def test_parse_trailing_comments(self) -> None:
        """Trailing comments are split on `#`; the first fragment is the description."""
        assert parse_trailing_comments(None) == (None, [])
        assert parse_trailing_comments("v4.2.2") == ("v4.2.2", ["v4.2.2"])
        assert parse_trailing_comments("v4.2.2 # gh-action-pulse: ignore[max-days]") == (
            "v4.2.2",
            ["v4.2.2", "gh-action-pulse: ignore[max-days]"],
        )

    def test_matches_uses_line_with_multiple_comments(self) -> None:
        """Named groups capture the action, reference, and raw trailing comments."""
        match = USES_LINE_PATTERN.search(
            "        uses: actions/checkout@abc123 # v4.2.2 # gh-action-pulse: ignore[max-days]"
        )
        assert match is not None
        assert match.group("name") == "actions/checkout"
        assert match.group("reference") == "abc123"
        assert match.group("comments") == "v4.2.2 # gh-action-pulse: ignore[max-days]"

    def test_skips_local_action_without_reference(self) -> None:
        """Local `./` actions without `@` are not uses-line matches."""
        assert USES_LINE_PATTERN.search("uses: ./local-action") is None
