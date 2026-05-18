"""Defines the GithubAction and UniqGithubActions classes to handle action identification and metadata retrieval."""

import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import semver
from github import Auth, Github
from github.GithubException import GithubException

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import datetime
    from pathlib import Path

    from github.Repository import Repository


@dataclass
class ActualState:
    """Metadata about the reference currently used in the project files."""

    reference: str
    description: str | None = None
    reference_type: Literal["sha", "tag", "branch", "bullshit"] | None = None
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
        logger.info(
            "Looking for actual and recommended metadata for action: '%s' with reference: '%s' and description: '%s'",
            self.name,
            self.actual.reference,
            self.actual.description,
        )
        auth = Auth.Token(os.environ["GITHUB_TOKEN"])
        g = Github(auth=auth)
        logger.debug("Get Repo access to %s", self.name)
        repo = g.get_repo(self.name)  # missing exception catch here
        self._set_actual_reference_type_and_date(repo)
        logger.info("actual reference type is %s at date %s", self.actual.reference_type, self.actual.date)
        self._set_actual_description_type(repo)
        logger.info("actual description type is %s", self.actual.description_type)
        self._set_recommended_reference_and_date(repo)
        logger.info(
            "recommendation is ref: %s at date: %s with description:%s",
            self.recommended.reference,
            self.recommended.date,
            self.recommended.description,
        )
        logger.info(
            "Completed actual and recommended metadata retrieval for action: '%s' with reference: '%s'"
            "and description: '%s'\n",
            self.name,
            self.actual.reference,
            self.actual.description,
        )
        return self

    def _set_actual_reference_type_and_date(self, repo: Repository) -> None:
        """Determines the type and date of the actual reference."""
        try:
            # actually get_commit look for both sha and tag
            commit = repo.get_commit(sha=self.actual.reference)
            self.actual.date = commit.commit.committer.date
            if commit.commit.sha == self.actual.reference:
                self.actual.reference_type = "sha"
            else:
                self.actual.reference_type = "tag"
        except GithubException:
            pass
        else:
            return

        try:
            ref = repo.get_git_ref(f"heads/{self.actual.reference}")
            self.actual.reference_type = "branch"
            self.actual.date = repo.get_commit(sha=ref.object.sha).commit.committer.date
        except GithubException:
            pass
        else:
            return

        self.actual.reference_type = "bullshit"
        self.actual.date = None

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

    def _set_recommended_reference_and_date(self, repo: Repository) -> None:
        """Orchestrates the recommendation logic based on reference type and versioning."""
        valid_semver_tags = self._get_valid_semver_tags(repo)

        match self.actual.reference_type:
            case "tag":
                self._set_recommended_reference_and_date_to_tag_if_exists(valid_semver_tags)
            case "branch":
                self._set_recommended_with_fallback(repo, valid_semver_tags, self.actual.reference)
            case "sha":
                self._set_recommended_for_sha(repo, valid_semver_tags)
            case "bullshit":
                logger.error("Cannot recommend update for invalid reference type.")
                raise SystemExit(1)
            case _:
                logger.error("Unknown reference type encountered, that should not happen.")
                raise SystemExit(1)

    def _get_valid_semver_tags(self, repo: Repository) -> list:
        valid_semver_tags = []
        for tag in repo.get_tags():
            clean_name = tag.name.lstrip("v")
            if semver.Version.is_valid(clean_name):
                valid_semver_tags.append(tag)
        valid_semver_tags.sort(key=lambda tag: semver.Version.parse(tag.name.lstrip("v")), reverse=True)
        return valid_semver_tags

    def _set_recommended_for_sha(self, repo: Repository, valid_semver_tags: list) -> None:
        match self.actual.description_type:
            case "tag":
                self._set_recommended_reference_and_date_to_tag_if_exists(valid_semver_tags)
                return
            case "branch":
                self._set_recommended_with_fallback(repo, valid_semver_tags, self.actual.reference)
                return
            case _:
                if self._actual_sha_matches_tag(repo):
                    self._set_recommended_reference_and_date_to_tag_if_exists(valid_semver_tags)

                if self.recommended.reference is None:
                    self._set_recommended_to_branch(repo, self.actual.reference)

    def _actual_sha_matches_tag(self, repo: Repository) -> bool:
        return any(tag.commit.commit.sha == self.actual.reference for tag in repo.get_tags())

    def _set_recommended_to_branch(self, repo: Repository, branch_name: str) -> None:
        """Sets the recommendation to the latest commit of a specific branch."""
        try:
            branch = repo.get_branch(branch_name)
            self.recommended.reference = branch.commit.sha
            self.recommended.date = branch.commit.commit.committer.date
            self.recommended.description = branch_name
        except GithubException:
            logger.exception("Failed to fetch branch '%s', that should not happen.", branch_name)

    def _set_recommended_with_fallback(self, repo: Repository, valid_tags: list, branch_name: str) -> None:
        """Tries to recommend the latest tag, falling back to a branch if the tag is older than the current pin."""
        self._set_recommended_reference_and_date_to_tag_if_exists(valid_tags)

        should_use_branch = self.recommended.date is None or (
            self.actual.date is not None and self.recommended.date < self.actual.date
        )

        if should_use_branch:
            self._set_recommended_to_branch(repo, branch_name)

    def _set_recommended_reference_and_date_to_tag_if_exists(self, valid_semver_tags: list) -> None:
        if valid_semver_tags:
            recommended_tag = valid_semver_tags[0]
            self.recommended.reference = recommended_tag.commit.sha
            self.recommended.date = recommended_tag.commit.commit.committer.date
            self.recommended.description = f"{recommended_tag.name}"


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

    def get_fully_qualified(self) -> set[GithubAction]:
        """Update all actions in the collection with metadata from the GitHub API."""
        return {action.get_fully_qualified() for action in self.get_actions()}
