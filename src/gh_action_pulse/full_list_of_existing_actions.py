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

"""Model representing an existing GitHub Action in a repository."""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class FullListOfExistingActions:
    """Model representing a list of existing GitHub Actions in a repository."""

    def __init__(self, search_configs: list[tuple[Path, str]]) -> None:
        """Initialize the model and scan for 'uses:' statements."""
        self._full_list: dict[Path, list[dict[int, str]]] = {}
        logger.debug("Scanning for 'uses:' statements in specified directories...")
        self._scan_for_actions(search_configs)
        logger.debug(
            "Scanning completed. Found %d files with actions that have 'uses:' statements.\n", len(self._full_list)
        )

    def _scan_for_actions(self, search_configs: list[tuple[Path, str]]) -> None:
        """Internal method to scan files based on provided configurations."""
        for directory, glob_pat in search_configs:
            regex_pattern: re.Pattern[str] = re.compile(pattern=r"^ *-{0,1} {0,1}uses:")
            for file_path in Path(directory).glob(pattern=glob_pat):
                logger.debug("Scanning file: %s", file_path)
                matches: list[dict[int, str]] = []
                try:
                    with file_path.open(encoding="utf-8") as f:
                        for line_num, line in enumerate(iterable=f, start=1):
                            if re.match(pattern=regex_pattern, string=line):
                                logger.debug(
                                    "Found action in file %s at line %d: %s", file_path, line_num, line.strip()
                                )
                                matches.append({line_num: line.strip()})
                except OSError, UnicodeDecodeError:
                    logger.exception("Could not read file %s", file_path)
                    continue
                if matches:
                    self._full_list[file_path] = matches

    def __len__(self) -> int:
        """Return the number of files containing actions."""
        return len(self._full_list)

    def get_results(self) -> dict[Path, list[dict[int, str]]]:
        """Return the dictionary of found actions."""
        return self._full_list
