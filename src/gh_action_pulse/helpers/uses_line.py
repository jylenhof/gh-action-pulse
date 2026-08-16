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

USES_LINE_PATTERN = re.compile(
    r"^\s*[-]?\s{0,1}uses:\s*"
    r"(?P<name>[^@\s]+)@"
    r"(?P<reference>[^\s#]+)"
    r"(?:\s+#\s+(?P<comments>.+))?"
)


def parse_trailing_comments(raw_comments: str | None) -> tuple[str | None, list[str]]:
    """Split trailing `#` comments; the first one is the action description."""
    comments = [part.strip() for part in raw_comments.split("#")] if raw_comments else []
    description = comments[0] if comments else None
    return description, comments
