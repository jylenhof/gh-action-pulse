"""Tests for the recursive Node.js version checker."""

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from github.GithubException import GithubException

from gh_action_pulse.nodejs_version import (
    NodeVersionChecker,
    NodeVersionViolation,
    _Location,
    report_node_version_violations,
)


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


def scan(target: str) -> dict[Path, list[dict[int, str]]]:
    """Build a minimal scan result containing a single ``uses:`` line."""
    return {Path("wf.yml"): [{1: f"uses: {target}"}]}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("uses: actions/checkout@v4", "actions/checkout@v4"),
        ("- uses: actions/checkout@v4", "actions/checkout@v4"),
        ("- uses: actions/checkout@v4 # v4.1.1", "actions/checkout@v4"),
        ('uses: "actions/checkout@v4"', "actions/checkout@v4"),
        ("uses: './.github/actions/foo'", "./.github/actions/foo"),
        ("name: not a uses line", None),
    ],
)
def test_extract_target(line: str, expected: str | None) -> None:
    """Verify targets are extracted and unquoted from scanned lines."""
    assert NodeVersionChecker._extract_target(line) == expected


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


class TestNodeVersionChecker:
    """Behavioural tests exercising the recursive resolution."""

    def test_remote_node_action_below_minimum_is_reported(self) -> None:
        """A remote JavaScript action older than the minimum yields a violation."""
        g = make_github({"actions/old": {"action.yml": "runs:\n  using: node16\n  main: index.js\n"}})
        checker = NodeVersionChecker(g, 24)

        violations = checker.check_scanned_uses(scan("actions/old@v1"))

        assert len(violations) == 1
        assert violations[0].node_version == 16
        assert violations[0].action == "actions/old@v1"

    def test_remote_node_action_at_minimum_is_ok(self) -> None:
        """A remote JavaScript action meeting the minimum yields no violation."""
        g = make_github({"actions/new": {"action.yml": "runs:\n  using: node24\n  main: index.js\n"}})
        checker = NodeVersionChecker(g, 24)

        assert not checker.check_scanned_uses(scan("actions/new@v1"))

    def test_docker_action_is_ignored(self) -> None:
        """A docker:// reference is skipped without any API call."""
        g = make_github({})
        checker = NodeVersionChecker(g, 24)

        assert not checker.check_scanned_uses(scan("docker://rhysd/actionlint:1.6.23"))
        g.get_repo.assert_not_called()

    def test_action_yaml_extension_fallback(self, tmp_path: Path) -> None:
        """A local action defined in ``action.yaml`` (not ``.yml``) is still resolved."""
        action_dir = tmp_path / ".github" / "actions" / "bar"
        action_dir.mkdir(parents=True)
        (action_dir / "action.yaml").write_text("runs:\n  using: node16\n  main: index.js\n")
        checker = NodeVersionChecker(MagicMock(), 24, repo_root=tmp_path)

        violations = checker.check_scanned_uses(scan("./.github/actions/bar"))

        assert len(violations) == 1
        assert violations[0].node_version == 16

    def test_remote_composite_recurses_into_steps(self) -> None:
        """A composite action's steps are resolved recursively."""
        g = make_github(
            {
                "my/comp": {"action.yml": "runs:\n  using: composite\n  steps:\n    - uses: actions/old@v1\n"},
                "actions/old": {"action.yml": "runs:\n  using: node16\n"},
            }
        )
        checker = NodeVersionChecker(g, 24)

        violations = checker.check_scanned_uses(scan("my/comp@v2"))

        assert len(violations) == 1
        assert violations[0].node_version == 16
        assert violations[0].chain == ("my/comp@v2", "actions/old@v1")

    def test_local_composite_recurses_into_remote_and_local_dependencies(self, tmp_path: Path) -> None:
        """A local composite action pulling remote and local node actions reports both."""
        foo_dir = tmp_path / ".github" / "actions" / "foo"
        foo_dir.mkdir(parents=True)
        (foo_dir / "action.yml").write_text(
            "runs:\n"
            "  using: composite\n"
            "  steps:\n"
            "    - uses: actions/old@v1\n"
            "    - uses: ./.github/actions/bar\n"
            "    - run: echo hello\n"
        )
        bar_dir = tmp_path / ".github" / "actions" / "bar"
        bar_dir.mkdir(parents=True)
        (bar_dir / "action.yml").write_text("runs:\n  using: node16\n  main: index.js\n")

        g = make_github({"actions/old": {"action.yml": "runs:\n  using: node16\n"}})
        checker = NodeVersionChecker(g, 24, repo_root=tmp_path)

        violations = checker.check_scanned_uses(scan("./.github/actions/foo"))

        versions = sorted(v.node_version for v in violations)
        actions = {v.action for v in violations}
        assert versions == [16, 16]
        assert "actions/old@v1" in actions

    def test_missing_manifest_is_skipped(self) -> None:
        """When no manifest can be fetched, the action is skipped without error."""
        g = make_github({})
        checker = NodeVersionChecker(g, 24)

        assert not checker.check_scanned_uses(scan("actions/missing@v1"))

    def test_non_dict_manifest_is_skipped(self) -> None:
        """A manifest that does not parse into a mapping is ignored."""
        g = make_github({"weird/action": {"action.yml": "just a scalar string"}})
        checker = NodeVersionChecker(g, 24)

        assert not checker.check_scanned_uses(scan("weird/action@v1"))

    def test_invalid_yaml_manifest_is_skipped(self) -> None:
        """A manifest with invalid YAML is ignored rather than raising."""
        g = make_github({"broken/action": {"action.yml": "runs: [unbalanced\n"}})
        checker = NodeVersionChecker(g, 24)

        assert not checker.check_scanned_uses(scan("broken/action@v1"))

    def test_duplicate_references_are_deduplicated(self) -> None:
        """The same offending action referenced twice yields a single violation."""
        g = make_github({"actions/old": {"action.yml": "runs:\n  using: node16\n"}})
        checker = NodeVersionChecker(g, 24)
        results = {Path("wf.yml"): [{1: "uses: actions/old@v1"}, {2: "uses: actions/old@v1"}]}

        assert len(checker.check_scanned_uses(results)) == 1


def test_report_logs_error_per_violation(caplog: pytest.LogCaptureFixture) -> None:
    """Each violation is logged at ERROR level with its dependency chain."""
    violations = [NodeVersionViolation(node_version=16, chain=("my/comp@v2", "actions/old@v1"))]

    with caplog.at_level(logging.ERROR):
        report_node_version_violations(violations, 24)

    assert "actions/old@v1" in caplog.text
    assert "16" in caplog.text
    assert "my/comp@v2 -> actions/old@v1" in caplog.text
