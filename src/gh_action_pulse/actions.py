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

"""Defines the GithubAction class to handle action identification and metadata retrieval."""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import semver
from github.GithubException import GithubException

from gh_action_pulse.helpers.uses_line import (
    ParsedIgnoreHint,
    ParsedOverrideHint,
    parse_ignore_checks,
    parse_override_hints,
)

logger = logging.getLogger(__name__)

VersionScheme = Literal["semver", "loose"]

# Non-SemVer version tags accepted as a fallback when a repository has no SemVer tag at all,
# e.g. "v1", "v0.6", "1.2" or "v2-beta" (missing minor/patch components default to 0).
_LOOSE_VERSION_PATTERN = re.compile(
    r"^[vV]?(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def parse_version_tag(name: str, scheme: VersionScheme) -> semver.Version | None:
    """Parse a tag name with the given versioning scheme, or return None when it does not match."""
    if scheme == "semver":
        clean_name = name.lstrip("v")
        return semver.Version.parse(clean_name) if semver.Version.is_valid(clean_name) else None
    if (match := _LOOSE_VERSION_PATTERN.match(name)) is None:
        return None
    return semver.Version(
        major=int(match.group("major")),
        minor=int(match.group("minor") or 0),
        patch=int(match.group("patch") or 0),
        prerelease=match.group("prerelease"),
    )


if TYPE_CHECKING:
    from collections.abc import Sequence

    from github import Github
    from github.Repository import Repository
    from github.Tag import Tag


@dataclass
class ActualState:  # pylint: disable=too-many-instance-attributes
    """Metadata about the reference currently used in the project files."""

    reference: str
    description: str | None = None
    comments: list[str] = field(default_factory=list)
    reference_type: Literal["sha", "tag", "branch", "bullshit"] | None = None
    description_type: Literal["tag", "branch", "bullshit"] | None = None
    date: datetime.datetime | None = None
    ignore_hint: ParsedIgnoreHint = field(default_factory=ParsedIgnoreHint)
    override_hint: ParsedOverrideHint = field(default_factory=ParsedOverrideHint)


@dataclass
class Recommendation:
    """Metadata about the recommended reference suggested by the API."""

    reference: str | None = None
    date: datetime.datetime | None = None
    description: str | None = None
    comments: list[str] = field(default_factory=list)
    repo_canonical_name: str | None = None


class GithubActionNotFoundError(Exception):
    """Exception raised when a GitHub Action cannot be found."""


class GithubActionArchivedError(Exception):
    """Exception raised when a GitHub Action repository is archived."""

    def __init__(self, repo_name: str) -> None:
        """Initialize with the archived repository name."""
        self.repo_name = repo_name
        super().__init__(f"GitHub Action repository '{repo_name}' is archived.")


class GithubActionReferenceNotFoundError(Exception):
    """Exception raised when a uses-line reference is neither a branch, a tag nor a commit upstream."""

    def __init__(self, name: str, reference: str) -> None:
        """Initialize with the action name and the reference that could not be found."""
        self.name = name
        self.reference = reference
        super().__init__(
            f"Reference '{reference}' of action '{name}' does not exist upstream"
            " (it is neither a branch, a tag nor a commit SHA)."
        )


class GithubAction:  # pylint: disable=too-many-instance-attributes
    """Represents a GitHub Action reference found in workflow or action files."""

    # local action like ./github/actions/myaction/action.yml are not considered here
    name: str
    actual: ActualState
    recommended: Recommendation
    repo: Repository
    min_age: int
    min_age_tag_date: datetime.datetime | None = None
    has_version_tags: bool = False
    version_scheme: VersionScheme | None = None

    def __init__(
        self,
        name: str,
        reference: str,
        actual_description: str | None = None,
        comments: list[str] | None = None,
    ) -> None:
        """Initialize a GithubAction with its name, reference, and optional description."""
        self.name = name
        comment_list = list(comments) if comments is not None else []
        self.actual = ActualState(
            reference=reference,
            description=actual_description,
            comments=comment_list,
            ignore_hint=parse_ignore_checks(comment_list),
            override_hint=parse_override_hints(comment_list),
        )
        self.recommended = Recommendation()
        self.warnings: list[str] = []
        self._all_tags: list[Tag] | None = None
        self._related_branch_searched = False

    def ignores(self, check: str) -> bool:
        """Return True when this uses-line asked to skip the named check."""
        return check in self.actual.ignore_hint.checks

    def override(self, check: str) -> int | None:
        """Return the per-line override for a check id, or None when unset."""
        return self.actual.override_hint.values.get(check)

    def effective_max_age(self, default: int) -> int:
        """Return the max-age threshold for this line after ignore/override hints."""
        if self.ignores("max-age"):
            return 0
        if (value := self.override("max-age")) is not None:
            return value
        return default

    def effective_nodejs_version(self, default: int) -> int:
        """Return the Node.js minimum for this line after ignore/override hints."""
        if self.ignores("nodejs-version"):
            return 0
        if (value := self.override("nodejs-version")) is not None:
            return value
        return default

    def __hash__(self) -> int:
        """Return a hash based on the action name, reference, description, and comments."""
        return hash((self.name, self.actual.reference, self.actual.description, tuple(self.actual.comments)))

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
        logger.debug(
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
        if self.ignores("min-age"):
            logger.debug("Skipping min-age wait for action '%s' due to ignore hint.", self.name)
        elif (override := self.override("min-age")) is not None:
            logger.debug("Using min-age override of %d days for action '%s'.", override, self.name)
        self._set_actual_reference_type_and_date()
        logger.debug("actual reference type is %s at date %s", self.actual.reference_type, self.actual.date)
        self._set_actual_description_type()
        logger.debug("actual description type is %s", self.actual.description_type)
        self._set_recommended_reference_and_date()
        logger.debug(
            "recommendation is ref: %s at date: %s with description: %s",
            self.recommended.reference,
            self.recommended.date,
            self.recommended.description,
        )
        logger.debug(
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
        logger.debug("Action '%s' redirects to '%s'", self.name, self.recommended.repo_canonical_name)

    def _build_uses_content(self, action_name: str, reference: str, comments: Sequence[str] | None) -> str:
        uses_content = f"{action_name}@{reference}"
        if comments:
            for comment in comments:
                uses_content += f" # {comment}"
        return uses_content

    def get_updated_uses_replacement(
        self,
        actual_reference: str,
        actual_comments: Sequence[str] | None,
    ) -> str | None:
        """Return replacement content after 'uses: ', or None when no update is needed."""
        action_name = self.recommended.repo_canonical_name or self.name

        if self.recommended.reference and self.recommended.description:
            replacement = self._build_uses_content(
                action_name,
                self.recommended.reference,
                self.recommended.comments,
            )
        elif self.recommended.repo_canonical_name is not None:
            replacement = self._build_uses_content(action_name, actual_reference, actual_comments)
        else:
            return None

        current = self._build_uses_content(self.name, actual_reference, actual_comments)
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
        version_tags = self._get_version_tags()
        self.recommended.comments = list(self.actual.comments)
        match self.actual.reference_type:
            case "tag":
                self._set_recommended_reference_and_date_to_tag_if_exists(version_tags)
            case "branch":
                self._set_recommended_with_fallback(version_tags, self.actual.reference)
            case "sha":
                self._set_recommended_for_sha(version_tags)
            case "bullshit":
                raise GithubActionReferenceNotFoundError(self.name, self.actual.reference)
            case _:
                logger.error("Unknown reference type encountered, that should not happen.")
                raise SystemExit(1)
        if self.recommended.reference is None or self.recommended.description is None:
            self._set_recommended_degraded()
        if self.recommended.description is None:
            # Degraded mode could not find anything better: keep the uses-line unchanged.
            self.recommended.reference = None
            self.recommended.comments = list(self.actual.comments)
            return
        if self.actual.description_type in ["tag", "branch"] and self.recommended.comments:
            self.recommended.comments[0] = self.recommended.description
        else:
            self.recommended.comments.insert(0, self.recommended.description)

    def _warn(self, message: str) -> None:
        """Log a warning and keep it for the end-of-run degraded recommendations report."""
        logger.warning("%s", message)
        self.warnings.append(message)

    def _get_all_tags(self) -> list[Tag]:
        """Return every tag of the repository, fetched once per action."""
        if self._all_tags is None:
            self._all_tags = list(self.repo.get_tags())
        return self._all_tags

    def _get_version_tags(self) -> list[Tag]:
        """Return version tags sorted newest first, preferring SemVer and falling back to loose versions."""
        all_tags = self._get_all_tags()
        scheme: VersionScheme
        for scheme in ("semver", "loose"):
            parsed = [
                (version, tag) for tag in all_tags if (version := parse_version_tag(tag.name, scheme)) is not None
            ]
            if not parsed:
                continue
            parsed.sort(key=lambda item: item[0], reverse=True)
            self.version_scheme = scheme
            self.has_version_tags = True
            if scheme == "loose":
                self._warn(
                    f"No SemVer tag found for action '{self.name}'; falling back to non-SemVer version tags"
                    f" (newest: '{parsed[0][1].name}')."
                )
            return [tag for _, tag in parsed]
        self.version_scheme = None
        self.has_version_tags = False
        return []

    def _parse_version(self, name: str) -> semver.Version | None:
        """Parse a tag name with the versioning scheme selected for this repository (SemVer by default)."""
        return parse_version_tag(name, self.version_scheme or "semver")

    def is_tag_fresh(self, max_age: int) -> bool:
        """Return True when the min-age eligible tag is not older than max_age."""
        if self.min_age_tag_date is not None:
            age = datetime.datetime.now(datetime.UTC) - self.min_age_tag_date.astimezone(datetime.UTC)
            return age.days <= max_age
        return bool(self.has_version_tags)

    def _set_recommended_for_sha(self, version_tags: Sequence[Tag]) -> None:
        match self.actual.description_type:
            case "tag":
                self._set_recommended_reference_and_date_to_tag_if_exists(version_tags)
                return
            case "branch":
                if self.actual.description is not None:
                    self._set_recommended_with_fallback(version_tags, self.actual.description)
                return
            case _:
                if self._actual_sha_matches_tag():
                    self._set_recommended_reference_and_date_to_tag_if_exists(version_tags)
                    return

                self._set_recommended_to_latest_related_branch()

    def _tags_matching_actual_sha(self) -> list[Tag]:
        """Return the tags pointing at the pinned SHA (short SHAs are resolved first)."""
        if self.actual.reference_type != "sha":
            return []

        try:
            resolved_sha = self.repo.get_commit(sha=self.actual.reference).commit.sha
        except GithubException:
            return []

        return [tag for tag in self._get_all_tags() if tag.commit.sha == resolved_sha]

    def _actual_sha_matches_tag(self) -> bool:
        return bool(self._tags_matching_actual_sha())

    def _get_pinned_tag_name(self) -> str | None:
        """Return the tag currently pinned by the uses-line (reference, comment, or tag at the pinned SHA)."""
        if self.actual.reference_type == "tag":
            return self.actual.reference
        if self.actual.description_type == "tag" and self.actual.description:
            return self.actual.description
        matching_tags = self._tags_matching_actual_sha()
        if not matching_tags:
            return None
        # Prefer the most precise version-like tag (e.g. v1.2.3 over a floating v1), then a stable name order.
        versioned = [
            (version, tag) for tag in matching_tags if (version := parse_version_tag(tag.name, "loose")) is not None
        ]
        if versioned:
            return max(versioned, key=lambda item: (item[0], len(item[1].name)))[1].name
        return min(tag.name for tag in matching_tags)

    def _set_recommended_to_tag_name(self, tag_name: str) -> bool:
        """Recommend the commit SHA a tag points to; return False when the tag cannot be resolved."""
        try:
            commit = self.repo.get_commit(sha=tag_name)
        except GithubException:
            logger.debug("Failed to resolve tag '%s' for action '%s'.", tag_name, self.name)
            return False
        self.recommended.reference = commit.sha
        self.recommended.date = commit.commit.committer.date
        self.recommended.description = tag_name
        return True

    def _degraded_reason(self) -> str:
        if not self.has_version_tags:
            return "no version tag found"
        return "no eligible version tag (min-age not met or no newer tag than the pinned one)"

    def _set_recommended_degraded(self) -> None:
        """Best-effort recommendation when the rules cannot be applied, always preferring a SHA pin."""
        reason = self._degraded_reason()
        self.recommended.reference = None
        self.recommended.date = None
        self.recommended.description = None

        if (pinned_tag := self._get_pinned_tag_name()) is not None and self._set_recommended_to_tag_name(pinned_tag):
            self._warn(f"Action '{self.name}': {reason}; pinning current tag '{pinned_tag}' to its commit SHA.")
            return

        branch_name = None
        if self.actual.reference_type == "branch":
            branch_name = self.actual.reference
        elif self.actual.description_type == "branch":
            branch_name = self.actual.description
        if branch_name is not None:
            self._set_recommended_to_branch(branch_name)
            if self.recommended.reference is not None:
                self._warn(f"Action '{self.name}': {reason}; pinning branch '{branch_name}' tip to its commit SHA.")
                return

        if self.actual.reference_type == "sha" and not self._related_branch_searched:
            self._set_recommended_to_latest_related_branch()
            if self.recommended.reference is not None:
                self._warn(
                    f"Action '{self.name}': {reason}; pinning the newest branch containing"
                    f" '{self.actual.reference}' ('{self.recommended.description}')."
                )
                return

        self._warn(
            f"Action '{self.name}@{self.actual.reference}': {reason} and no tag or branch to follow;"
            " keeping the current reference unchanged."
        )

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
        self._related_branch_searched = True
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

    def _set_recommended_with_fallback(self, valid_tags: Sequence[Tag], branch_name: str) -> None:
        """Recommend a tag when it is at least as new as the branch tip, otherwise keep the branch."""
        self._set_recommended_reference_and_date_to_tag_if_exists(valid_tags)

        should_use_branch = self.recommended.date is None or (
            self.actual.date is not None and self.recommended.date < self.actual.date
        )

        if should_use_branch:
            self._set_recommended_to_branch(branch_name)

    def _get_actual_version(self) -> semver.Version | None:
        """Return the highest version from the pinned tag reference or comment."""
        version_strings: list[str] = []
        if self.actual.reference_type == "tag":
            version_strings.append(self.actual.reference)
        if self.actual.description_type == "tag" and self.actual.description:
            version_strings.append(self.actual.description)

        versions = [version for value in version_strings if (version := self._parse_version(value)) is not None]
        return max(versions) if versions else None

    def _parse_tag_version(self, tag: Tag) -> semver.Version:
        version = self._parse_version(tag.name)
        if version is None:  # Only called on tags returned by _get_version_tags
            msg = f"Tag '{tag.name}' is not a version tag."
            raise ValueError(msg)
        return version

    @staticmethod
    def _tag_meets_min_age(tag: Tag, cutoff: datetime.datetime) -> bool:
        return tag.commit.commit.committer.date <= cutoff

    def _find_tag_for_version(self, valid_semver_tags: Sequence[Tag], version: semver.Version) -> Tag | None:
        for tag in valid_semver_tags:
            if self._parse_tag_version(tag) == version:
                return tag
        return None

    def _effective_min_age(self) -> int:
        """Return the min-age wait for this line after ignore/override hints."""
        if self.ignores("min-age"):
            return 0
        if (value := self.override("min-age")) is not None:
            return value
        return self.min_age

    def _apply_tag_recommendation(self, tag: Tag, cutoff: datetime.datetime) -> None:
        tag_date = tag.commit.commit.committer.date
        self.recommended.reference = tag.commit.sha
        self.recommended.date = tag_date
        self.recommended.description = f"{tag.name}"
        if tag_date <= cutoff:
            self.min_age_tag_date = tag_date

    def _set_recommended_reference_and_date_to_tag_if_exists(self, valid_semver_tags: Sequence[Tag]) -> None:
        now = datetime.datetime.now(datetime.UTC)
        cutoff = now - datetime.timedelta(days=self._effective_min_age())
        self.min_age_tag_date = None
        current_version = self._get_actual_version()

        min_age_eligible_tag = None
        for tag in valid_semver_tags:
            tag_date = tag.commit.commit.committer.date
            if tag_date <= cutoff:
                min_age_eligible_tag = tag
                break

        selected_tag = None
        if min_age_eligible_tag is not None and (
            current_version is None or self._parse_tag_version(min_age_eligible_tag) >= current_version
        ):
            selected_tag = min_age_eligible_tag

        if selected_tag is None and current_version is not None:
            actual_tag = self._find_tag_for_version(valid_semver_tags, current_version)
            if actual_tag is not None and not self._tag_meets_min_age(actual_tag, cutoff):
                selected_tag = actual_tag
        elif selected_tag is None:
            selected_tag = min_age_eligible_tag

        if selected_tag is not None:
            self._apply_tag_recommendation(selected_tag, cutoff)
