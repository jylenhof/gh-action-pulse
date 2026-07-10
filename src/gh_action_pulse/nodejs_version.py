"""Verify that GitHub Actions run on at least a minimum Node.js version.

For every unique action discovered in the project, the check resolves the
manifest at the *recommended* reference (the reference the tool would update the
action to) rather than the currently pinned one, and reports when its Node.js
runtime is below the configured minimum. Composite actions are walked
recursively so that a dependency pulling in an outdated JavaScript action is
also reported.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import yaml
from github.GithubException import GithubException

if TYPE_CHECKING:
    from collections.abc import Iterable

    from github import Github
    from github.Repository import Repository

    from gh_action_pulse.actions import GithubAction

logger = logging.getLogger(__name__)

# ``runs.using`` values such as ``node20`` / ``node24``.
_NODE_USING_RE = re.compile(r"node(\d+)", re.IGNORECASE)
_MANIFEST_FILENAMES = ("action.yml", "action.yaml")
_MIN_OWNER_REPO_SEGMENTS = 2


@dataclass(frozen=True)
class NodeVersionViolation:
    """A resolved action whose Node.js runtime is older than the minimum required."""

    node_version: int
    chain: tuple[str, ...]

    @property
    def action(self) -> str:
        """Return the offending action (the last link of the dependency chain)."""
        return self.chain[-1]

    def format_chain(self) -> str:
        """Return a human readable representation of the dependency chain."""
        return " -> ".join(self.chain)


@dataclass(frozen=True)
class _Location:
    """Where a manifest lives: a remote repository at a ref, or the local work tree."""

    # None means the manifest is read from the local working tree.
    repo_full_name: str | None = None
    ref: str | None = None


class NodeVersionChecker:  # pylint: disable=too-few-public-methods
    """Resolve actions recursively and collect Node.js version violations.

    Exposes a single public entry point (``check_actions``) while keeping the
    recursion state (visited manifests, resolved violations, cached repositories)
    encapsulated in private helpers.
    """

    def __init__(self, g: Github, minimum_version: int, repo_root: Path | None = None) -> None:
        """Initialize the checker with a GitHub client and the minimum Node.js version."""
        self._g = g
        self._minimum = minimum_version
        self._root = repo_root if repo_root is not None else Path.cwd()
        self._violations: list[NodeVersionViolation] = []
        self._visited: set[tuple[str | None, str | None, str]] = set()
        self._repos: dict[str, Repository] = {}

    def check_actions(self, actions: Iterable[GithubAction]) -> list[NodeVersionViolation]:
        """Resolve each action at its recommended reference and return the violations found."""
        logger.info("Checking that recommended actions run on at least Node.js %d...", self._minimum)
        for action in actions:
            target = self._recommended_target(action)
            if target is None:
                continue
            location, action_dir, display = target
            self._walk(location, action_dir, display, ())
        logger.info(
            "Finished Node.js version check. Found %d action(s) below the minimum.\n",
            len(self._violations),
        )
        return self._violations

    @staticmethod
    def _recommended_target(action: GithubAction) -> tuple[_Location, str, str] | None:
        """Build the manifest location for the reference the tool recommends for an action."""
        full_name = action.recommended.repo_canonical_name or action.name
        ref = action.recommended.reference or action.actual.reference
        segments = full_name.split("/")
        if len(segments) < _MIN_OWNER_REPO_SEGMENTS or not ref:
            return None
        repo_full_name = "/".join(segments[:_MIN_OWNER_REPO_SEGMENTS])
        action_dir = "/".join(segments[_MIN_OWNER_REPO_SEGMENTS:])
        label = (
            action.recommended.description
            or action.recommended.reference
            or action.actual.description
            or action.actual.reference
        )
        return _Location(repo_full_name=repo_full_name, ref=ref), action_dir, f"{full_name}@{label}"

    def _resolve(self, target: str, location: _Location, chain: tuple[str, ...]) -> None:
        """Resolve a single ``uses:`` reference, recursing into composite actions."""
        resolved = self._resolve_target(target, location)
        if resolved is None:
            return
        child_location, action_dir, display = resolved
        self._walk(child_location, action_dir, display, chain)

    def _walk(self, location: _Location, action_dir: str, display: str, chain: tuple[str, ...]) -> None:
        """Load a resolved action manifest and process its ``runs`` block, recursing on composites."""
        key = (location.repo_full_name, location.ref, action_dir)
        if key in self._visited:
            return
        self._visited.add(key)

        new_chain = (*chain, display)
        manifest = self._load_manifest(location, action_dir)
        if manifest is None:
            logger.debug("Could not load action manifest for '%s'; skipping.", display)
            return

        runs = manifest.get("runs")
        if isinstance(runs, dict):
            self._process_runs(runs, location, new_chain)

    def _process_runs(self, runs: dict, location: _Location, chain: tuple[str, ...]) -> None:
        """Inspect a manifest ``runs`` block, recording node violations or recursing on composites."""
        using = str(runs.get("using", "")).strip()

        if node_match := _NODE_USING_RE.fullmatch(using):
            version = int(node_match.group(1))
            if version < self._minimum:
                self._violations.append(NodeVersionViolation(node_version=version, chain=chain))
            return

        if using.casefold() != "composite":
            return

        steps = runs.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict) and (step_uses := step.get("uses")):
                    self._resolve(str(step_uses), location, chain)

    def _resolve_target(
        self,
        target: str,
        location: _Location,
    ) -> tuple[_Location, str, str] | None:
        """Turn a ``uses:`` reference into (manifest location, action directory, display name).

        Returns None for references that carry no Node.js runtime (Docker actions) or that
        cannot be resolved (bare names without a ref that are not local paths).
        """
        if target.startswith("docker://"):
            return None

        if target.startswith(("./", "../")):
            action_dir = str(PurePosixPath(target))
            if action_dir in (".", ""):
                action_dir = ""
            if location.repo_full_name is None:
                display = f"./{action_dir}" if action_dir else "."
            else:
                suffix = f"/{action_dir}" if action_dir else ""
                display = f"{location.repo_full_name}{suffix}@{location.ref}"
            return location, action_dir, display

        if "@" in target:
            path_part, _, ref = target.partition("@")
            segments = path_part.split("/")
            if len(segments) < _MIN_OWNER_REPO_SEGMENTS:
                logger.debug("Skipping unresolvable action reference '%s'.", target)
                return None
            repo_full_name = "/".join(segments[:_MIN_OWNER_REPO_SEGMENTS])
            action_dir = "/".join(segments[_MIN_OWNER_REPO_SEGMENTS:])
            return _Location(repo_full_name=repo_full_name, ref=ref), action_dir, target

        logger.debug("Skipping unresolvable action reference '%s'.", target)
        return None

    def _load_manifest(self, location: _Location, action_dir: str) -> dict | None:
        """Load and parse an ``action.yml``/``action.yaml`` manifest for a given location."""
        for filename in _MANIFEST_FILENAMES:
            path = str(PurePosixPath(action_dir) / filename) if action_dir else filename
            content = self._read_file(location, path)
            if content is None:
                continue
            parsed = self._parse_manifest(content, path)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _parse_manifest(content: str, path: str) -> dict | None:
        """Parse YAML manifest content, returning the mapping or None when unusable."""
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError:
            logger.debug("Failed to parse YAML manifest at '%s'.", path)
            return None
        return parsed if isinstance(parsed, dict) else None

    def _read_file(self, location: _Location, path: str) -> str | None:
        """Read a manifest file either from the local work tree or a remote repository."""
        repo_full_name = location.repo_full_name
        ref = location.ref
        if repo_full_name is None or ref is None:
            file_path = self._root / path
            try:
                return file_path.read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                return None

        try:
            repo = self._get_repo(repo_full_name)
            contents = repo.get_contents(path, ref=ref)
        except GithubException:
            return None
        if isinstance(contents, list):
            # A directory was returned instead of a file.
            return None
        try:
            return contents.decoded_content.decode("utf-8")
        except UnicodeDecodeError, AssertionError:
            return None

    def _get_repo(self, repo_full_name: str) -> Repository:
        """Return a cached repository handle, fetching it from the API when needed."""
        if repo_full_name not in self._repos:
            self._repos[repo_full_name] = self._g.get_repo(repo_full_name)
        return self._repos[repo_full_name]


def report_node_version_violations(violations: Iterable[NodeVersionViolation], minimum_version: int) -> None:
    """Log an error for each action running below the required Node.js version."""
    for violation in violations:
        logger.error(
            "Action '%s' runs on Node.js %d which is below the required minimum of %d (dependency chain: %s).",
            violation.action,
            violation.node_version,
            minimum_version,
            violation.format_chain(),
        )
