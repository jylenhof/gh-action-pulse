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

"""Defines the UniqGithubActions collection for deduplicated action references."""

import logging
import re
import time
from typing import TYPE_CHECKING

from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TimeElapsedColumn

from gh_action_pulse.actions import GithubAction, GithubActionNotFoundError
from gh_action_pulse.helpers.console import console, phase_status

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from pathlib import Path

    from github import Github


class UniqGithubActions:
    """A collection of unique GitHub Actions harvested from project files."""

    def __init__(self) -> None:
        """Initialize an empty set of GitHub Actions."""
        self._actions: set[GithubAction] = set()

    def init_from_full_list(self, full_list: dict[Path, list[dict[int, str]]]) -> None:
        """Parse action references from a scanned list of file matches."""
        action_pattern = re.compile(r"^\s*[-]?\s{0,1}uses:\s*([^@\s]+)@([^\s#]+)(?:\s+#\s+(.+))?")

        logger.debug("Parsing action references from scanned files with de-duplication...")
        for matches in full_list.values():
            for match_dict in matches:
                for line in match_dict.values():
                    if match := action_pattern.search(line):
                        name: str = match.group(1)
                        reference: str = match.group(2)
                        actual_description: str | None = match.group(3) if match.group(3) is not None else None
                        logger.debug(
                            "Found action \n=>name: %s \n=>reference: %s \n=>actual description: %s",
                            name,
                            reference,
                            actual_description,
                        )
                        action = GithubAction(
                            name=name,
                            reference=reference,
                            actual_description=actual_description,
                        )
                        self.add(action)
        logger.debug("Finished parsing action references. Total unique actions found: %d\n", len(self._actions))

    def add(self, action: GithubAction) -> None:
        """Add a unique GithubAction to the collection."""
        self._actions.add(action)

    def get_actions(self) -> set[GithubAction]:
        """Return the set of collected GitHub Actions."""
        return self._actions

    def __getitem__(self, index: int) -> GithubAction:
        """Allow indexing into the set of actions."""
        return list(self._actions)[index]

    def get_item(self, name: str, reference: str, description: str | None) -> GithubAction:
        """Look for GithubAction which is named name with 'reference' reference and has 'description' description."""
        for i in self._actions:
            if i.name == name and i.actual.reference == reference and i.actual.description == description:
                return i
        raise GithubActionNotFoundError

    def get_fully_qualified(self, g: Github, min_age: int) -> set[GithubAction]:
        """Update all actions in the collection with metadata from the GitHub API."""
        actions = list(self.get_actions())
        if not actions:
            return set()

        qualified: set[GithubAction] = set()
        started = time.perf_counter()
        with Progress(
            SpinnerColumn(),
            "[progress.description]{task.description}",
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task_id = progress.add_task("Looking up upstream action metadata", total=len(actions))
            for action in actions:
                progress.update(task_id, description=f"Looking up upstream action metadata  {action.name}")
                qualified.add(action.get_fully_qualified(g, min_age))
                progress.advance(task_id)
        phase_status(
            "Looking up upstream action metadata…",
            "OK",
            elapsed=time.perf_counter() - started,
        )
        return qualified

    def get_stale_actions(self, max_age: int) -> list[GithubAction]:
        """Return actions whose min_age eligible tag is older than max_age."""
        if max_age <= 0:
            return []
        return [action for action in self.get_actions() if not action.is_tag_fresh(max_age)]
