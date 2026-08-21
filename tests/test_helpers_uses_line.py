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

from gh_action_pulse.helpers.uses_line import USES_LINE_PATTERN, parse_ignore_checks, parse_trailing_comments


class TestUsesLineHelpers:
    """Tests for uses-line parsing helpers."""

    def test_parse_trailing_comments(self) -> None:
        """Trailing comments are split on `#`; the first fragment is the description."""
        assert parse_trailing_comments(None) == (None, [])
        assert parse_trailing_comments("v4.2.2") == ("v4.2.2", ["v4.2.2"])
        assert parse_trailing_comments("v4.2.2 # gh-action-pulse: ignore[max-age]") == (
            "v4.2.2",
            ["v4.2.2", "gh-action-pulse: ignore[max-age]"],
        )

    def test_parse_ignore_checks_extracts_known_and_unknown_ids(self) -> None:
        """Ignore hints accept quoted or unquoted ids and split unknown values out."""
        empty = parse_ignore_checks([])
        assert empty.checks == frozenset()
        assert empty.unknown == frozenset()

        assert parse_ignore_checks(["v4.2.2"]).checks == frozenset()

        unquoted = parse_ignore_checks(["v4.2.2", "gh-action-pulse: ignore[max-age]"])
        assert unquoted.checks == frozenset({"max-age"})
        assert unquoted.unknown == frozenset()

        quoted = parse_ignore_checks(['gh-action-pulse: ignore["max-age", "min-age", "nodejs-version"]'])
        assert quoted.checks == frozenset({"max-age", "min-age", "nodejs-version"})
        assert quoted.unknown == frozenset()

        mixed = parse_ignore_checks(["gh-action-pulse: ignore[max-age, max-days]"])
        assert mixed.checks == frozenset({"max-age"})
        assert mixed.unknown == frozenset({"max-days"})

        whitespace = parse_ignore_checks(["gh-action-pulse:  ignore[ max-age , nodejs-version ]"])
        assert whitespace.checks == frozenset({"max-age", "nodejs-version"})

        trailing_comma = parse_ignore_checks(["gh-action-pulse: ignore[max-age,]"])
        assert trailing_comma.checks == frozenset({"max-age"})
        assert trailing_comma.unknown == frozenset()

        split_comments = parse_ignore_checks(
            [
                "gh-action-pulse: ignore[max-age]",
                "gh-action-pulse: ignore[nodejs-version]",
            ]
        )
        assert split_comments.checks == frozenset({"max-age", "nodejs-version"})

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
