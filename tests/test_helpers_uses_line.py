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

from pathlib import Path

from gh_action_pulse.helpers.uses_line import (
    USES_LINE_PATTERN,
    parse_ignore_checks,
    parse_override_hints,
    parse_trailing_comments,
    parse_uses_line,
    rewrite_uses_line,
)


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

    def test_parse_override_hints_extracts_assignments(self) -> None:
        """Override hints accept comma-separated assignments for the three known keys."""
        empty = parse_override_hints([])
        assert not empty.values
        assert empty.unknown == frozenset()
        assert not empty.invalid

        assert not parse_override_hints(["v4.2.2"]).values

        single = parse_override_hints(["v4.2.2", "gh-action-pulse: override[max-age=200]"])
        assert single.values == {"max-age": 200}
        assert single.unknown == frozenset()
        assert not single.invalid

        several = parse_override_hints(["gh-action-pulse: override[max-age=180, min-age=3, nodejs-version=20]"])
        assert several.values == {"max-age": 180, "min-age": 3, "nodejs-version": 20}

        quoted = parse_override_hints(['gh-action-pulse: override["max-age"="200", "min-age"=0]'])
        assert quoted.values == {"max-age": 200, "min-age": 0}

        last_wins = parse_override_hints(
            [
                "gh-action-pulse: override[max-age=150]",
                "gh-action-pulse: override[max-age=200, min-age=14]",
            ]
        )
        assert last_wins.values == {"max-age": 200, "min-age": 14}

        whitespace = parse_override_hints(["gh-action-pulse:  override[ max-age = 200 , nodejs-version = 20 ]"])
        assert whitespace.values == {"max-age": 200, "nodejs-version": 20}

        trailing_comma = parse_override_hints(["gh-action-pulse: override[max-age=200,]"])
        assert trailing_comma.values == {"max-age": 200}

        mixed = parse_override_hints(["gh-action-pulse: override[max-age=200, max-days=180, min-age]"])
        assert mixed.values == {"max-age": 200}
        assert mixed.unknown == frozenset({"max-days", "min-age"})

        invalid = parse_override_hints(["gh-action-pulse: override[min-age=-1, max-age=200]"])
        assert invalid.values == {"max-age": 200}
        assert invalid.invalid == (("min-age", "min-age must be 0 or greater."),)

        negative_max = parse_override_hints(["gh-action-pulse: override[max-age=-5]"])
        assert not negative_max.values
        assert negative_max.invalid == (("max-age", "max-age must be 0 or greater."),)

        too_large = parse_override_hints(["gh-action-pulse: override[min-age=61]"])
        assert not too_large.values
        assert too_large.invalid == (("min-age", "min-age cannot exceed 60 days."),)

    def test_matches_uses_line_with_multiple_comments(self) -> None:
        """Named groups capture the prefix, action, reference, and raw trailing comments."""
        match = USES_LINE_PATTERN.search(
            "        uses: actions/checkout@abc123 # v4.2.2 # gh-action-pulse: ignore[max-days]"
        )
        assert match is not None
        assert match.group("prefix") == "        uses: "
        assert match.group("name") == "actions/checkout"
        assert match.group("reference") == "abc123"
        assert match.group("comments") == "v4.2.2 # gh-action-pulse: ignore[max-days]"

    def test_skips_local_action_without_reference(self) -> None:
        """Local `./` actions without `@` are not uses-line matches."""
        assert USES_LINE_PATTERN.search("uses: ./local-action") is None

    def test_skips_docker_ref_without_at(self) -> None:
        """Docker image refs without `@` are not uses-line matches."""
        assert USES_LINE_PATTERN.search("uses: docker://alpine:3.8") is None

    def test_parse_uses_line_returns_occurrence(self) -> None:
        """Scan-time parse fills UsesOccurrence so later stages do not re-parse the line."""
        workflow = Path("ci.yml")
        occurrence = parse_uses_line(
            "      - uses: actions/checkout@abc123 # v4.2.2 # extra\n",
            file=workflow,
            line_number=7,
        )
        assert occurrence is not None
        assert occurrence.file == workflow
        assert occurrence.line_number == 7
        assert occurrence.raw_line == "      - uses: actions/checkout@abc123 # v4.2.2 # extra"
        assert occurrence.name == "actions/checkout"
        assert occurrence.reference == "abc123"
        assert occurrence.description == "v4.2.2"
        assert occurrence.comments == ["v4.2.2", "extra"]

    def test_parse_uses_line_rejects_local_and_docker_refs(self) -> None:
        """Refs that fail the `@` pattern drop out at scan time."""
        workflow = Path("ci.yml")
        assert parse_uses_line("uses: ./local-action", file=workflow, line_number=1) is None
        assert parse_uses_line("uses: docker://alpine:3.8", file=workflow, line_number=2) is None

    def test_rewrite_uses_line_preserves_prefix_from_shared_pattern(self) -> None:
        """Rewrite keeps the indent/dash/`uses:` prefix captured by USES_LINE_PATTERN."""
        original = "      - uses: actions/checkout@v4\n"
        assert rewrite_uses_line(original, "actions/checkout@abc123 # v4.2.0") == (
            "      - uses: actions/checkout@abc123 # v4.2.0\n"
        )

    def test_rewrite_uses_line_leaves_non_matching_lines_unchanged(self) -> None:
        """Lines that are not `name@ref` uses-lines are not rewritten."""
        original = "name: Example\n"
        assert rewrite_uses_line(original, "actions/checkout@v4") == original
