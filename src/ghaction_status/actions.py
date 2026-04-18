"""Defines the GithubAction and UniqGithubActions classes to handle action identification and metadata retrieval."""

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from github import Auth, Github
from github.GithubException import GithubException
from packaging.version import InvalidVersion, Version

if TYPE_CHECKING:
    import datetime
    from pathlib import Path

    from github.Repository import Repository


@dataclass
class ActualState:
    """Metadata about the reference currently used in the project files."""

    reference: str
    description: str | None = None
    type: Literal["sha", "tag", "branch", "bullshit"] | None = None
    description_type: Literal["tag", "branch", "bullshit"] | None = None
    date: datetime.datetime | None = None


@dataclass
class Recommendation:
    """Metadata about the recommended reference suggested by the API."""

    reference: str | None = None
    date: datetime.datetime | None = None
    description: str | None = None


class GithubAction:
    """Represents a GitHub Action reference found in workflow or action files."""

    # local action like ./github/actions/myaction/action.yml are not considered here
    name: str
    actual: ActualState
    recommended: Recommendation

    def __init__(
        self,
        name: str,
        reference: str,
        actual_description: str | None = None,
    ) -> None:
        """Initialize a GithubAction with its name, reference, and optional description."""
        self.name = name
        self.actual = ActualState(reference=reference, description=actual_description)
        self.recommended = Recommendation()

    def __hash__(self) -> int:
        """Return a hash based on the action name, reference, and description."""
        return hash((self.name, self.actual.reference, self.actual.description))

    def __eq__(self, other: object) -> bool:
        """Compare two GithubAction instances for equality."""
        if isinstance(other, GithubAction):
            return (
                self.name,
                self.actual,
            ) == (other.name, other.actual)
        return False

    def get_fully_qualified(self) -> GithubAction:
        """Fetch metadata from GitHub API to determine the type and dates of references."""
        auth = Auth.Token(os.environ["GITHUB_TOKEN"])
        g = Github(auth=auth)
        repo = g.get_repo(self.name)
        self._set_actual_reference_type_and_date(repo)
        self._set_actual_description_type(repo)
        self._set_recommended_reference_and_date(repo)
        return self

    def _set_recommended_reference_and_date(self, repo: Repository) -> None:
        """Determines the recommended reference and date."""
        valid_semver_tags = []
        for tag in repo.get_tags():
            try:
                Version(tag.name)
                valid_semver_tags.append(tag)
            except InvalidVersion:
                # Ignore tags that do not conform to semantic versioning
                pass

        valid_semver_tags.sort(key=lambda tag: Version(tag.name), reverse=True)
        if self.actual.type == "tag" or self.actual.description_type == "tag":
            self.recommended.reference = valid_semver_tags[0].commit.sha
            self.recommended.date = repo.get_commit(
                sha=valid_semver_tags[0].commit.sha,
            ).commit.committer.date
            self.recommended.description = f"{valid_semver_tags[0].name}"
        elif self.actual.type == "branch" or self.actual.description_type == "branch":
            self.recommended.reference = (
                repo.get_branch(
                    self.recommended.reference,
                ).commit.sha
                if self.recommended.reference is not None
                else None
            )
            self.recommended.date = (
                repo.get_commit(
                    sha=self.recommended.reference,
                ).commit.committer.date
                if self.recommended.reference is not None
                else None
            )
            self.recommended.description = f"{self.actual.description}"
        else:
            # Look for the actual reference in the sorted tags first, then branches
            for tag in valid_semver_tags:
                if tag.commit.sha == self.actual.reference:
                    self.recommended.reference = tag.commit.sha
                    self.recommended.date = repo.get_commit(
                        sha=tag.commit.sha,
                    ).commit.committer.date
                    self.recommended.description = f"{tag.name}"
                    return
            # If not found in tags, look in last commit of branches, perhaps we should do better
            for branch in repo.get_branches():
                if branch.commit.sha == self.actual.reference:
                    self.recommended.reference = branch.commit.sha
                    self.recommended.date = repo.get_commit(
                        sha=branch.commit.sha,
                    ).commit.committer.date
                    self.recommended.description = f"{branch.name}"
                    return

    def _set_actual_description_type(self, repo: Repository) -> None:
        """Determines the type of the actual description."""
        if self.actual.description is None:
            self.actual.description_type = None
            return

        try:
            repo.get_git_ref(f"tags/{self.actual.description}")
            self.actual.description_type = "tag"
        except GithubException:
            pass
        else:
            return

        try:
            repo.get_git_ref(f"heads/{self.actual.description}")
            self.actual.description_type = "branch"
        except GithubException:
            pass
        else:
            return

        self.actual.description_type = "bullshit"

    def _set_actual_reference_type_and_date(self, repo: Repository) -> None:
        """Determines the type and date of the actual reference."""
        try:
            # actually get_commit look for both sha and tag
            commit = repo.get_commit(sha=self.actual.reference)
            self.actual.date = commit.commit.committer.date
            if commit.commit.sha == self.actual.reference:
                self.actual.type = "sha"
            else:
                self.actual.type = "tag"
        except GithubException:
            pass
        else:
            return

        try:
            ref = repo.get_git_ref(f"tags/{self.actual.reference}")
            self.actual.type = "tag"
            self.actual.date = repo.get_commit(sha=ref.object.sha).commit.committer.date
        except GithubException:
            pass
        else:
            return

        try:
            ref = repo.get_git_ref(f"heads/{self.actual.reference}")
            self.actual.type = "branch"
            self.actual.date = repo.get_commit(sha=ref.object.sha).commit.committer.date
        except GithubException:
            pass
        else:
            return

        self.actual.type = "bullshit"
        self.actual.date = None


class UniqGithubActions:
    """A collection of unique GitHub Actions harvested from project files."""

    def __init__(self) -> None:
        """Initialize an empty set of GitHub Actions."""
        self._actions: set[GithubAction] = set()

    def init_from_full_list(self, full_list: dict[Path, list[dict[int, str]]]) -> None:
        """Parse action references from a scanned list of file matches."""
        action_pattern = re.compile(r"^\s*[-]?\s{0,1}uses:\s*([^@\s]+)@([^\s#]+)(?:\s+#\s+(.+))?")

        for matches in full_list.values():
            for match_dict in matches:
                for line in match_dict.values():
                    if match := action_pattern.search(line):
                        name: str = match.group(1)
                        reference: str = match.group(2)
                        actual_description: str | None = match.group(3) if match.group(3) is not None else None
                        action = GithubAction(
                            name=name,
                            reference=reference,
                            actual_description=actual_description,
                        )
                        self.add(action)

    def add(self, action: GithubAction) -> None:
        """Add a unique GithubAction to the collection."""
        self._actions.add(action)

    def get_actions(self) -> set[GithubAction]:
        """Return the set of collected GitHub Actions."""
        return self._actions

    def get_fully_qualified(self) -> set[GithubAction]:
        """Update all actions in the collection with metadata from the GitHub API."""
        return {action.get_fully_qualified() for action in self.get_actions()}
