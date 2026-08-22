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

"""Helpers for parsing GitHub Actions ``uses:`` lines and trailing comments."""

import re
from dataclasses import dataclass, field

from gh_action_pulse.helpers.constants import ALLOWED_IGNORE_CHECKS, ALLOWED_OVERRIDE_KEYS, MAX_MIN_AGE

USES_LINE_PATTERN = re.compile(
    r"^\s*[-]?\s{0,1}uses:\s*"
    r"(?P<name>[^@\s]+)@"
    r"(?P<reference>[^\s#]+)"
    r"(?:\s+#\s+(?P<comments>.+))?"
)

IGNORE_HINT_PATTERN = re.compile(r"^gh-action-pulse:\s*ignore\[(?P<body>[^\]]*)\]$")
OVERRIDE_HINT_PATTERN = re.compile(r"^gh-action-pulse:\s*override\[(?P<body>[^\]]*)\]$")
OVERRIDE_ASSIGNMENT_PATTERN = re.compile(r"^['\"]?(?P<key>[A-Za-z0-9_-]+)['\"]?\s*=\s*['\"]?(?P<value>-?\d+)['\"]?$")


@dataclass(frozen=True)
class ParsedIgnoreHint:
    """Known and unknown check ids parsed from ``gh-action-pulse: ignore[...]`` comments."""

    checks: frozenset[str] = field(default_factory=frozenset)
    unknown: frozenset[str] = field(default_factory=frozenset)


def parse_trailing_comments(raw_comments: str | None) -> tuple[str | None, list[str]]:
    """Split trailing `#` comments; the first one is the action description."""
    comments = [part.strip() for part in raw_comments.split("#")] if raw_comments else []
    description = comments[0] if comments else None
    return description, comments


def parse_ignore_checks(comments: list[str]) -> ParsedIgnoreHint:
    """Extract ignore-hint check ids from trailing ``uses:`` comments.

    Accepts unquoted and quoted ids, for example ``ignore[max-age]`` or
    ``ignore["max-age", "min-age", "nodejs-version"]``. Unknown ids are returned separately
    so callers can warn without treating them as a skip.
    """
    requested: set[str] = set()
    for comment in comments:
        if match := IGNORE_HINT_PATTERN.fullmatch(comment.strip()):
            for raw in match.group("body").split(","):
                check = raw.strip().strip("\"'")
                if check:
                    requested.add(check)
    return ParsedIgnoreHint(
        checks=frozenset(requested & ALLOWED_IGNORE_CHECKS),
        unknown=frozenset(requested - ALLOWED_IGNORE_CHECKS),
    )


@dataclass(frozen=True)
class ParsedOverrideHint:
    """Known assignments and leftover keys from ``gh-action-pulse: override[...]`` comments."""

    values: dict[str, int] = field(default_factory=dict)
    unknown: frozenset[str] = field(default_factory=frozenset)
    invalid: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def _validate_override_value(key: str, value: int) -> None:
    """Raise ValueError when an override assignment is outside the CLI bounds."""
    if key == "min-age":
        if value < 0:
            msg = "min-age must be 0 or greater."
            raise ValueError(msg)
        if value > MAX_MIN_AGE:
            msg = f"min-age cannot exceed {MAX_MIN_AGE} days."
            raise ValueError(msg)
        return
    if value < 0:
        msg = f"{key} must be 0 or greater."
        raise ValueError(msg)


def parse_override_hints(comments: list[str]) -> ParsedOverrideHint:
    """Extract per-line threshold overrides from trailing ``uses:`` comments.

    Accepts comma-separated assignments such as ``override[max-age=200]`` or
    ``override[max-age=200, min-age=3, nodejs-version=20]``. Duplicate keys keep
    the last assignment. Unknown keys and out-of-range values are returned separately
    so callers can warn without applying them.
    """
    values: dict[str, int] = {}
    unknown: set[str] = set()
    invalid: list[tuple[str, str]] = []
    for comment in comments:
        if match := OVERRIDE_HINT_PATTERN.fullmatch(comment.strip()):
            for raw in match.group("body").split(","):
                item = raw.strip()
                if not item:
                    continue
                assignment = OVERRIDE_ASSIGNMENT_PATTERN.fullmatch(item)
                if assignment is None:
                    unknown.add(item.strip("\"'"))
                    continue
                key = assignment.group("key")
                if key not in ALLOWED_OVERRIDE_KEYS:
                    unknown.add(key)
                    continue
                value = int(assignment.group("value"))
                try:
                    _validate_override_value(key, value)
                except ValueError as exc:
                    invalid.append((key, str(exc)))
                    continue
                values[key] = value
    return ParsedOverrideHint(
        values=values,
        unknown=frozenset(unknown),
        invalid=tuple(invalid),
    )
