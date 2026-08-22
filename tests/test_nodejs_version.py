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
    from pathlib import Path

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

    def test_dot_local_reference_uses_empty_action_dir(self) -> None:
        """A `./` path resolves to the current action directory."""
        checker = NodeVersionChecker(MagicMock(), 24)
        local = checker._resolve_target("./", _Location())
        remote = checker._resolve_target("./", _Location(repo_full_name="my/comp", ref="v2"))

        assert local == (_Location(), "", ".")
        assert remote is not None
        assert remote[1] == ""
        assert remote[2] == "my/comp@v2"

    def test_parent_local_reference_inside_local_composite(self) -> None:
        """A `../` path inside a local composite stays on the local work tree."""
        checker = NodeVersionChecker(MagicMock(), 24)

        resolved = checker._resolve_target("../nested", _Location())
        assert resolved is not None
        child_location, action_dir, display = resolved

        assert child_location == _Location()
        assert action_dir == "../nested"
        assert display == "./../nested"

    def test_owner_only_reference_with_ref_is_skipped(self) -> None:
        """A `name@ref` value that is not owner/repo cannot be resolved."""
        checker = NodeVersionChecker(MagicMock(), 24)
        assert checker._resolve_target("justname@v1", _Location()) is None


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

    def test_empty_action_list_returns_no_violations(self) -> None:
        """An empty unique-action set skips the Node.js walk entirely."""
        checker = NodeVersionChecker(MagicMock(), 24)

        assert not checker.check_actions([])

    def test_action_subdirectory_manifest_is_loaded(self) -> None:
        """Actions published under a repository subdirectory are resolved from that path."""
        g = make_github({"my/repo": {"subdir/action.yml": "runs:\n  using: node16\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action("my/repo/subdir", recommended_reference="sha", recommended_description="v1")

        violations = checker.check_actions([action])

        assert len(violations) == 1
        assert violations[0].action == "my/repo/subdir@v1"

    def test_falls_back_to_action_yaml_manifest(self) -> None:
        """`action.yaml` is used when `action.yml` is missing."""
        g = make_github({"actions/old": {"action.yaml": "runs:\n  using: node16\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action("actions/old", recommended_reference="sha", recommended_description="v1")

        violations = checker.check_actions([action])

        assert len(violations) == 1
        assert violations[0].node_version == 16

    def test_docker_using_is_skipped(self) -> None:
        """Docker-runtime manifests carry no Node.js version to compare."""
        g = make_github({"actions/docker": {"action.yml": "runs:\n  using: docker\n  image: Dockerfile\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action("actions/docker", recommended_reference="sha", recommended_description="v1")

        assert not checker.check_actions([action])

    def test_non_dict_runs_block_is_skipped(self) -> None:
        """A manifest whose `runs` value is not a mapping is ignored."""
        g = make_github({"weird/action": {"action.yml": "runs: 5\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action("weird/action", recommended_reference="sha")

        assert not checker.check_actions([action])

    def test_composite_without_steps_list_is_skipped(self) -> None:
        """A composite action with a non-list `steps` value has nothing to recurse into."""
        g = make_github({"my/comp": {"action.yml": "runs:\n  using: composite\n  steps: true\n"}})
        checker = NodeVersionChecker(g, 24)
        action = make_action("my/comp", recommended_reference="sha", recommended_description="v1")

        assert not checker.check_actions([action])

    def test_composite_skips_steps_without_uses(self) -> None:
        """Run-only composite steps are ignored while later `uses:` steps are still walked."""
        g = make_github(
            {
                "my/comp": {
                    "action.yml": (
                        "runs:\n"
                        "  using: composite\n"
                        "  steps:\n"
                        "    - run: echo hi\n"
                        "    - not a mapping\n"
                        "    - uses: docker://alpine:3\n"
                        "    - uses: justname@v1\n"
                        "    - uses: actions/old@v1\n"
                    )
                },
                "actions/old": {"action.yml": "runs:\n  using: node16\n"},
            }
        )
        checker = NodeVersionChecker(g, 24)
        action = make_action("my/comp", recommended_reference="sha", recommended_description="v2")

        violations = checker.check_actions([action])

        assert len(violations) == 1
        assert violations[0].chain == ("my/comp@v2", "actions/old@v1")

    def test_directory_contents_are_skipped(self) -> None:
        """A GitHub contents listing (directory) is not treated as a manifest file."""
        g = MagicMock()
        repo = MagicMock()
        repo.get_contents.return_value = [MagicMock()]
        g.get_repo.return_value = repo
        checker = NodeVersionChecker(g, 24)
        action = make_action("actions/old", recommended_reference="sha")

        assert not checker.check_actions([action])

    def test_undecodable_remote_manifest_is_skipped(self) -> None:
        """Remote files that cannot be decoded as UTF-8 are ignored."""
        g = MagicMock()
        repo = MagicMock()
        content_file = MagicMock()
        content_file.decoded_content.decode.side_effect = UnicodeDecodeError("utf-8", b"\x80", 0, 1, "bad")
        repo.get_contents.return_value = content_file
        g.get_repo.return_value = repo
        checker = NodeVersionChecker(g, 24)
        action = make_action("actions/old", recommended_reference="sha")

        assert not checker.check_actions([action])

    def test_assertion_error_decoding_remote_manifest_is_skipped(self) -> None:
        """Remote files that raise AssertionError while decoding are ignored."""
        g = MagicMock()
        repo = MagicMock()
        content_file = MagicMock()
        content_file.decoded_content.decode.side_effect = AssertionError("not a bytes payload")
        repo.get_contents.return_value = content_file
        g.get_repo.return_value = repo
        checker = NodeVersionChecker(g, 24)
        action = make_action("actions/old", recommended_reference="sha")

        assert not checker.check_actions([action])

    def test_repository_handles_are_cached(self) -> None:
        """Repeated lookups of the same repository reuse the cached handle."""
        g = make_github({"actions/old": {"action.yml": "runs:\n  using: node24\n"}})
        checker = NodeVersionChecker(g, 24)

        first = checker._get_repo("actions/old")
        second = checker._get_repo("actions/old")

        assert first is second
        assert g.get_repo.call_count == 1

    def test_local_composite_is_read_from_the_work_tree(self, tmp_path: Path) -> None:
        """Local `./` composite steps are resolved from the working tree."""
        (tmp_path / "action.yml").write_text(
            "runs:\n  using: composite\n  steps:\n    - uses: ./nested\n",
            encoding="utf-8",
        )
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "action.yml").write_text("runs:\n  using: node16\n", encoding="utf-8")
        checker = NodeVersionChecker(MagicMock(), 24, repo_root=tmp_path)

        checker._walk(_Location(), "", "local-root", (), 24)

        assert len(checker._violations) == 1
        assert checker._violations[0].chain == ("local-root", "./nested")
        assert checker._violations[0].node_version == 16

    def test_missing_local_manifest_is_skipped(self, tmp_path: Path) -> None:
        """A local path with no action manifest is skipped without error."""
        checker = NodeVersionChecker(MagicMock(), 24, repo_root=tmp_path)

        checker._walk(_Location(), "missing", "./missing", (), 24)

        assert not checker._violations

    def test_undecodable_local_manifest_is_skipped(self, tmp_path: Path) -> None:
        """Local files that are not valid UTF-8 are ignored."""
        (tmp_path / "action.yml").write_bytes(b"\x80\x81")
        checker = NodeVersionChecker(MagicMock(), 24, repo_root=tmp_path)

        checker._walk(_Location(), "", "local-root", (), 24)

        assert not checker._violations


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
