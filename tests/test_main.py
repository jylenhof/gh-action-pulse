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

"""Tests for CLI validation helpers in main."""

import datetime
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from gh_action_pulse.actions import GithubAction, GithubActionArchivedError
from gh_action_pulse.helpers.console import console
from gh_action_pulse.helpers.constants import (
    ARCHIVED_ACTION_ERROR_EXIT_CODE,
    GITHUB_TOKEN_ERROR_EXIT_CODE,
    MAX_MIN_AGE,
    NODEJS_VERSION_ERROR_EXIT_CODE,
    STALE_TAG_ERROR_EXIT_CODE,
)
from gh_action_pulse.helpers.uses_line import UsesOccurrence, parse_uses_line
from gh_action_pulse.main import (
    IgnoredCheck,
    OverriddenSetting,
    Replacement,
    UpdateResult,
    _format_uses_change,
    _print_summary,
    app,
    apply_recommended_updates,
    check_node_versions,
    collect_ignored_checks,
    collect_overridden_settings,
    report_ignored_checks,
    report_overridden_settings,
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

runner = CliRunner()


def _occurrence(file: Path, line_number: int, raw_line: str) -> UsesOccurrence:
    parsed = parse_uses_line(raw_line, file=file, line_number=line_number)
    assert parsed is not None
    return parsed


def _scan(workflow: Path, original: str) -> dict[Path, list[UsesOccurrence]]:
    return {workflow: [_occurrence(workflow, 1, original.rstrip("\n"))]}


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
        """A minimum of 0 skips the recursive Node.js check when no line overrides it."""
        uniq = MagicMock()
        uniq.get_actions.return_value = set()

        assert not check_node_versions(MagicMock(), uniq, 0)

        uniq.get_actions.assert_called_once()

    @patch("gh_action_pulse.main.report_node_version_violations")
    @patch("gh_action_pulse.main.NodeVersionChecker")
    def test_runs_when_minimum_is_zero_but_override_is_present(
        self,
        mock_checker_cls: MagicMock,
        mock_report: MagicMock,
    ) -> None:
        """A nodejs-version override re-enables the check for that line when the CLI minimum is 0."""
        mock_checker = MagicMock()
        mock_checker.check_actions.return_value = []
        mock_checker_cls.return_value = mock_checker
        overridden = GithubAction(
            "actions/old",
            "v1",
            comments=["v1", "gh-action-pulse: override[nodejs-version=20]"],
        )
        uniq = MagicMock()
        uniq.get_actions.return_value = {overridden}

        result = check_node_versions(MagicMock(), uniq, 0)

        assert not result
        mock_checker_cls.assert_called_once()
        mock_checker.check_actions.assert_called_once()
        mock_report.assert_called_once()

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
        action = MagicMock()
        action.ignores.return_value = False
        actions = {action}
        uniq.get_actions.return_value = actions

        result = check_node_versions(MagicMock(), uniq, 24)

        assert result == [violation]
        mock_checker_cls.assert_called_once()
        mock_checker.check_actions.assert_called_once_with(actions)
        mock_report.assert_called_once()
        assert mock_report.call_args.args == ([violation], 24)
        assert mock_report.call_args.kwargs["ignored_count"] == 0
        assert "elapsed" in mock_report.call_args.kwargs

    @patch("gh_action_pulse.main.report_node_version_violations")
    @patch("gh_action_pulse.main.NodeVersionChecker")
    def test_counts_nodejs_ignore_hints(
        self,
        mock_checker_cls: MagicMock,
        mock_report: MagicMock,
    ) -> None:
        """Actions with a nodejs-version ignore hint are counted in the phase status."""
        mock_checker = MagicMock()
        mock_checker.check_actions.return_value = []
        mock_checker_cls.return_value = mock_checker
        ignored = GithubAction(
            "actions/old",
            "v1",
            comments=["v1", "gh-action-pulse: ignore[nodejs-version]"],
        )
        uniq = MagicMock()
        uniq.get_actions.return_value = {ignored}

        result = check_node_versions(MagicMock(), uniq, 24)

        assert not result
        assert mock_report.call_args.kwargs["ignored_count"] == 1

    def test_disabled_when_minimum_is_zero_and_override_is_ignored(self) -> None:
        """An ignored nodejs-version override does not re-enable a disabled CLI check."""
        ignored = GithubAction(
            "actions/old",
            "v1",
            comments=[
                "v1",
                "gh-action-pulse: ignore[nodejs-version]",
                "gh-action-pulse: override[nodejs-version=20]",
            ],
        )
        uniq = MagicMock()
        uniq.get_actions.return_value = {ignored}

        assert not check_node_versions(MagicMock(), uniq, 0)


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
        action.recommended.comments = ["v4.2.0"]
        uniq = UniqGithubActions()
        uniq.add(action)

        apply_recommended_updates(_scan(workflow, original), uniq, dry_run=True)

        assert workflow.read_text(encoding="utf-8") == original

    def test_writes_recommended_reference_to_disk(self, tmp_path: Path) -> None:
        """Non-dry-run mode rewrites matching uses lines in place."""
        workflow = tmp_path / "workflow.yml"
        original = "- uses: actions/checkout@v4\n"
        workflow.write_text(original, encoding="utf-8")

        action = GithubAction("actions/checkout", "v4")
        action.recommended.reference = "abc123"
        action.recommended.description = "v4.2.0"
        action.recommended.comments = ["v4.2.0"]
        uniq = UniqGithubActions()
        uniq.add(action)

        apply_recommended_updates(_scan(workflow, original), uniq, dry_run=False)

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

        apply_recommended_updates(_scan(workflow, original), uniq, dry_run=False)

        assert workflow.read_text(encoding="utf-8") == original

    def test_skips_lines_when_recommended_matches_actual(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No change is logged or written when recommended reference already matches actual."""
        workflow = tmp_path / "workflow.yml"
        original = "- uses: actions/checkout@abc123 # v4.2.0\n"
        workflow.write_text(original, encoding="utf-8")

        action = GithubAction("actions/checkout", "abc123", "v4.2.0", comments=["v4.2.0"])
        action.recommended.reference = "abc123"
        action.recommended.description = "v4.2.0"
        action.recommended.comments = ["v4.2.0"]
        uniq = UniqGithubActions()
        uniq.add(action)

        with caplog.at_level(logging.DEBUG):
            result = apply_recommended_updates(_scan(workflow, original), uniq, dry_run=False)

        assert workflow.read_text(encoding="utf-8") == original
        assert result.files_changed == 0
        assert not result.replacements
        assert "Changing line number" not in caplog.text
        assert "Writing these changes" not in caplog.text

    def test_returns_replacements_for_summary(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Rewrites are returned for the summary and logged at DEBUG with from/to detail."""
        workflow = tmp_path / "workflow.yml"
        original = "- uses: actions/checkout@v4\n"
        workflow.write_text(original, encoding="utf-8")

        action = GithubAction("actions/checkout", "v4")
        action.recommended.reference = "abc123"
        action.recommended.description = "v4.2.0"
        action.recommended.comments = ["v4.2.0"]
        uniq = UniqGithubActions()
        uniq.add(action)

        with caplog.at_level(logging.DEBUG):
            result = apply_recommended_updates(_scan(workflow, original), uniq, dry_run=True)

        assert result.files_changed == 1
        assert len(result.replacements) == 1
        assert result.replacements[0].line_number == 1
        assert "Changing line number" in caplog.text
        assert "from:" in caplog.text
        assert "to:" in caplog.text
        assert workflow.read_text(encoding="utf-8") == original

    def test_updates_table_preserves_brackets_in_comments(self, tmp_path: Path) -> None:
        """Rich markup must not swallow ignore-hint brackets in the updates recap."""
        workflow = tmp_path / "workflow.yml"
        original = "- uses: actions/checkout@v4 # gh-action-pulse: ignore[max-days]\n"
        workflow.write_text(original, encoding="utf-8")

        action = GithubAction(
            "actions/checkout",
            "v4",
            "gh-action-pulse: ignore[max-days]",
            comments=["gh-action-pulse: ignore[max-days]"],
        )
        action.recommended.reference = "abc123"
        action.recommended.description = "v4.2.0"
        action.recommended.comments = ["v4.2.0", "gh-action-pulse: ignore[max-days]"]
        uniq = UniqGithubActions()
        uniq.add(action)

        with console.capture() as capture:
            apply_recommended_updates(_scan(workflow, original), uniq, dry_run=True)

        assert "ignore[max-days]" in capture.get()

    def test_updates_version_comment_while_preserving_ignore_hint(self, tmp_path: Path) -> None:
        """SHA-pinned actions keep extra comments when only the version comment changes."""
        workflow = tmp_path / "workflow.yml"
        sha = "548a7c3603594ec17c819e1239f281a3b801ab4d"
        original = (
            f"        uses: crazy-max/ghaction-github-labeler@{sha} # v5.0.0 # gh-action-pulse: ignore[max-days]\n"
        )
        workflow.write_text(original, encoding="utf-8")

        action = GithubAction(
            "crazy-max/ghaction-github-labeler",
            sha,
            "v5.0.0",
            comments=["v5.0.0", "gh-action-pulse: ignore[max-days]"],
        )
        action.actual.reference_type = "sha"
        action.actual.description_type = "tag"
        action.recommended.reference = sha
        action.recommended.description = "v6.0.0"
        with (
            patch("gh_action_pulse.actions.GithubAction._get_valid_semver_tags", return_value=[]),
            patch("gh_action_pulse.actions.GithubAction._set_recommended_for_sha") as mock_set_sha,
        ):

            def set_recommendation(_tags: list) -> None:
                action.recommended.reference = sha
                action.recommended.description = "v6.0.0"

            mock_set_sha.side_effect = set_recommendation
            action._set_recommended_reference_and_date()

        uniq = UniqGithubActions()
        uniq.add(action)

        apply_recommended_updates(_scan(workflow, original), uniq, dry_run=False)

        assert (
            workflow.read_text(encoding="utf-8")
            == f"        uses: crazy-max/ghaction-github-labeler@{sha} # v6.0.0 # gh-action-pulse: ignore[max-days]\n"
        )

    def test_preserves_distinct_extra_comments_for_the_same_pin(self, tmp_path: Path) -> None:
        """Two uses lines with the same pin keep their own extra comments after an update."""
        workflow = tmp_path / "workflow.yml"
        original = (
            "- uses: actions/checkout@abc123 # v4.2.0 # gh-action-pulse: ignore[max-days]\n"
            "- uses: actions/checkout@abc123 # v4.2.0 # keep me\n"
        )
        workflow.write_text(original, encoding="utf-8")

        ignore_action = GithubAction(
            "actions/checkout",
            "abc123",
            "v4.2.0",
            comments=["v4.2.0", "gh-action-pulse: ignore[max-days]"],
        )
        ignore_action.recommended.reference = "def456"
        ignore_action.recommended.description = "v4.3.0"
        ignore_action.recommended.comments = ["v4.3.0", "gh-action-pulse: ignore[max-days]"]
        note_action = GithubAction(
            "actions/checkout",
            "abc123",
            "v4.2.0",
            comments=["v4.2.0", "keep me"],
        )
        note_action.recommended.reference = "def456"
        note_action.recommended.description = "v4.3.0"
        note_action.recommended.comments = ["v4.3.0", "keep me"]
        uniq = UniqGithubActions()
        uniq.add(ignore_action)
        uniq.add(note_action)

        apply_recommended_updates(
            {
                workflow: [
                    _occurrence(workflow, 1, original.splitlines()[0]),
                    _occurrence(workflow, 2, original.splitlines()[1]),
                ]
            },
            uniq,
            dry_run=False,
        )

        assert workflow.read_text(encoding="utf-8") == (
            "- uses: actions/checkout@def456 # v4.3.0 # gh-action-pulse: ignore[max-days]\n"
            "- uses: actions/checkout@def456 # v4.3.0 # keep me\n"
        )

    def test_format_uses_change_falls_back_when_line_has_no_uses(self) -> None:
        """Lines that do not contain `uses:` are shown stripped as old → new."""
        assert _format_uses_change("  old pin  ", "  new pin  ") == "old pin → new pin"


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

    def test_mentions_ignored_count_when_fresh(self) -> None:
        """The freshness phase reports how many max-age checks were skipped."""
        with console.capture() as capture:
            warn_about_stale_actions([], 150, ignored_count=2)

        assert "OK (2 ignored)" in capture.get()

    def test_mentions_ignored_count_when_stale(self) -> None:
        """Stale results still mention how many max-age checks were skipped."""
        action = GithubAction("actions/example", "v1")
        action.has_semver_tags = True
        action.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=200)

        with console.capture() as capture:
            warn_about_stale_actions([action], 150, ignored_count=1)

        assert "1 stale (1 ignored)" in capture.get()

    def test_omits_limit_in_title_when_max_age_is_disabled(self) -> None:
        """Override-driven stale results still render when the CLI max-age is 0."""
        action = GithubAction("actions/example", "v1")
        action.has_semver_tags = False

        with console.capture() as capture:
            warn_about_stale_actions([action], 0)

        output = capture.get()
        assert "Stale tags" in output
        assert "max-age" not in output

    def test_is_silent_when_disabled_and_nothing_is_stale(self) -> None:
        """A disabled freshness check with no stale actions prints nothing."""
        with console.capture() as capture:
            warn_about_stale_actions([], 0)

        assert capture.get() == ""


class TestIgnoredChecks:
    """Unit tests for inline ignore-hint collection and reporting."""

    def test_collects_enabled_checks_and_unknown_ids(self, caplog: pytest.LogCaptureFixture) -> None:
        """Known ignores are collected only when that check is enabled; unknown ids always are."""
        ignored = GithubAction(
            "actions/old",
            "v1",
            "v1",
            comments=["v1", 'gh-action-pulse: ignore["max-age", "nodejs-version"]'],
        )
        unknown = GithubAction(
            "actions/cache",
            "v4",
            comments=["gh-action-pulse: ignore[max-days]"],
        )
        plain = GithubAction("actions/checkout", "v4")

        with caplog.at_level(logging.WARNING):
            result = collect_ignored_checks(
                [plain, ignored, unknown],
                max_age_enabled=True,
                min_age_enabled=False,
                nodejs_enabled=False,
            )

        assert result == [
            IgnoredCheck(
                "actions/cache",
                "max-days",
                "unknown check id (allowed: max-age, min-age, nodejs-version)",
            ),
            IgnoredCheck("actions/old", "max-age", "hint on uses: line"),
        ]
        assert "Unknown ignore check 'max-days' on action 'actions/cache'" in caplog.text

    def test_collects_nodejs_ignore_when_enabled(self) -> None:
        """A nodejs-version hint is recorded only when that check is enabled."""
        action = GithubAction(
            "actions/old",
            "v1",
            comments=["v1", "gh-action-pulse: ignore[nodejs-version]"],
        )

        skipped = collect_ignored_checks([action], max_age_enabled=False, min_age_enabled=False, nodejs_enabled=True)
        disabled = collect_ignored_checks([action], max_age_enabled=False, min_age_enabled=False, nodejs_enabled=False)

        assert skipped == [IgnoredCheck("actions/old", "nodejs-version", "hint on uses: line")]
        assert not disabled

    def test_collects_min_age_ignore_when_enabled(self) -> None:
        """A min-age hint is recorded only when that wait is enabled."""
        action = GithubAction(
            "actions/checkout",
            "v4",
            comments=["v4", "gh-action-pulse: ignore[min-age]"],
        )

        skipped = collect_ignored_checks([action], max_age_enabled=False, min_age_enabled=True, nodejs_enabled=False)
        disabled = collect_ignored_checks([action], max_age_enabled=False, min_age_enabled=False, nodejs_enabled=False)

        assert skipped == [IgnoredCheck("actions/checkout", "min-age", "hint on uses: line")]
        assert not disabled

    def test_report_prints_ignored_checks_table(self) -> None:
        """The ignored-checks recap lists the action, check id, and why it was skipped."""
        with console.capture() as capture:
            report_ignored_checks([IgnoredCheck("actions/old", "max-age", "hint on uses: line")])

        output = capture.get()
        assert "Ignored checks" in output
        assert "actions/old" in output
        assert "max-age" in output
        assert "hint on uses: line" in output

    def test_report_is_silent_when_empty(self) -> None:
        """No ignored-checks table is printed when nothing was skipped."""
        with console.capture() as capture:
            report_ignored_checks([])

        assert capture.get() == ""

    def test_summary_includes_ignored_checks(self) -> None:
        """The closing summary mentions skipped checks when ignore hints were used."""
        with console.capture() as capture:
            _print_summary(
                update_result=UpdateResult(),
                stale_actions=[],
                node_version_violations=[],
                ignored_checks=[IgnoredCheck("actions/old", "max-age", "hint on uses: line")],
                overridden_settings=[],
                dry_run=True,
                exit_code=0,
            )

        assert "1 ignored check" in capture.get()

    def test_summary_includes_overrides(self) -> None:
        """The closing summary mentions override hints when they were used."""
        with console.capture() as capture:
            _print_summary(
                update_result=UpdateResult(),
                stale_actions=[],
                node_version_violations=[],
                ignored_checks=[],
                overridden_settings=[OverriddenSetting("actions/old", "max-age", "200 days (CLI: 150)")],
                dry_run=True,
                exit_code=0,
            )

        assert "1 override" in capture.get()

    def test_summary_describes_applied_and_proposed_updates(self) -> None:
        """The closing summary distinguishes dry-run proposals from applied rewrites."""
        one = UpdateResult(
            files_changed=1,
            replacements=[Replacement(file=Path("a.yml"), line_number=1, old="old", new="new")],
        )
        two = UpdateResult(
            files_changed=2,
            replacements=[
                Replacement(file=Path("a.yml"), line_number=1, old="old", new="new"),
                Replacement(file=Path("b.yml"), line_number=2, old="older", new="newer"),
            ],
        )

        with console.capture() as capture:
            _print_summary(
                update_result=one,
                stale_actions=[],
                node_version_violations=[],
                ignored_checks=[],
                overridden_settings=[],
                dry_run=False,
                exit_code=0,
            )
        assert "1 update applied" in capture.get()

        with console.capture() as capture:
            _print_summary(
                update_result=two,
                stale_actions=[GithubAction("actions/a", "v1"), GithubAction("actions/b", "v1")],
                node_version_violations=[
                    NodeVersionViolation(node_version=16, chain=("actions/old@v1",)),
                    NodeVersionViolation(node_version=20, chain=("actions/other@v2",)),
                ],
                ignored_checks=[
                    IgnoredCheck("actions/a", "max-age", "hint on uses: line"),
                    IgnoredCheck("actions/b", "min-age", "hint on uses: line"),
                ],
                overridden_settings=[
                    OverriddenSetting("actions/a", "max-age", "200 days (CLI: 150)"),
                    OverriddenSetting("actions/b", "nodejs-version", "20 (CLI: 24)"),
                ],
                dry_run=True,
                exit_code=3,
            )
        output = capture.get()
        assert "2 updates proposed" in output
        assert "2 stale tags" in output
        assert "2 Node.js violations" in output
        assert "2 ignored checks" in output
        assert "2 overrides" in output
        assert "exit 3" in output


class TestOverriddenSettings:
    """Unit tests for inline override-hint collection and reporting."""

    def test_collects_valid_overrides_and_unknown_keys(self, caplog: pytest.LogCaptureFixture) -> None:
        """Known assignments are recapped; unknown keys are warned about."""
        overridden = GithubAction(
            "actions/old",
            "v1",
            "v1",
            comments=["v1", "gh-action-pulse: override[max-age=200, nodejs-version=20]"],
        )
        unknown = GithubAction(
            "actions/cache",
            "v4",
            comments=["gh-action-pulse: override[stale-days=10]"],
        )
        ignored = GithubAction(
            "actions/checkout",
            "v4",
            comments=["v4", "gh-action-pulse: ignore[max-age]", "gh-action-pulse: override[max-age=200]"],
        )
        plain = GithubAction("actions/setup-python", "v5")

        with caplog.at_level(logging.WARNING):
            result = collect_overridden_settings(
                [plain, overridden, unknown, ignored],
                min_age=7,
                max_age=150,
                minimum_nodejs_version=24,
            )

        assert result == [
            OverriddenSetting(
                "actions/cache",
                "stale-days",
                "unknown override key (allowed: max-age, min-age, nodejs-version)",
            ),
            OverriddenSetting("actions/old", "max-age", "200 days (CLI: 150)"),
            OverriddenSetting("actions/old", "nodejs-version", "20 (CLI: 24)"),
        ]
        assert "Unknown override key 'stale-days' on action 'actions/cache'" in caplog.text

    def test_collects_invalid_override_values(self, caplog: pytest.LogCaptureFixture) -> None:
        """Out-of-range assignments are recapped without being applied."""
        action = GithubAction(
            "actions/checkout",
            "v4",
            comments=["v4", "gh-action-pulse: override[min-age=-1]"],
        )

        with caplog.at_level(logging.WARNING):
            result = collect_overridden_settings(
                [action],
                min_age=7,
                max_age=150,
                minimum_nodejs_version=24,
            )

        assert result == [OverriddenSetting("actions/checkout", "min-age", "min-age must be 0 or greater.")]
        assert "Invalid override 'min-age' on action 'actions/checkout'" in caplog.text

    def test_collects_min_age_override(self) -> None:
        """A min-age override is recapped in days against the CLI default."""
        action = GithubAction(
            "actions/checkout",
            "v4",
            comments=["v4", "gh-action-pulse: override[min-age=3]"],
        )

        result = collect_overridden_settings(
            [action],
            min_age=7,
            max_age=150,
            minimum_nodejs_version=24,
        )

        assert result == [OverriddenSetting("actions/checkout", "min-age", "3 days (CLI: 7)")]

    def test_report_prints_overridden_settings_table(self) -> None:
        """The override recap lists the action, setting, and applied value."""
        with console.capture() as capture:
            report_overridden_settings([OverriddenSetting("actions/old", "max-age", "200 days (CLI: 150)")])

        output = capture.get()
        assert "Overridden settings" in output
        assert "actions/old" in output
        assert "max-age" in output
        assert "200 days (CLI: 150)" in output

    def test_report_is_silent_when_empty(self) -> None:
        """No override table is printed when nothing was overridden."""
        with console.capture() as capture:
            report_overridden_settings([])

        assert capture.get() == ""


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
            patch("gh_action_pulse.main.apply_recommended_updates", return_value=UpdateResult()) as mock_apply,
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

    def test_help_lists_option_environment_variables(self) -> None:
        """Typer help text documents the env vars wired to each configurable option."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        # Rich help truncates long env var names; assert on the shared prefix.
        assert result.output.count("GH_ACTION_PULSE_") >= 5
        assert result.output.count("[env var:") >= 5

    def test_options_can_be_set_from_environment_variables(self) -> None:
        """Configured env vars are accepted when the matching CLI flags are omitted."""
        with self._patched_main() as (_uniq, mock_apply):
            result = runner.invoke(
                app,
                [],
                env={
                    "GH_ACTION_PULSE_DRY_RUN": "1",
                    "GH_ACTION_PULSE_LOG_LEVEL": "WARNING",
                    "GH_ACTION_PULSE_MIN_AGE": "7",
                    "GH_ACTION_PULSE_MAX_AGE": "0",
                    "GH_ACTION_PULSE_MINIMUM_NODEJS_VERSION": "0",
                },
            )

        assert result.exit_code == 0
        mock_apply.assert_called_once_with({}, _uniq, dry_run=True)

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
