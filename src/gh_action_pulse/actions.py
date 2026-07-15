"""Defines the GithubAction class to handle action identification and metadata retrieval."""

import datetime
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import semver
from github.GithubException import GithubException

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from github import Github
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
    repo_canonical_name: str | None = None


class GithubActionNotFoundError(Exception):
    """Exception raised when a GitHub Action cannot be found."""


class GithubActionArchivedError(Exception):
    """Exception raised when a GitHub Action repository is archived."""

    def __init__(self, repo_name: str) -> None:
        """Initialize with the archived repository name."""
        self.repo_name = repo_name
        super().__init__(f"GitHub Action repository '{repo_name}' is archived.")


class GithubAction:
    """Represents a GitHub Action reference found in workflow or action files."""

    # local action like ./github/actions/myaction/action.yml are not considered here
    name: str
    actual: ActualState
    recommended: Recommendation
    repo: Repository
    min_age: int
    min_age_tag_date: datetime.datetime | None = None
    has_semver_tags: bool = False

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

    def get_fully_qualified(self, g: Github, min_age: int) -> GithubAction:
        """Fetch metadata from GitHub API to determine the type and dates of references."""
        logger.info(
            "Looking for actual and recommended metadata for action: '%s' with reference: '%s' and description: '%s'",
            self.name,
            self.actual.reference,
            self.actual.description,
        )
        # For actions like owner/repo/path@ref, the repo is owner/repo
        repo_name = "/".join(self.name.split("/")[:2])
        logger.debug("Get Repo access to %s (full action name: %s)", repo_name, self.name)
        self.repo = g.get_repo(repo_name)  # missing exception catch here
        self._set_repo_canonical_name(repo_name)
        if self.repo.archived:
            logger.error("GitHub Action repository '%s' is archived.", repo_name)
            raise GithubActionArchivedError(repo_name)
        self.min_age = min_age
        self._set_actual_reference_type_and_date()
        logger.info("actual reference type is %s at date %s", self.actual.reference_type, self.actual.date)
        self._set_actual_description_type()
        logger.info("actual description type is %s", self.actual.description_type)
        self._set_recommended_reference_and_date()
        logger.info(
            "recommendation is ref: %s at date: %s with description: %s",
            self.recommended.reference,
            self.recommended.date,
            self.recommended.description,
        )
        logger.info(
            "Completed actual and recommended metadata retrieval for action: '%s' with reference: '%s'"
            " and description: '%s'\n",
            self.name,
            self.actual.reference,
            self.actual.description,
        )
        return self

    def _set_repo_canonical_name(self, requested_repo: str) -> None:
        """Set repo_canonical_name when GitHub redirects the repository to a new owner or name."""
        canonical_repo = self.repo.full_name
        if canonical_repo.casefold() == requested_repo.casefold():
            self.recommended.repo_canonical_name = None
            return

        name_parts = self.name.split("/")
        subpath = "/".join(name_parts[2:])
        self.recommended.repo_canonical_name = f"{canonical_repo}/{subpath}" if subpath else canonical_repo
        logger.info("Action '%s' redirects to '%s'", self.name, self.recommended.repo_canonical_name)

    def _build_uses_content(self, action_name: str, reference: str, description: str | None) -> str:
        if description:
            return f"{action_name}@{reference} # {description}"
        return f"{action_name}@{reference}"

    def get_updated_uses_replacement(
        self,
        actual_reference: str,
        actual_description: str | None,
    ) -> str | None:
        """Return replacement content after 'uses: ', or None when no update is needed."""
        action_name = self.recommended.repo_canonical_name or self.name

        if self.recommended.reference and self.recommended.description:
            replacement = self._build_uses_content(
                action_name,
                self.recommended.reference,
                self.recommended.description,
            )
        elif self.recommended.repo_canonical_name is not None:
            replacement = self._build_uses_content(action_name, actual_reference, actual_description)
        else:
            return None

        current = self._build_uses_content(self.name, actual_reference, actual_description)
        if replacement == current:
            return None
        return replacement

    def _set_actual_reference_type_and_date(self) -> None:
        """Determines the type and date of the actual reference."""
        try:
            ref = self.repo.get_git_ref(f"heads/{self.actual.reference}")
            self.actual.reference_type = "branch"
            self.actual.date = self.repo.get_commit(sha=ref.object.sha).commit.committer.date
        except GithubException:
            pass
        else:
            return

        try:
            self.repo.get_git_ref(f"tags/{self.actual.reference}")
            commit = self.repo.get_commit(sha=self.actual.reference)
            self.actual.reference_type = "tag"
            self.actual.date = commit.commit.committer.date
        except GithubException:
            pass
        else:
            return

        try:
            commit = self.repo.get_commit(sha=self.actual.reference)
            self.actual.date = commit.commit.committer.date
            self.actual.reference_type = "sha"
        except GithubException:
            pass
        else:
            return

        self.actual.reference_type = "bullshit"
        self.actual.date = None

    def _set_actual_description_type(self) -> None:
        """Determines the type of the actual description."""
        if self.actual.description is None:
            self.actual.description_type = None
            return

        try:
            self.repo.get_git_ref(f"tags/{self.actual.description}")
            self.actual.description_type = "tag"
        except GithubException:
            pass
        else:
            return

        try:
            self.repo.get_git_ref(f"heads/{self.actual.description}")
            self.actual.description_type = "branch"
        except GithubException:
            pass
        else:
            return

        self.actual.description_type = "bullshit"

    def _set_recommended_reference_and_date(self) -> None:
        """Orchestrates the recommendation logic based on reference type and versioning."""
        valid_semver_tags = self._get_valid_semver_tags()

        match self.actual.reference_type:
            case "tag":
                self._set_recommended_reference_and_date_to_tag_if_exists(valid_semver_tags)
            case "branch":
                self._set_recommended_with_fallback(valid_semver_tags, self.actual.reference)
            case "sha":
                self._set_recommended_for_sha(valid_semver_tags)
            case "bullshit":
                logger.error("Cannot recommend update for invalid reference type.")
                raise SystemExit(1)
            case _:
                logger.error("Unknown reference type encountered, that should not happen.")
                raise SystemExit(1)

    def _get_valid_semver_tags(self) -> list:
        valid_semver_tags = []
        for tag in self.repo.get_tags():
            clean_name = tag.name.lstrip("v")
            if semver.Version.is_valid(clean_name):
                valid_semver_tags.append(tag)
        valid_semver_tags.sort(key=lambda tag: semver.Version.parse(tag.name.lstrip("v")), reverse=True)
        self.has_semver_tags = len(valid_semver_tags) != 0
        return valid_semver_tags

    def is_tag_fresh(self, max_age: int) -> bool:
        """Return True when the min-age eligible tag is not older than max_age."""
        if self.min_age_tag_date is not None:
            age = datetime.datetime.now(datetime.UTC) - self.min_age_tag_date.astimezone(datetime.UTC)
            return age.days <= max_age
        return bool(self.has_semver_tags)

    def _set_recommended_for_sha(self, valid_semver_tags: list) -> None:
        match self.actual.description_type:
            case "tag":
                self._set_recommended_reference_and_date_to_tag_if_exists(valid_semver_tags)
                return
            case "branch":
                if self.actual.description is not None:
                    self._set_recommended_with_fallback(valid_semver_tags, self.actual.description)
                return
            case _:
                if self._actual_sha_matches_tag():
                    self._set_recommended_reference_and_date_to_tag_if_exists(valid_semver_tags)
                    return

                self._set_recommended_to_latest_related_branch()

    def _actual_sha_matches_tag(self) -> bool:
        if self.actual.reference_type != "sha":
            return False

        try:
            resolved_sha = self.repo.get_commit(sha=self.actual.reference).commit.sha
        except GithubException:
            return False

        return any(tag.commit.commit.sha == resolved_sha for tag in self.repo.get_tags())

    def _set_recommended_to_branch(self, branch_name: str) -> None:
        """Sets the recommendation to the latest commit of a specific branch."""
        try:
            branch = self.repo.get_branch(branch_name)
            self.recommended.reference = branch.commit.sha
            self.recommended.date = branch.commit.commit.committer.date
            self.recommended.description = branch_name
        except GithubException:
            logger.exception("Failed to fetch branch '%s', that should not happen.", branch_name)

    def _set_recommended_to_latest_related_branch(self) -> None:
        """Recommend the newest branch tip among branches that contain the pinned SHA."""
        try:
            latest_branch = None
            latest_date = None
            for branch in self.repo.get_branches():
                try:
                    comparison = self.repo.compare(self.actual.reference, branch.commit.sha)
                except GithubException:
                    continue
                if comparison.status not in ("behind", "identical"):
                    continue
                branch_date = branch.commit.commit.committer.date
                if latest_date is None or branch_date > latest_date:
                    latest_date = branch_date
                    latest_branch = branch
            if latest_branch is not None:
                self._set_recommended_to_branch(latest_branch.name)
            else:
                logger.warning(
                    "No branch found containing commit '%s' for action '%s'.",
                    self.actual.reference,
                    self.name,
                )
        except GithubException:
            logger.exception(
                "Failed to find branches related to commit '%s' for action '%s'.",
                self.actual.reference,
                self.name,
            )

    def _set_recommended_with_fallback(self, valid_tags: list, branch_name: str) -> None:
        """Recommend a tag when it is newer than the branch tip, otherwise keep the branch."""
        self._set_recommended_reference_and_date_to_tag_if_exists(valid_tags)

        should_use_branch = self.recommended.date is None or (
            self.actual.date is not None and self.recommended.date <= self.actual.date
        )

        if should_use_branch:
            self._set_recommended_to_branch(branch_name)

    def _set_recommended_reference_and_date_to_tag_if_exists(self, valid_semver_tags: list) -> None:
        now = datetime.datetime.now(datetime.UTC)
        cutoff = now - datetime.timedelta(days=self.min_age)
        self.min_age_tag_date = None

        for tag in valid_semver_tags:
            tag_date = tag.commit.commit.committer.date
            if tag_date <= cutoff:
                self.recommended.reference = tag.commit.sha
                self.recommended.date = tag_date
                self.recommended.description = f"{tag.name}"
                self.min_age_tag_date = tag_date
                break
