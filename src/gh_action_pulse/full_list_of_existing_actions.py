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
        logger.info("Scanning for 'uses:' statements in specified directories...")
        self._scan_for_actions(search_configs)
        logger.info(
            "Scanning completed. Found %d files with actions that have 'uses:' statements.\n", len(self._full_list)
        )

    def _scan_for_actions(self, search_configs: list[tuple[Path, str]]) -> None:
        """Internal method to scan files based on provided configurations."""
        for directory, glob_pat in search_configs:
            regex_pattern: re.Pattern[str] = re.compile(pattern=r"^ *-{0,1} {0,1}uses:")
            for file_path in Path(directory).glob(pattern=glob_pat):
                logger.info("Scanning file: %s", file_path)
                matches: list[dict[int, str]] = []
                try:
                    with file_path.open(encoding="utf-8") as f:
                        for line_num, line in enumerate(iterable=f, start=1):
                            if re.match(pattern=regex_pattern, string=line):
                                logger.info("Found action in file %s at line %d: %s", file_path, line_num, line.strip())
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
