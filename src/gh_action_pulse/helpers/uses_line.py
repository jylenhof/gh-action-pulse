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

from gh_action_pulse.helpers.constants import ALLOWED_IGNORE_CHECKS

USES_LINE_PATTERN = re.compile(
    r"^\s*[-]?\s{0,1}uses:\s*"
    r"(?P<name>[^@\s]+)@"
    r"(?P<reference>[^\s#]+)"
    r"(?:\s+#\s+(?P<comments>.+))?"
)

IGNORE_HINT_PATTERN = re.compile(r"^gh-action-pulse:\s*ignore\[(?P<body>[^\]]*)\]$")


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
