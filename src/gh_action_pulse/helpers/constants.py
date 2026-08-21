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

"""Constants used across the ghaction_status project."""

from pathlib import Path

SEARCH_CONFIGS: list[tuple[Path, str]] = [
    (Path(".github/workflows"), "*.yml"),
    (Path(".github/workflows"), "*.yaml"),
    (Path(".github/actions"), "**/*.yml"),
    (Path(".github/actions"), "**/*.yaml"),
]

DEFAULT_MIN_AGE = 7
MAX_MIN_AGE = 60
DEFAULT_MAX_AGE = 150

# Minimum Node.js major version GitHub Actions (and their recursive dependencies)
# are expected to run on. Set to 0 to disable the check.
DEFAULT_MINIMUM_NODEJS_VERSION = 24

# Check ids accepted by `# gh-action-pulse: ignore[...]` trailing comments.
ALLOWED_IGNORE_CHECKS = frozenset({"max-age", "min-age", "nodejs-version"})

# Dedicated CLI exit codes for known failure conditions.
GITHUB_TOKEN_ERROR_EXIT_CODE = 2
NODEJS_VERSION_ERROR_EXIT_CODE = 3
ARCHIVED_ACTION_ERROR_EXIT_CODE = 4
STALE_TAG_ERROR_EXIT_CODE = 5
