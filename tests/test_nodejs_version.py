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

"""Tests for the recursive Node.js version checker (recommended-reference based)."""

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from github.GithubException import GithubException

from gh_action_pulse.actions import GithubAction
from gh_action_pulse.helpers.console import console
from gh_action_pulse.nodejs_version import (
    NodeVersionChecker,
    NodeVersionViolation,
    _Location,
    report_node_version_violations,
)

if TYPE_CHECKING:
    import pytest


def make_github(repo_files: dict[str, dict[str, str]]) -> MagicMock:
    """Build a fake ``Github`` client backed by an in-memory {repo: {path: content}} map."""
    g = MagicMock()

    def _get_repo(name: str) -> MagicMock:
        if name not in repo_files:
            raise GithubException(404, None, None)
        repo = MagicMock()
        files = repo_files[name]

        def _get_contents(path: str, **_kwargs: object) -> MagicMock:
            if path in files:
                content_file = MagicMock()
                content_file.decoded_content = files[path].encode("utf-8")
                return content_file
            raise GithubException(404, None, None)

        repo.get_contents.side_effect = _get_contents
        return repo

    g.get_repo.side_effect = _get_repo
    return g


def make_action(  # noqa: PLR0913
    name: str,
    *,
    reference: str = "v1",
    description: str | None = None,
    comments: list[str] | None = None,
    recommended_reference: str | None = None,
    recommended_description: str | None = None,
    canonical: str | None = None,
) -> GithubAction:
    """Build a GithubAction with an optional recommendation, as produced by the resolver."""
    action = GithubAction(name=name, reference=reference, actual_description=description, comments=comments)
    action.recommended.reference = recommended_reference
    action.recommended.description = recommended_description
    action.recommended.repo_canonical_name = canonical
    return action


class TestResolveTarget:
    """Unit tests for reference classification."""

    def test_docker_reference_is_skipped(self) -> None:
        """Docker actions carry no Node.js runtime and must be ignored."""
        checker = NodeVersionChecker(MagicMock(), 24)
        assert checker._resolve_target("docker://alpine:3", _Location()) is None

    def test_bare_reference_without_ref_is_skipped(self) -> None:
        """A bare name without a ref that is not local cannot be resolved."""
        checker = NodeVersionChecker(MagicMock(), 24)
        assert checker._resolve_target("just-a-name", _Location()) is None

    def test_local_reference_inside_remote_composite_stays_remote(self) -> None:
        """A local ``./path`` inside a remote composite resolves within that same repo."""
        checker = NodeVersionChecker(MagicMock(), 24)
        remote = _Location(repo_full_name="my/comp", ref="v2")

        resolved = checker._resolve_target("./nested", remote)
        assert resolved is not None
        child_location, action_dir, display = resolved

        assert child_location == remote
        assert action_dir == "nested"
        assert display == "my/comp/nested@v2"


class TestCheckActions:
    """Behavioural tests exercising the recommended-reference resolution."""

    def test_recommended_node_action_below_minimum_is_reported(self) -> None:
        """An action whose recommended reference still runs an old Node.js version is reported."""
        g = make_github({"actions/checkout": {"action.yml": "runs:\n  using: node20\n  main: index.js\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action(
            "actions/checkout",
            reference="v4",
            recommended_reference="sha123",
            recommended_description="v5.0.0",
        )

        violations = checker.check_actions([action])

        assert len(violations) == 1
        assert violations[0].node_version == 20
        assert violations[0].action == "actions/checkout@v5.0.0"

    def test_recommended_node_action_at_minimum_is_ok(self) -> None:
        """An action whose recommended reference meets the minimum yields no violation."""
        g = make_github({"actions/checkout": {"action.yml": "runs:\n  using: node24\n  main: index.js\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action(
            "actions/checkout",
            reference="v4",
            recommended_reference="sha",
            recommended_description="v5",
        )

        assert not checker.check_actions([action])

    def test_recommended_canonical_repository_is_used(self) -> None:
        """The recommended canonical repository (after a redirect) is the one inspected."""
        g = make_github({"googleapis/release-please-action": {"action.yml": "runs:\n  using: node16\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action(
            "GoogleCloudPlatform/release-please-action",
            reference="v3",
            recommended_reference="sha",
            recommended_description="v4.0.0",
            canonical="googleapis/release-please-action",
        )

        violations = checker.check_actions([action])

        assert len(violations) == 1
        assert violations[0].node_version == 16
        assert violations[0].action == "googleapis/release-please-action@v4.0.0"

    def test_falls_back_to_actual_reference_without_recommendation(self) -> None:
        """When no recommendation exists, the actual reference is inspected instead."""
        g = make_github({"actions/old": {"action.yml": "runs:\n  using: node16\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action("actions/old", reference="v1", description="v1")

        violations = checker.check_actions([action])

        assert len(violations) == 1
        assert violations[0].action == "actions/old@v1"

    def test_composite_recurses_into_steps(self) -> None:
        """A recommended composite action's steps are resolved recursively."""
        g = make_github(
            {
                "my/comp": {"action.yml": "runs:\n  using: composite\n  steps:\n    - uses: actions/old@v1\n"},
                "actions/old": {"action.yml": "runs:\n  using: node16\n"},
            }
        )
        checker = NodeVersionChecker(g, 24)
        action = make_action("my/comp", reference="v2", recommended_reference="sha", recommended_description="v2.1.0")

        violations = checker.check_actions([action])

        assert len(violations) == 1
        assert violations[0].node_version == 16
        assert violations[0].chain == ("my/comp@v2.1.0", "actions/old@v1")

    def test_missing_manifest_is_skipped(self) -> None:
        """When no manifest can be fetched, the action is skipped without error."""
        g = make_github({})
        checker = NodeVersionChecker(g, 24)
        action = make_action("actions/missing", reference="v1", recommended_reference="sha")

        assert not checker.check_actions([action])

    def test_non_dict_manifest_is_skipped(self) -> None:
        """A manifest that does not parse into a mapping is ignored."""
        g = make_github({"weird/action": {"action.yml": "just a scalar string"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action("weird/action", reference="v1", recommended_reference="sha")

        assert not checker.check_actions([action])

    def test_invalid_yaml_manifest_is_skipped(self) -> None:
        """A manifest with invalid YAML is ignored rather than raising."""
        g = make_github({"broken/action": {"action.yml": "runs: [unbalanced\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action("broken/action", reference="v1", recommended_reference="sha")

        assert not checker.check_actions([action])

    def test_bare_name_action_is_skipped(self) -> None:
        """An action name that is not owner/repo cannot be resolved and is skipped."""
        g = make_github({})
        checker = NodeVersionChecker(g, 24)
        action = make_action("justname", reference="v1")

        assert not checker.check_actions([action])
        g.get_repo.assert_not_called()

    def test_duplicate_references_are_deduplicated(self) -> None:
        """The same offending action inspected twice yields a single violation."""
        g = make_github({"actions/old": {"action.yml": "runs:\n  using: node16\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action("actions/old", recommended_reference="sha", recommended_description="v1")

        assert len(checker.check_actions([action, action])) == 1

    def test_nodejs_ignore_hint_skips_the_action(self) -> None:
        """An ignore[nodejs-version] hint skips that root action without inspecting it."""
        g = make_github({"actions/old": {"action.yml": "runs:\n  using: node16\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action(
            "actions/old",
            comments=["v1", "gh-action-pulse: ignore[nodejs-version]"],
            recommended_reference="sha",
            recommended_description="v1",
        )

        assert not checker.check_actions([action])
        g.get_repo.assert_not_called()

    def test_nodejs_ignore_hint_does_not_skip_other_actions(self) -> None:
        """A sibling action without an ignore hint is still inspected."""
        g = make_github(
            {
                "actions/old": {"action.yml": "runs:\n  using: node16\n"},
                "actions/checkout": {"action.yml": "runs:\n  using: node20\n"},
            }
        )
        checker = NodeVersionChecker(g, 24)
        ignored = make_action(
            "actions/old",
            comments=["v1", "gh-action-pulse: ignore[nodejs-version]"],
            recommended_reference="sha",
            recommended_description="v1",
        )
        other = make_action(
            "actions/checkout",
            recommended_reference="sha",
            recommended_description="v4",
        )

        violations = checker.check_actions([ignored, other])

        assert len(violations) == 1
        assert violations[0].action == "actions/checkout@v4"

    def test_nodejs_override_hint_lowers_the_minimum(self) -> None:
        """An override[nodejs-version=16] hint accepts a runtime below the CLI minimum."""
        g = make_github({"actions/old": {"action.yml": "runs:\n  using: node16\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action(
            "actions/old",
            comments=["v1", "gh-action-pulse: override[nodejs-version=16]"],
            recommended_reference="sha",
            recommended_description="v1",
        )

        assert not checker.check_actions([action])

    def test_nodejs_override_hint_still_fails_below_override(self) -> None:
        """An override does not skip the check; it only changes the threshold."""
        g = make_github({"actions/old": {"action.yml": "runs:\n  using: node16\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action(
            "actions/old",
            comments=["v1", "gh-action-pulse: override[nodejs-version=20]"],
            recommended_reference="sha",
            recommended_description="v1",
        )

        violations = checker.check_actions([action])

        assert len(violations) == 1
        assert violations[0].node_version == 16
        assert violations[0].minimum_version == 20

    def test_nodejs_override_zero_skips_the_action(self) -> None:
        """override[nodejs-version=0] disables the Node.js check for that line."""
        g = make_github({"actions/old": {"action.yml": "runs:\n  using: node16\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action(
            "actions/old",
            comments=["v1", "gh-action-pulse: override[nodejs-version=0]"],
            recommended_reference="sha",
            recommended_description="v1",
        )

        assert not checker.check_actions([action])
        g.get_repo.assert_not_called()


def test_report_mentions_ignored_count() -> None:
    """The Node.js phase status includes how many root actions were skipped."""
    with console.capture() as capture:
        report_node_version_violations([], 24, ignored_count=1)

    assert "OK (1 ignored)" in capture.get()


def test_report_logs_error_per_violation(caplog: pytest.LogCaptureFixture) -> None:
    """Each violation is logged at ERROR level with its dependency chain."""
    violations = [NodeVersionViolation(node_version=16, chain=("my/comp@v2", "actions/old@v1"))]

    with caplog.at_level(logging.ERROR):
        report_node_version_violations(violations, 24)

    assert "actions/old@v1" in caplog.text
    assert "16" in caplog.text
    assert "my/comp@v2 -> actions/old@v1" in caplog.text
