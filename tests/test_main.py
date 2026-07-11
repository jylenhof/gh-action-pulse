"""Tests for CLI validation helpers in main."""

import datetime
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from gh_action_pulse.actions import GithubAction, GithubActionArchivedError
from gh_action_pulse.helpers.constants import (
    ARCHIVED_ACTION_ERROR_EXIT_CODE,
    GITHUB_TOKEN_ERROR_EXIT_CODE,
    MAX_MIN_AGE,
    NODEJS_VERSION_ERROR_EXIT_CODE,
    STALE_TAG_ERROR_EXIT_CODE,
)
from gh_action_pulse.main import (
    app,
    apply_recommended_updates,
    check_node_versions,
    validate_max_age,
    validate_max_age_cli,
    validate_min_age,
    validate_min_age_cli,
    validate_minimum_nodejs_version,
    validate_minimum_nodejs_version_cli,
    warn_about_stale_actions,
)
from gh_action_pulse.nodejs_version import NodeVersionViolation
from gh_action_pulse.uniq_actions import UniqGithubActions

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()


class TestValidateCliOptions:
    """Unit tests for CLI option validation helpers."""

    @patch("gh_action_pulse.main.__version__", "1.2.3")
    def test_version_option_prints_version_and_exits(self) -> None:
        """Verify that --version prints the package version and exits successfully."""
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert result.output.strip() == "1.2.3"

    def test_validate_min_age_accepts_valid_value(self) -> None:
        """Verify that values within the allowed range are accepted."""
        assert validate_min_age(0) == 0
        assert validate_min_age(MAX_MIN_AGE) == MAX_MIN_AGE

    def test_validate_min_age_rejects_negative_value(self) -> None:
        """Verify that negative min_age values are rejected."""
        with pytest.raises(ValueError, match=r"min_age must be 0 or greater\."):
            validate_min_age(-1)

    def test_validate_min_age_rejects_above_max(self) -> None:
        """Verify that min_age values above MAX_MIN_AGE are rejected."""
        with pytest.raises(ValueError, match=rf"min_age cannot exceed {MAX_MIN_AGE} days\."):
            validate_min_age(MAX_MIN_AGE + 1)

    def test_validate_min_age_cli_wraps_value_error(self) -> None:
        """Verify that the Typer callback converts ValueError into BadParameter."""
        with pytest.raises(typer.BadParameter, match=r"min_age must be 0 or greater\."):
            validate_min_age_cli(-1)

    def test_validate_min_age_cli_wraps_max_value_error(self) -> None:
        """Verify that the Typer callback surfaces the max-age validation error."""
        with pytest.raises(typer.BadParameter, match=rf"min_age cannot exceed {MAX_MIN_AGE} days\."):
            validate_min_age_cli(MAX_MIN_AGE + 1)

    def test_validate_max_age_accepts_zero(self) -> None:
        """Verify that 0 is accepted to disable the freshness check."""
        assert validate_max_age(0) == 0

    def test_validate_max_age_accepts_positive_value(self) -> None:
        """Verify that positive values are accepted."""
        assert validate_max_age(150) == 150

    def test_validate_max_age_rejects_negative_value(self) -> None:
        """Verify that negative values are rejected."""
        with pytest.raises(ValueError, match=r"max_age must be 0 or greater\."):
            validate_max_age(-1)

    def test_validate_max_age_cli_wraps_value_error(self) -> None:
        """Verify that the Typer callback converts ValueError into BadParameter."""
        with pytest.raises(typer.BadParameter, match=r"max_age must be 0 or greater\."):
            validate_max_age_cli(-1)

    def test_validate_minimum_nodejs_version_accepts_zero(self) -> None:
        """Verify that 0 is accepted to disable the Node.js version check."""
        assert validate_minimum_nodejs_version(0) == 0

    def test_validate_minimum_nodejs_version_accepts_positive_value(self) -> None:
        """Verify that positive values are accepted."""
        assert validate_minimum_nodejs_version(24) == 24

    def test_validate_minimum_nodejs_version_rejects_negative_value(self) -> None:
        """Verify that negative values are rejected."""
        with pytest.raises(ValueError, match=r"minimum_nodejs_version must be 0 or greater\."):
            validate_minimum_nodejs_version(-1)

    def test_validate_minimum_nodejs_version_cli_wraps_value_error(self) -> None:
        """Verify that the Typer callback converts ValueError into BadParameter."""
        with pytest.raises(typer.BadParameter, match=r"minimum_nodejs_version must be 0 or greater\."):
            validate_minimum_nodejs_version_cli(-1)


class TestCheckNodeVersions:
    """Unit tests for the Node.js version orchestration helper."""

    def test_disabled_when_minimum_is_zero(self) -> None:
        """A minimum of 0 skips the recursive Node.js check entirely."""
        uniq = MagicMock()

        assert not check_node_versions(MagicMock(), uniq, 0)

        uniq.get_actions.assert_not_called()

    @patch("gh_action_pulse.main.report_node_version_violations")
    @patch("gh_action_pulse.main.NodeVersionChecker")
    def test_reports_violations_when_enabled(
        self,
        mock_checker_cls: MagicMock,
        mock_report: MagicMock,
    ) -> None:
        """Violations from the checker are reported and returned to the caller."""
        violation = NodeVersionViolation(node_version=16, chain=("actions/old@v1",))
        mock_checker = MagicMock()
        mock_checker.check_actions.return_value = [violation]
        mock_checker_cls.return_value = mock_checker
        uniq = MagicMock()
        actions = {MagicMock()}
        uniq.get_actions.return_value = actions

        result = check_node_versions(MagicMock(), uniq, 24)

        assert result == [violation]
        mock_checker_cls.assert_called_once()
        mock_checker.check_actions.assert_called_once_with(actions)
        mock_report.assert_called_once_with([violation], 24)


class TestApplyRecommendedUpdates:
    """Unit tests for rewriting workflow files with recommended references."""

    def test_dry_run_leaves_files_unchanged(self, tmp_path: Path) -> None:
        """Dry-run mode must not persist rewritten uses lines."""
        workflow = tmp_path / "workflow.yml"
        original = "- uses: actions/checkout@v4\n"
        workflow.write_text(original, encoding="utf-8")

        action = GithubAction("actions/checkout", "v4")
        action.recommended.reference = "abc123"
        action.recommended.description = "v4.2.0"
        uniq = UniqGithubActions()
        uniq.add(action)

        apply_recommended_updates({workflow: [{1: original.rstrip("\n")}]}, uniq, dry_run=True)

        assert workflow.read_text(encoding="utf-8") == original

    def test_writes_recommended_reference_to_disk(self, tmp_path: Path) -> None:
        """Non-dry-run mode rewrites matching uses lines in place."""
        workflow = tmp_path / "workflow.yml"
        original = "- uses: actions/checkout@v4\n"
        workflow.write_text(original, encoding="utf-8")

        action = GithubAction("actions/checkout", "v4")
        action.recommended.reference = "abc123"
        action.recommended.description = "v4.2.0"
        uniq = UniqGithubActions()
        uniq.add(action)

        apply_recommended_updates({workflow: [{1: original.rstrip("\n")}]}, uniq, dry_run=False)

        updated = workflow.read_text(encoding="utf-8")
        assert updated == "- uses: actions/checkout@abc123 # v4.2.0\n"

    def test_skips_lines_without_replacement(self, tmp_path: Path) -> None:
        """Lines with no recommended update remain unchanged."""
        workflow = tmp_path / "workflow.yml"
        original = "- uses: actions/checkout@v4\n"
        workflow.write_text(original, encoding="utf-8")

        action = GithubAction("actions/checkout", "v4")
        uniq = UniqGithubActions()
        uniq.add(action)

        apply_recommended_updates({workflow: [{1: original.rstrip("\n")}]}, uniq, dry_run=False)

        assert workflow.read_text(encoding="utf-8") == original

    def test_ignores_lines_that_do_not_match_uses_pattern(self, tmp_path: Path) -> None:
        """Non-matching scanned lines are left untouched."""
        workflow = tmp_path / "workflow.yml"
        original = "name: Example\n"
        workflow.write_text(original, encoding="utf-8")

        apply_recommended_updates({workflow: [{1: "name: Example"}]}, UniqGithubActions(), dry_run=False)

        assert workflow.read_text(encoding="utf-8") == original


class TestWarnAboutStaleActions:
    """Unit tests for stale-action warning helpers."""

    def test_warns_when_no_semver_tags_exist(self, caplog: pytest.LogCaptureFixture) -> None:
        """Actions without semver tags emit a warning instead of a freshness error."""
        action = GithubAction("actions/example", "v1")
        action.has_semver_tags = False

        with caplog.at_level(logging.WARNING):
            warn_about_stale_actions([action], 150)

        assert "No semver tag found for action 'actions/example'" in caplog.text

    def test_logs_error_when_tag_is_stale(self, caplog: pytest.LogCaptureFixture) -> None:
        """Actions with an eligible tag older than max_age emit an error."""
        action = GithubAction("actions/example", "v1")
        action.has_semver_tags = True
        action.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=200)

        with caplog.at_level(logging.ERROR):
            warn_about_stale_actions([action], 150)

        assert "Min-age eligible tag for action 'actions/example' is 200 days old" in caplog.text

    def test_skips_actions_with_semver_tags_but_no_eligible_date(self, caplog: pytest.LogCaptureFixture) -> None:
        """Actions with semver tags but no min-age eligible date do not emit freshness errors."""
        action = GithubAction("actions/example", "v1")
        action.has_semver_tags = True
        action.min_age_tag_date = None

        with caplog.at_level(logging.WARNING):
            warn_about_stale_actions([action], 150)

        assert caplog.text == ""


class TestMainCommand:
    """Integration tests for the Typer entry point."""

    @staticmethod
    @contextmanager
    def _patched_main(
        *,
        stale_actions: list[GithubAction] | None = None,
        node_version_violations: list[NodeVersionViolation] | None = None,
        archived_repo: str | None = None,
    ) -> Iterator[tuple[MagicMock, MagicMock]]:
        with (
            patch("gh_action_pulse.main.get_github_token", return_value="token"),
            patch("gh_action_pulse.main.Github"),
            patch("gh_action_pulse.main.UniqGithubActions") as mock_uniq_cls,
            patch("gh_action_pulse.main.FullListOfExistingActions") as mock_scan_cls,
            patch(
                "gh_action_pulse.main.check_node_versions",
                return_value=[] if node_version_violations is None else node_version_violations,
            ),
            patch("gh_action_pulse.main.apply_recommended_updates") as mock_apply,
        ):
            mock_scan_cls.return_value.get_results.return_value = {}
            mock_uniq = MagicMock()
            mock_uniq.get_stale_actions.return_value = stale_actions or []
            if archived_repo is not None:
                mock_uniq.get_fully_qualified.side_effect = GithubActionArchivedError(archived_repo)
            mock_uniq_cls.return_value = mock_uniq
            yield mock_uniq, mock_apply

    def test_successful_run_exits_zero(self) -> None:
        """A successful scan with no stale actions or Node.js violations exits cleanly."""
        with self._patched_main() as (_uniq, mock_apply):
            result = runner.invoke(
                app,
                ["--dry-run", "--minimum-nodejs-version", "0", "--max-age", "0"],
            )

        assert result.exit_code == 0
        mock_apply.assert_called_once()

    @patch("gh_action_pulse.main.get_github_token")
    def test_missing_token_exits_with_dedicated_code(self, mock_get_token: MagicMock) -> None:
        """Token resolution failures exit with the dedicated authentication status code."""
        mock_get_token.side_effect = RuntimeError("missing token")

        result = runner.invoke(app, ["--minimum-nodejs-version", "0", "--max-age", "0"])

        assert result.exit_code == GITHUB_TOKEN_ERROR_EXIT_CODE

    def test_archived_action_exits_with_dedicated_code(self) -> None:
        """Archived upstream repositories cause the CLI to exit with the dedicated status code."""
        with self._patched_main(archived_repo="actions/archived"):
            result = runner.invoke(app, ["--minimum-nodejs-version", "0", "--max-age", "0"])

        assert result.exit_code == ARCHIVED_ACTION_ERROR_EXIT_CODE

    def test_stale_actions_exit_with_dedicated_code(self) -> None:
        """Stale upstream tags cause the CLI to exit with the dedicated status code."""
        stale_action = GithubAction("actions/stale", "v1")

        with self._patched_main(stale_actions=[stale_action]):
            result = runner.invoke(app, ["--minimum-nodejs-version", "0"])

        assert result.exit_code == STALE_TAG_ERROR_EXIT_CODE

    def test_node_version_violations_exit_three(self) -> None:
        """Node.js violations exit with the dedicated status code even when tags are stale."""
        stale_action = GithubAction("actions/stale", "v1")
        violations = [NodeVersionViolation(node_version=16, chain=("actions/old@v1",))]

        with self._patched_main(stale_actions=[stale_action], node_version_violations=violations):
            result = runner.invoke(app, [])

        assert result.exit_code == NODEJS_VERSION_ERROR_EXIT_CODE
