"""Defines the UniqGithubActions collection for deduplicated action references."""

import logging
import re
from typing import TYPE_CHECKING

from gh_action_pulse.actions import GithubAction, GithubActionNotFoundError

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

        logger.info("Parsing action references from scanned files with de-duplication...")
        for matches in full_list.values():
            for match_dict in matches:
                for line in match_dict.values():
                    if match := action_pattern.search(line):
                        name: str = match.group(1)
                        reference: str = match.group(2)
                        actual_description: str | None = match.group(3) if match.group(3) is not None else None
                        logger.info(  # Maybe move this to debug level
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
        logger.info("Finished parsing action references. Total unique actions found: %d\n", len(self._actions))

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
        return {action.get_fully_qualified(g, min_age) for action in self.get_actions()}

    def get_stale_actions(self, max_age: int) -> list[GithubAction]:
        """Return actions whose min_age eligible tag is older than max_age."""
        if max_age <= 0:
            return []
        return [action for action in self.get_actions() if not action.is_tag_fresh(max_age)]
