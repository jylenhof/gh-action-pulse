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

"""Tests for the GithubAction class to ensure correct parsing and comparison."""

# pylint: disable=too-many-lines

import datetime
from typing import TYPE_CHECKING, ClassVar, Literal
from unittest.mock import MagicMock, patch

import pytest
from github.GithubException import GithubException, UnknownObjectException
from testfixtures import LogCapture, log_capture

from gh_action_pulse.actions import (
    GithubAction,
    GithubActionArchivedError,
    GithubActionReferenceNotFoundError,
    parse_version_tag,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


@pytest.fixture
def create_mock_tag() -> Callable[..., MagicMock]:
    """Fixture factory to create a mock tag object with a name attribute."""

    def _make_mock_tag(name: str) -> MagicMock:
        tag = MagicMock()
        tag.name = name
        return tag

    return _make_mock_tag


class TestGithubAction:
    """Unit tests for GithubAction model and behavior."""

    @pytest.fixture
    def _no_version_tags(self) -> Iterator[None]:
        with patch("gh_action_pulse.actions.GithubAction._get_version_tags", return_value=[]):
            yield

    def test_equality(self) -> None:
        """Verify equality and hash semantics for GithubAction instances."""
        a1 = GithubAction("repo", "v1", "desc")
        a2 = GithubAction("repo", "v1", "desc")
        a3 = GithubAction("repo", "v2", "desc")
        a4 = GithubAction("repo", "v1", "desc", comments=["desc", "gh-action-pulse: ignore[max-age]"])

        assert a1 == a2
        assert a1 != a3
        assert a1 != a4
        assert len({a1, a2}) == 1
        assert len({a1, a4}) == 2

        # Coverage for comparison with a different type
        assert a1 != "not a GithubAction"

    def test_parses_ignore_hints_from_comments(self) -> None:
        """Trailing ignore hints are stored as skipped check ids on the actual state."""
        action = GithubAction(
            "actions/checkout",
            "abc123",
            "v4.2.2",
            comments=["v4.2.2", 'gh-action-pulse: ignore["max-age", "min-age", "nodejs-version"]'],
        )

        assert action.ignores("max-age")
        assert action.ignores("min-age")
        assert action.ignores("nodejs-version")
        assert action.actual.ignore_hint.checks == frozenset({"max-age", "min-age", "nodejs-version"})
        assert action.actual.ignore_hint.unknown == frozenset()

    def test_unknown_ignore_check_ids_are_kept_separate(self) -> None:
        """Unrecognized ignore ids are not treated as skipped checks."""
        action = GithubAction(
            "actions/checkout",
            "abc123",
            "v4.2.2",
            comments=["v4.2.2", "gh-action-pulse: ignore[max-days]"],
        )

        assert not action.ignores("max-age")
        assert action.actual.ignore_hint.checks == frozenset()
        assert action.actual.ignore_hint.unknown == frozenset({"max-days"})

    def test_parses_override_hints_from_comments(self) -> None:
        """Trailing override hints are stored as per-check thresholds on the actual state."""
        action = GithubAction(
            "actions/checkout",
            "abc123",
            "v4.2.2",
            comments=["v4.2.2", "gh-action-pulse: override[max-age=200, min-age=3, nodejs-version=20]"],
        )

        assert action.override("max-age") == 200
        assert action.override("min-age") == 3
        assert action.override("nodejs-version") == 20
        assert action.effective_max_age(150) == 200
        assert action.effective_nodejs_version(24) == 20

    def test_ignore_hint_wins_over_override(self) -> None:
        """An ignore hint disables the matching check even when an override is present."""
        action = GithubAction(
            "actions/checkout",
            "abc123",
            "v4.2.2",
            comments=[
                "v4.2.2",
                "gh-action-pulse: ignore[max-age, nodejs-version]",
                "gh-action-pulse: override[max-age=200, nodejs-version=20]",
            ],
        )

        assert action.ignores("max-age")
        assert action.override("max-age") == 200
        assert action.effective_max_age(150) == 0
        assert action.effective_nodejs_version(24) == 0

    @patch("gh_action_pulse.actions.GithubAction._set_actual_reference_type_and_date")
    @patch("gh_action_pulse.actions.GithubAction._set_actual_description_type")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date")
    def test_get_fully_qualified(
        self, mock_set_rec: MagicMock, mock_set_desc: MagicMock, mock_set_actual: MagicMock
    ) -> None:
        """Test that get_fully_qualified correctly orchestrates the internal logic to populate all fields."""
        # GIVEN
        action = GithubAction("actions/checkout", "v4")
        mock_g = MagicMock()
        mock_repo = MagicMock()
        mock_repo.archived = False
        mock_repo.full_name = "actions/checkout"
        mock_g.get_repo.return_value = mock_repo

        # WHEN
        result = action.get_fully_qualified(mock_g, 0)

        # THEN
        assert result is action
        mock_set_actual.assert_called_once()
        mock_set_desc.assert_called_once()
        mock_set_rec.assert_called_once()

    @patch("gh_action_pulse.actions.GithubAction._set_actual_reference_type_and_date")
    @patch("gh_action_pulse.actions.GithubAction._set_actual_description_type")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date")
    def test_get_fully_qualified_logs_min_age_ignore(
        self,
        mock_set_rec: MagicMock,
        mock_set_desc: MagicMock,
        mock_set_actual: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A min-age ignore hint is logged while the configured wait is still stored."""
        action = GithubAction(
            "actions/checkout",
            "v4",
            comments=["v4", "gh-action-pulse: ignore[min-age]"],
        )
        mock_g = MagicMock()
        mock_repo = MagicMock()
        mock_repo.archived = False
        mock_repo.full_name = "actions/checkout"
        mock_g.get_repo.return_value = mock_repo

        with caplog.at_level("DEBUG"):
            action.get_fully_qualified(mock_g, 30)

        assert action.min_age == 30
        assert "Skipping min-age wait for action 'actions/checkout'" in caplog.text
        mock_set_actual.assert_called_once()
        mock_set_desc.assert_called_once()
        mock_set_rec.assert_called_once()

    @patch("gh_action_pulse.actions.GithubAction._set_actual_reference_type_and_date")
    @patch("gh_action_pulse.actions.GithubAction._set_actual_description_type")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date")
    def test_get_fully_qualified_logs_min_age_override(
        self,
        mock_set_rec: MagicMock,
        mock_set_desc: MagicMock,
        mock_set_actual: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A min-age override is logged while the CLI wait is still stored."""
        action = GithubAction(
            "actions/checkout",
            "v4",
            comments=["v4", "gh-action-pulse: override[min-age=3]"],
        )
        mock_g = MagicMock()
        mock_repo = MagicMock()
        mock_repo.archived = False
        mock_repo.full_name = "actions/checkout"
        mock_g.get_repo.return_value = mock_repo

        with caplog.at_level("DEBUG"):
            action.get_fully_qualified(mock_g, 30)

        assert action.min_age == 30
        assert action.override("min-age") == 3
        assert "Using min-age override of 3 days for action 'actions/checkout'" in caplog.text
        mock_set_actual.assert_called_once()
        mock_set_desc.assert_called_once()
        mock_set_rec.assert_called_once()

    def test_get_fully_qualified_raises_for_archived_repo(self) -> None:
        """Verify that get_fully_qualified exits when the action repository is archived."""
        action = GithubAction("actions/checkout", "v4")
        mock_g = MagicMock()
        mock_repo = MagicMock()
        mock_repo.archived = True
        mock_repo.full_name = "actions/checkout"
        mock_g.get_repo.return_value = mock_repo

        with pytest.raises(GithubActionArchivedError, match=r"actions/checkout.*archived"):
            action.get_fully_qualified(mock_g, 0)

    def test_get_fully_qualified_raises_reference_not_found_for_missing_repo(self) -> None:
        """A repository that does not exist upstream is reported instead of crashing."""
        action = GithubAction("does-not/exist", "v1")
        mock_g = MagicMock()
        mock_g.get_repo.side_effect = UnknownObjectException(404, "Not Found", None)

        with pytest.raises(GithubActionReferenceNotFoundError, match=r"does-not/exist"):
            action.get_fully_qualified(mock_g, 0)

    def test_get_fully_qualified_sets_repo_canonical_name_on_repo_redirect(self) -> None:
        """Verify that get_fully_qualified records the canonical name when GitHub redirects the repo."""
        action = GithubAction("GoogleCloudPlatform/release-please-action", "v4")
        mock_g = MagicMock()
        mock_repo = MagicMock()
        mock_repo.archived = False
        mock_repo.full_name = "googleapis/release-please-action"
        mock_g.get_repo.return_value = mock_repo

        with (
            patch("gh_action_pulse.actions.GithubAction._set_actual_reference_type_and_date"),
            patch("gh_action_pulse.actions.GithubAction._set_actual_description_type"),
            patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date"),
        ):
            action.get_fully_qualified(mock_g, 0)

        assert action.recommended.repo_canonical_name == "googleapis/release-please-action"

    def test_get_fully_qualified_preserves_subpath_on_repo_redirect(self) -> None:
        """Verify that subpaths are preserved when only the owner/repo part redirects."""
        action = GithubAction("old-org/some-repo/actions/my-action", "v1")
        mock_g = MagicMock()
        mock_repo = MagicMock()
        mock_repo.archived = False
        mock_repo.full_name = "new-org/some-repo"
        mock_g.get_repo.return_value = mock_repo

        with (
            patch("gh_action_pulse.actions.GithubAction._set_actual_reference_type_and_date"),
            patch("gh_action_pulse.actions.GithubAction._set_actual_description_type"),
            patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date"),
        ):
            action.get_fully_qualified(mock_g, 0)

        assert action.recommended.repo_canonical_name == "new-org/some-repo/actions/my-action"

    @pytest.mark.parametrize(
        ("repo_canonical_name", "actual_reference", "actual_description", "recommended", "expected"),
        [
            (
                "googleapis/release-please-action",
                "abc123",
                "v4.0.0",
                ("def456", "v4.1.0"),
                "googleapis/release-please-action@def456 # v4.1.0",
            ),
            (
                "googleapis/release-please-action",
                "abc123",
                "v4.0.0",
                (None, None),
                "googleapis/release-please-action@abc123 # v4.0.0",
            ),
            (
                None,
                "abc123",
                "v4.0.0",
                ("def456", "v4.1.0"),
                "actions/checkout@def456 # v4.1.0",
            ),
            (None, "abc123", None, (None, None), None),
            (None, "abc123", "v4.0.0", ("abc123", "v4.0.0"), None),
        ],
    )
    def test_get_updated_uses_replacement(
        self,
        repo_canonical_name: str | None,
        actual_reference: str,
        actual_description: str | None,
        recommended: tuple[str | None, str | None],
        expected: str | None,
    ) -> None:
        """Verify updated uses replacement handles redirects and version updates."""
        action = GithubAction("actions/checkout", actual_reference, actual_description)
        action.recommended.repo_canonical_name = repo_canonical_name
        action.recommended.reference, action.recommended.description = recommended
        if recommended[1] is not None:
            action.recommended.comments = [recommended[1]]
        actual_comments = [actual_description] if actual_description else []

        assert action.get_updated_uses_replacement(actual_reference, actual_comments) == expected

    def test_get_updated_uses_replacement_joins_multiple_comments(self) -> None:
        """Each trailing comment is prefixed with '# ' when building uses content."""
        action = GithubAction("actions/checkout", "abc123", "v4.0.0")
        action.recommended.reference = "def456"
        action.recommended.description = "v4.1.0"
        action.recommended.comments = ["v4.1.0", "keep this", "gh-action-pulse: ignore[max-days]"]

        assert (
            action.get_updated_uses_replacement(
                "abc123",
                ["v4.0.0", "keep this", "gh-action-pulse: ignore[max-days]"],
            )
            == "actions/checkout@def456 # v4.1.0 # keep this # gh-action-pulse: ignore[max-days]"
        )

    def test__set_actual_reference_type_and_date_with_tag(self) -> None:
        """Verify that _set_actual_reference_type_and_date correctly identifies the reference type and date."""
        action = GithubAction("actions/checkout", "v4")
        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v4.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_repo.get_commit.return_value = mock_tag_v4.commit

        def get_git_ref_side_effect(ref: str) -> MagicMock:
            if ref == "heads/v4":
                raise GithubException(404, "Not Found", None)
            if ref == "tags/v4":
                return MagicMock()
            raise GithubException(404, "Not Found", None)

        mock_repo.get_git_ref.side_effect = get_git_ref_side_effect

        action._set_actual_reference_type_and_date()

        assert action.actual.reference_type == "tag"
        assert action.actual.date == datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        assert mock_repo.get_commit.call_count == 1
        mock_repo.get_commit.assert_called_once_with(sha="v4")
        mock_repo.get_git_ref.assert_any_call("heads/v4")
        mock_repo.get_git_ref.assert_any_call("tags/v4")

    def test__set_actual_reference_type_and_date_with_sha(self) -> None:
        """Verify that _set_actual_reference_type_and_date correctly identifies the reference type and date."""
        # Use a specific SHA to ensure the comparison on line 72 is True
        target_sha = "a1b2c3d4e5f6g7h8i9j0"
        action = GithubAction("actions/checkout", target_sha)
        mock_repo = MagicMock()
        mock_sha_v4 = MagicMock()
        mock_sha_v4.commit.sha = target_sha
        mock_sha_v4.commit.commit.committer.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_repo.get_commit.return_value = mock_sha_v4.commit
        action.repo = mock_repo
        mock_repo.get_git_ref.side_effect = GithubException(404, "Not Found", None)

        action._set_actual_reference_type_and_date()

        assert action.actual.reference_type == "sha"
        assert action.actual.date == datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        assert mock_repo.get_commit.call_count == 1
        mock_repo.get_commit.assert_called_once_with(sha=target_sha)
        mock_repo.get_git_ref.assert_any_call(f"heads/{target_sha}")
        mock_repo.get_git_ref.assert_any_call(f"tags/{target_sha}")

    def test__set_actual_reference_type_and_date_with_branch(self) -> None:
        """Verify that _set_actual_reference_type_and_date correctly identifies the reference type and date."""
        action = GithubAction("actions/checkout", "main")
        mock_repo = MagicMock()
        mock_branch_ref = MagicMock()
        mock_branch_ref.object.sha = "sha-for-main"
        mock_branch_commit = MagicMock()
        mock_branch_commit.commit.committer.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_repo.get_git_ref.return_value = mock_branch_ref
        mock_repo.get_commit.return_value = mock_branch_commit
        action.repo = mock_repo

        action._set_actual_reference_type_and_date()

        assert action.actual.reference_type == "branch"
        assert action.actual.date == datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_repo.get_git_ref.assert_called_once_with("heads/main")
        mock_repo.get_commit.assert_called_once_with(sha="sha-for-main")

    def test__set_actual_reference_type_and_date_with_branch_before_tag_lookup(self) -> None:
        """Branch names must stay branches even when get_commit could resolve the name."""
        action = GithubAction("actions/checkout", "main")
        mock_repo = MagicMock()
        mock_branch_ref = MagicMock()
        mock_branch_ref.object.sha = "sha-for-main"
        mock_branch_commit = MagicMock()
        mock_branch_commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        def get_git_ref_side_effect(ref: str) -> MagicMock:
            if ref == "heads/main":
                return mock_branch_ref
            raise GithubException(404, "Not Found", None)

        mock_repo.get_git_ref.side_effect = get_git_ref_side_effect
        mock_repo.get_commit.return_value = mock_branch_commit
        action.repo = mock_repo

        action._set_actual_reference_type_and_date()

        assert action.actual.reference_type == "branch"
        mock_repo.get_git_ref.assert_called_once_with("heads/main")
        mock_repo.get_commit.assert_called_once_with(sha="sha-for-main")

    def test__set_actual_reference_type_and_date_with_invalid_ref(self) -> None:
        """Verify that _set_actual_reference_type_and_date correctly handles invalid references."""
        action = GithubAction("actions/checkout", "invalid-ref")
        mock_repo = MagicMock()
        mock_repo.get_commit.side_effect = GithubException(404, "Not Found", None)
        mock_repo.get_git_ref.side_effect = GithubException(404, "Not Found", None)
        action.repo = mock_repo

        action._set_actual_reference_type_and_date()

        assert action.actual.reference_type == "bullshit"
        assert action.actual.date is None
        assert mock_repo.get_commit.call_count == 1
        mock_repo.get_commit.assert_called_once_with(sha="invalid-ref")
        mock_repo.get_git_ref.assert_any_call("heads/invalid-ref")
        mock_repo.get_git_ref.assert_any_call("tags/invalid-ref")

    def test__set_actual_description_type_with_none(self) -> None:
        """Verify that _set_actual_description_type correctly handles None description."""
        action = GithubAction("actions/checkout", "v4", None)
        mock_repo = MagicMock()

        action._set_actual_description_type()

        assert action.actual.description_type is None
        mock_repo.get_git_ref.assert_not_called()

    def test__set_actual_description_type_with_tag(self) -> None:
        """Verify that _set_actual_description_type correctly identifies a tag description."""
        action = GithubAction("actions/checkout", "v4", "v4.0.0")
        mock_repo = MagicMock()
        mock_repo.get_git_ref.return_value = MagicMock()  # Simulate tag exists
        action.repo = mock_repo

        action._set_actual_description_type()

        assert action.actual.description_type == "tag"
        mock_repo.get_git_ref.assert_called_once_with("tags/v4.0.0")

    def test__set_actual_description_type_with_branch(self) -> None:
        """Verify that _set_actual_description_type correctly identifies a branch description."""
        action = GithubAction("actions/checkout", "v4", "main")
        mock_repo = MagicMock()
        mock_repo.get_git_ref.return_value = MagicMock()  # Simulate branch exists
        mock_repo.get_git_ref.side_effect = [
            GithubException(404, "Not Found", None),
            mock_repo.get_git_ref.return_value,
        ]
        action.repo = mock_repo

        action._set_actual_description_type()

        assert action.actual.description_type == "branch"
        assert mock_repo.get_git_ref.call_count == 2
        mock_repo.get_git_ref.assert_any_call("tags/main")
        mock_repo.get_git_ref.assert_any_call("heads/main")

    def test__set_actual_description_type_with_invalid_ref(self) -> None:
        """Verify that _set_actual_description_type correctly handles invalid description references."""
        action = GithubAction("actions/checkout", "v4", "invalid-desc")
        mock_repo = MagicMock()
        mock_repo.get_git_ref.side_effect = GithubException(404, "Not Found", None)
        action.repo = mock_repo

        action._set_actual_description_type()

        assert action.actual.description_type == "bullshit"
        assert mock_repo.get_git_ref.call_count == 2
        mock_repo.get_git_ref.assert_any_call("tags/invalid-desc")
        mock_repo.get_git_ref.assert_any_call("heads/invalid-desc")

    @patch("gh_action_pulse.actions.GithubAction._get_version_tags")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    def test__set_recommended_reference_and_date_tag(
        self,
        mock__set_recommended_reference_and_date_to_tag_if_exists: MagicMock,
        mock__get_version_tags: MagicMock,
    ) -> None:
        """Verify that _set_recommended_reference_and_date calls the correct method when reference is a tag."""
        action = GithubAction("actions/checkout", "v4")
        action.actual.reference_type = "tag"
        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v6 = MagicMock()
        mock__get_version_tags.return_value = [mock_tag_v6, mock_tag_v4]
        mock_valid_semver_tags = mock__get_version_tags.return_value

        def set_recommendation(_tags: list) -> None:
            action.recommended.description = "v6.0.0"

        mock__set_recommended_reference_and_date_to_tag_if_exists.side_effect = set_recommendation

        action._set_recommended_reference_and_date()

        mock__get_version_tags.assert_called_once_with()
        mock__set_recommended_reference_and_date_to_tag_if_exists.assert_called_once_with(mock_valid_semver_tags)

    @patch("gh_action_pulse.actions.GithubAction._get_version_tags")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_with_fallback")
    def test__set_recommended_reference_and_date_branch(
        self,
        mock__set_recommended_with_fallback: MagicMock,
        mock__get_version_tags: MagicMock,
    ) -> None:
        """Verify that _set_recommended_reference_and_date calls the correct method when reference is a branch."""
        action = GithubAction("actions/checkout", "main")
        action.actual.reference_type = "branch"
        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v6 = MagicMock()
        mock__get_version_tags.return_value = [mock_tag_v6, mock_tag_v4]
        mock_valid_semver_tags = mock__get_version_tags.return_value

        def set_recommendation(_tags: list, _branch_name: str) -> None:
            action.recommended.description = "main"

        mock__set_recommended_with_fallback.side_effect = set_recommendation

        action._set_recommended_reference_and_date()

        mock__get_version_tags.assert_called_once_with()
        mock__set_recommended_with_fallback.assert_called_once_with(mock_valid_semver_tags, "main")

    @patch("gh_action_pulse.actions.GithubAction._get_version_tags")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_for_sha")
    def test__set_recommended_reference_and_date_sha(
        self,
        mock__set_recommended_for_sha: MagicMock,
        mock__get_version_tags: MagicMock,
    ) -> None:
        """Check that _set_recommended_reference_and_date calls the correct method when reference is a sha."""
        action = GithubAction("actions/checkout", "sha-for-v4", "v4.0.0")
        action.actual.reference_type = "sha"
        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v6 = MagicMock()
        mock__get_version_tags.return_value = [mock_tag_v6, mock_tag_v4]
        mock_valid_semver_tags = mock__get_version_tags.return_value

        def set_recommendation(_tags: list) -> None:
            action.recommended.description = "v4.0.0"

        mock__set_recommended_for_sha.side_effect = set_recommendation

        action._set_recommended_reference_and_date()

        mock__get_version_tags.assert_called_once_with()
        mock__set_recommended_for_sha.assert_called_once_with(mock_valid_semver_tags)

    @patch("gh_action_pulse.actions.GithubAction._get_version_tags")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_for_sha")
    def test__set_recommended_reference_and_date_does_not_mutate_actual_comments(
        self,
        mock__set_recommended_for_sha: MagicMock,
        mock__get_version_tags: MagicMock,
    ) -> None:
        """Updating the version comment must not rewrite the original comments used for lookup."""
        original_comments = ["v5.0.0", "gh-action-pulse: ignore[max-days]"]
        action = GithubAction(
            "crazy-max/ghaction-github-labeler",
            "548a7c3603594ec17c819e1239f281a3b801ab4d",
            "v5.0.0",
            comments=original_comments,
        )
        action.actual.reference_type = "sha"
        action.actual.description_type = "tag"
        mock__get_version_tags.return_value = []

        def set_recommendation(_tags: list) -> None:
            action.recommended.reference = "548a7c3603594ec17c819e1239f281a3b801ab4d"
            action.recommended.description = "v6.0.0"

        mock__set_recommended_for_sha.side_effect = set_recommendation

        action._set_recommended_reference_and_date()

        assert action.actual.comments == ["v5.0.0", "gh-action-pulse: ignore[max-days]"]
        assert original_comments == ["v5.0.0", "gh-action-pulse: ignore[max-days]"]
        assert action.recommended.comments == ["v6.0.0", "gh-action-pulse: ignore[max-days]"]

    @patch("gh_action_pulse.actions.GithubAction._get_version_tags")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_for_sha")
    def test__set_recommended_reference_and_date_inserts_description_before_annotation(
        self,
        mock__set_recommended_for_sha: MagicMock,
        mock__get_version_tags: MagicMock,
    ) -> None:
        """A non-tag first comment is kept and the recommended description is inserted in front."""
        action = GithubAction(
            "actions/checkout",
            "abc123",
            "gh-action-pulse: ignore[max-days]",
            comments=["gh-action-pulse: ignore[max-days]"],
        )
        action.actual.reference_type = "sha"
        action.actual.description_type = "bullshit"
        mock__get_version_tags.return_value = []

        def set_recommendation(_tags: list) -> None:
            action.recommended.reference = "def456"
            action.recommended.description = "v4.2.0"

        mock__set_recommended_for_sha.side_effect = set_recommendation

        action._set_recommended_reference_and_date()

        assert action.actual.comments == ["gh-action-pulse: ignore[max-days]"]
        assert action.recommended.comments == ["v4.2.0", "gh-action-pulse: ignore[max-days]"]

    @pytest.mark.usefixtures("_no_version_tags")
    def test__set_recommended_reference_and_date_bullshit_raises_reference_not_found(self) -> None:
        """A reference that exists neither as branch, tag nor commit raises a descriptive error."""
        action = GithubAction("actions/checkout", "v4-typo")
        action.actual.reference_type = "bullshit"

        with pytest.raises(GithubActionReferenceNotFoundError) as exc_info:
            action._set_recommended_reference_and_date()

        assert exc_info.value.name == "actions/checkout"
        assert exc_info.value.reference == "v4-typo"
        assert "Reference 'v4-typo' of action 'actions/checkout' does not exist upstream" in str(exc_info.value)

    @pytest.mark.parametrize(
        ("reference_type", "error_message"),
        [
            (None, "Unknown reference type encountered, that should not happen."),
        ],
    )
    @log_capture()
    @patch("gh_action_pulse.actions.GithubAction._get_version_tags")
    def test__set_recommended_reference_and_date_bullshit(
        self,
        mock__get_version_tags: MagicMock,
        capture: LogCapture,
        reference_type: Literal["bullshit", "sha", "tag", "branch"] | None,
        error_message: str,
    ) -> None:
        """Check that _set_recommended_reference_and_date calls the correct method when reference is bullshit."""
        action = GithubAction("actions/checkout", "sha-for-main", "main")
        action.actual.reference_type = reference_type
        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v6 = MagicMock()
        mock__get_version_tags.return_value = [mock_tag_v6, mock_tag_v4]

        with pytest.raises(SystemExit):
            action._set_recommended_reference_and_date()

        mock__get_version_tags.assert_called_once_with()
        capture.check(("gh_action_pulse.actions", "ERROR", error_message))

    def test__get_version_tags(self, create_mock_tag: Callable[..., MagicMock]) -> None:  # pylint: disable=redefined-outer-name
        """Verify that _get_version_tags correctly filters and sorts tags based on semantic versioning."""
        action = GithubAction("actions/checkout", "sha-for-main", "main")
        mock_repo = MagicMock()

        tags = [
            create_mock_tag("v4.0.0"),
            create_mock_tag("v4.0.1"),
            create_mock_tag("v4.0.2"),
            create_mock_tag("v5.0.0"),
            create_mock_tag("not-a-semver"),
            create_mock_tag("v6.0.0-alpha1"),
            create_mock_tag("v6.0.0"),
        ]
        mock_repo.get_tags.return_value = tags
        action.repo = mock_repo
        expected_names = ["v6.0.0", "v6.0.0-alpha1", "v5.0.0", "v4.0.2", "v4.0.1", "v4.0.0"]

        results = action._get_version_tags()

        assert [tag.name for tag in results] == expected_names

    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    def test__set_recommended_for_sha_when_description_is_tag(
        self,
        mock__set_recommended_reference_and_date_to_tag_if_exists: MagicMock,
    ) -> None:
        """Verify that _set_recommended_for_sha works correctly when the description is a tag."""
        action = GithubAction("actions/checkout", "sha-for-main", "tag")
        mock_repo = MagicMock()
        action.repo = mock_repo
        action.actual.description_type = "tag"
        mock_valid_semver_tags = [MagicMock(), MagicMock()]

        action._set_recommended_for_sha(mock_valid_semver_tags)

        mock__set_recommended_reference_and_date_to_tag_if_exists.assert_called_once_with(mock_valid_semver_tags)

    @patch("gh_action_pulse.actions.GithubAction._set_recommended_with_fallback")
    def test__set_recommended_for_sha_when_description_is_branch(
        self, mock__set_recommended_with_fallback: MagicMock
    ) -> None:
        """Verify that _set_recommended_for_sha works correctly when the description is a branch."""
        action = GithubAction("actions/checkout", "sha-for-main", "main")
        mock_repo = MagicMock()
        action.actual.description_type = "branch"
        action.repo = mock_repo
        mock_valid_semver_tags = [MagicMock(), MagicMock()]

        action._set_recommended_for_sha(mock_valid_semver_tags)

        mock__set_recommended_with_fallback.assert_called_once_with(mock_valid_semver_tags, "main")

    @patch("gh_action_pulse.actions.GithubAction._actual_sha_matches_tag")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_to_latest_related_branch")
    def test__set_recommended_for_sha_when_description_is_bullshit_or_none_and_sha_is_tag_related(
        self,
        mock__set_recommended_to_latest_related_branch: MagicMock,
        mock__set_recommended_reference_and_date_to_tag_if_exists: MagicMock,
        mock__actual_sha_matches_tag: MagicMock,
    ) -> None:
        """Verify that _set_recommended_for_sha works correctly when the description is bullshit or None."""
        action = GithubAction("actions/checkout", "sha-for-main", "main")
        mock_repo = MagicMock()
        action.repo = mock_repo
        action.actual.description_type = "bullshit"
        mock_valid_semver_tags = [MagicMock(), MagicMock()]
        mock__actual_sha_matches_tag.return_value = True

        def set_tag_recommendation(_valid_semver_tags: list) -> None:
            action.recommended.reference = "sha-for-v6"

        mock__set_recommended_reference_and_date_to_tag_if_exists.side_effect = set_tag_recommendation

        action._set_recommended_for_sha(mock_valid_semver_tags)

        mock__set_recommended_reference_and_date_to_tag_if_exists.assert_called_once_with(mock_valid_semver_tags)
        mock__set_recommended_to_latest_related_branch.assert_not_called()

    @patch("gh_action_pulse.actions.GithubAction._actual_sha_matches_tag")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_to_latest_related_branch")
    def test__set_recommended_for_sha_when_description_is_bullshit_or_none_and_sha_is_not_tag_related(
        self,
        mock__set_recommended_to_latest_related_branch: MagicMock,
        mock__set_recommended_reference_and_date_to_tag_if_exists: MagicMock,
        mock__actual_sha_matches_tag: MagicMock,
    ) -> None:
        """Verify that _set_recommended_for_sha works correctly when the description is bullshit or None."""
        action = GithubAction("actions/checkout", "sha-for-main", "main")
        mock_repo = MagicMock()
        action.repo = mock_repo
        action.actual.description_type = "bullshit"
        mock_valid_semver_tags = [MagicMock(), MagicMock()]
        mock__actual_sha_matches_tag.return_value = False
        action.recommended.reference = None

        action._set_recommended_for_sha(mock_valid_semver_tags)

        mock__set_recommended_reference_and_date_to_tag_if_exists.assert_not_called()
        mock__set_recommended_to_latest_related_branch.assert_called_once_with()

    def test__set_recommended_for_sha_tag_related_without_eligible_tag_does_not_fallback(self) -> None:
        """Tag-related SHAs must not fall back to a branch when no semver tag is eligible."""
        action = GithubAction("actions/checkout", "sha-for-v4")
        action.actual.description_type = None
        action.recommended.reference = None

        with (
            patch("gh_action_pulse.actions.GithubAction._actual_sha_matches_tag", return_value=True),
            patch(
                "gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists"
            ) as mock_set_tag,
            patch("gh_action_pulse.actions.GithubAction._set_recommended_to_latest_related_branch") as mock_set_branch,
        ):
            action._set_recommended_for_sha([])

        mock_set_tag.assert_called_once_with([])
        mock_set_branch.assert_not_called()

    def test__actual_sha_matches_tag(self) -> None:
        """Verify that _actual_sha_matches_tag correctly identifies when the actual sha matches a tag."""
        action = GithubAction("actions/checkout", "sha-for-v4", "v4.0.0")
        action.actual.reference_type = "sha"
        mock_repo = MagicMock()
        mock_tag_v4 = MagicMock()
        mock_tag_v4.commit.sha = "sha-for-v4"
        mock_tag_v6 = MagicMock()
        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_repo.get_tags.return_value = [mock_tag_v4, mock_tag_v6]
        mock_repo.get_commit.return_value = MagicMock(commit=MagicMock(sha="sha-for-v4"))
        action.repo = mock_repo

        result = action._actual_sha_matches_tag()

        assert result is True
        mock_repo.get_commit.assert_called_once_with(sha="sha-for-v4")

    def test__actual_sha_matches_tag_with_short_sha(self) -> None:
        """Short SHAs must be resolved before comparing against tag commit SHAs."""
        full_sha = "abcdef0123456789abcdef0123456789abcdef0"
        short_sha = full_sha[:7]
        action = GithubAction("actions/checkout", short_sha)
        action.actual.reference_type = "sha"
        mock_repo = MagicMock()
        mock_repo.get_commit.return_value = MagicMock(commit=MagicMock(sha=full_sha))
        mock_tag = MagicMock()
        mock_tag.commit.sha = full_sha
        mock_repo.get_tags.return_value = [mock_tag]
        action.repo = mock_repo

        assert action._actual_sha_matches_tag() is True

    def test__actual_sha_matches_tag_returns_false_for_non_sha_reference(self) -> None:
        """Tag-related detection only applies when the pinned reference itself is a SHA."""
        action = GithubAction("actions/checkout", "main")
        action.actual.reference_type = "branch"
        mock_repo = MagicMock()
        mock_repo.get_tags.return_value = [MagicMock(commit=MagicMock(commit=MagicMock(sha="sha-for-main")))]
        action.repo = mock_repo

        assert action._actual_sha_matches_tag() is False
        mock_repo.get_commit.assert_not_called()

    def test__actual_recommended_to_branch(self) -> None:
        """Checks that _set_recommended_to_branch sets the recommended reference and date."""
        action = GithubAction("actions/checkout", "sha-for-main-old", "main")
        mock_repo = MagicMock()
        mock_branch = MagicMock()
        mock_branch.commit.sha = "sha-for-main"
        mock_branch.commit.commit.committer.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_repo.get_branch.return_value = mock_branch
        action.repo = mock_repo

        action._set_recommended_to_branch("main")

        assert action.recommended.reference == "sha-for-main"
        assert action.recommended.date == datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        assert action.recommended.description == "main"

    @log_capture()
    def test__set_recommended_to_branch_with_exception(self, capture: LogCapture) -> None:
        """Checks that _set_recommended_to_branch handles exceptions when fetching a branch."""
        action = GithubAction("actions/checkout", "sha-for-main-old", "main")
        mock_repo = MagicMock()
        mock_repo.get_branch.side_effect = GithubException(404, "Not Found", None)
        action.repo = mock_repo

        action._set_recommended_to_branch("main")

        capture.check(("gh_action_pulse.actions", "ERROR", "Failed to fetch branch 'main', that should not happen."))

    def test__set_recommended_to_latest_related_branch_picks_newest_tip(self) -> None:
        """Checks that the newest branch tip is recommended among branches containing the SHA."""
        action = GithubAction("actions/checkout", "sha-for-main-old", None)
        mock_repo = MagicMock()
        mock_main = MagicMock()
        mock_main.name = "main"
        mock_main.commit.sha = "sha-for-main-new"
        mock_main.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)
        mock_develop = MagicMock()
        mock_develop.name = "develop"
        mock_develop.commit.sha = "sha-for-develop"
        mock_develop.commit.commit.committer.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_repo.get_branches.return_value = [mock_main, mock_develop]
        mock_repo.get_branch.return_value = mock_main

        def compare_side_effect(_base: str, head: str) -> MagicMock:
            comparison = MagicMock()
            comparison.status = "ahead" if head in {"sha-for-main-new", "sha-for-develop"} else "diverged"
            return comparison

        mock_repo.compare.side_effect = compare_side_effect
        action.repo = mock_repo

        action._set_recommended_to_latest_related_branch()

        assert action.recommended.reference == "sha-for-main-new"
        assert action.recommended.description == "main"
        mock_repo.get_branch.assert_called_once_with("main")

    @log_capture()
    def test__set_recommended_to_latest_related_branch_with_no_matches(self, capture: LogCapture) -> None:
        """Checks that a warning is logged when no branch contains the pinned SHA."""
        action = GithubAction("actions/checkout", "sha-for-main-old", None)
        mock_repo = MagicMock()
        mock_branch = MagicMock()
        mock_branch.name = "main"
        mock_branch.commit.sha = "sha-for-main-new"
        mock_repo.get_branches.return_value = [mock_branch]
        mock_repo.compare.return_value = MagicMock(status="diverged")
        action.repo = mock_repo

        action._set_recommended_to_latest_related_branch()

        assert action.recommended.reference is None
        capture.check(
            (
                "gh_action_pulse.actions",
                "WARNING",
                "No branch found containing commit 'sha-for-main-old' for action 'actions/checkout'.",
            )
        )

    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_to_branch")
    def test__set_recommended_reference_with_fallback_recommend_date_none(
        self,
        mock__set_recommended_to_branch: MagicMock,
        mock__set_recommended_reference_and_date_to_tag_if_exists: MagicMock,
    ) -> None:
        """Checks that _set_recommended_with_fallback sets the recommended reference and date based."""
        action = GithubAction("actions/checkout", "sha-for-main-old", "main")
        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v6 = MagicMock()
        action.recommended.date = None

        action._set_recommended_with_fallback([mock_tag_v6], "main")

        mock__set_recommended_reference_and_date_to_tag_if_exists.assert_called_once_with([mock_tag_v6])
        mock__set_recommended_to_branch.assert_called_once_with("main")

    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_to_branch")
    def test__set_recommended_reference_with_fallback_tag_is_newer(
        self,
        mock__set_recommended_to_branch: MagicMock,
        mock__set_recommended_reference_and_date_to_tag_if_exists: MagicMock,
    ) -> None:
        """Checks that _set_recommended_with_fallback sets the recommended reference and date."""
        action = GithubAction("actions/checkout", "sha-for-main-old", "main")

        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v6 = MagicMock()
        mock_tag_v6.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)
        action.actual.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        action.recommended.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_with_fallback([mock_tag_v6], "main")

        mock__set_recommended_reference_and_date_to_tag_if_exists.assert_called_once_with([mock_tag_v6])
        mock__set_recommended_to_branch.assert_not_called()

    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_to_branch")
    def test__set_recommended_reference_with_fallback_tag_is_older(
        self,
        mock__set_recommended_to_branch: MagicMock,
        mock__set_recommended_reference_and_date_to_tag_if_exists: MagicMock,
    ) -> None:
        """Branch tips newer than the latest eligible tag should keep the branch recommendation."""
        action = GithubAction("actions/checkout", "main")
        action.actual.date = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
        action.recommended.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_tag_v6 = MagicMock()

        action._set_recommended_with_fallback([mock_tag_v6], "main")

        mock__set_recommended_reference_and_date_to_tag_if_exists.assert_called_once_with([mock_tag_v6])
        mock__set_recommended_to_branch.assert_called_once_with("main")

    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_to_branch")
    def test__set_recommended_reference_with_fallback_tag_same_date_as_branch(
        self,
        mock__set_recommended_to_branch: MagicMock,
        mock__set_recommended_reference_and_date_to_tag_if_exists: MagicMock,
    ) -> None:
        """Equal tag and branch dates should prefer the tag annotation over the branch name."""
        action = GithubAction("actions/checkout", "main")
        same_date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)
        action.actual.date = same_date
        action.recommended.date = same_date
        mock_tag_v6 = MagicMock()

        action._set_recommended_with_fallback([mock_tag_v6], "main")

        mock__set_recommended_reference_and_date_to_tag_if_exists.assert_called_once_with([mock_tag_v6])
        mock__set_recommended_to_branch.assert_not_called()

    def test__set_recommended_reference_and_date_to_tag_if_exists_with_valid_tags(self) -> None:
        """Checks that _set_recommended_reference_and_date_to_tag_if_exists sets the recommended ref and date."""
        action = GithubAction("actions/checkout", "sha-for-main-old", "main")
        action.min_age = 0
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_tag_v6.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date_to_tag_if_exists([mock_tag_v6, mock_tag_v4])

        assert action.recommended.reference == "sha-for-v6"
        assert action.recommended.date == datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)
        assert action.recommended.description == "v6.0.0"

    def test__set_recommended_reference_and_date_to_tag_if_exists_with_no_tags(self) -> None:
        """Checks that _set_recommended_reference_and_date_to_tag_if_exists sets the recommended ref and date."""
        action = GithubAction("actions/checkout", "sha-for-main-old", "main")
        action.min_age = 0

        action._set_recommended_reference_and_date_to_tag_if_exists([])

    def test__set_recommended_reference_and_date_to_tag_if_exists_with_newer_tag(self) -> None:
        """Checks that tags newer than the min_age cutoff are not recommended when no version is pinned."""
        action = GithubAction("actions/checkout", "sha-for-main-old", "main")
        action.min_age = 30
        now = datetime.datetime.now(datetime.UTC)
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_tag_v6.commit.commit.committer.date = now - datetime.timedelta(days=29)
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v4.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date_to_tag_if_exists([mock_tag_v6, mock_tag_v4])

        assert action.recommended.reference == "sha-for-v4"
        assert action.recommended.date == datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)
        assert action.recommended.description == "v4.0.0"

    def test__set_recommended_reference_and_date_to_tag_if_exists_honors_min_age_ignore_hint(self) -> None:
        """Ignoring min-age selects a tag younger than the configured wait."""
        action = GithubAction(
            "actions/checkout",
            "sha-for-main-old",
            "main",
            comments=["main", "gh-action-pulse: ignore[min-age]"],
        )
        action.min_age = 30
        now = datetime.datetime.now(datetime.UTC)
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_tag_v6.commit.commit.committer.date = now - datetime.timedelta(days=29)
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v4.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date_to_tag_if_exists([mock_tag_v6, mock_tag_v4])

        assert action.recommended.reference == "sha-for-v6"
        assert action.recommended.description == "v6.0.0"

    def test__set_recommended_reference_and_date_to_tag_if_exists_honors_min_age_override(self) -> None:
        """A min-age override selects a tag that is old enough for the override but not the CLI wait."""
        action = GithubAction(
            "actions/checkout",
            "sha-for-main-old",
            "main",
            comments=["main", "gh-action-pulse: override[min-age=7]"],
        )
        action.min_age = 30
        now = datetime.datetime.now(datetime.UTC)
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_tag_v6.commit.commit.committer.date = now - datetime.timedelta(days=10)
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v4.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date_to_tag_if_exists([mock_tag_v6, mock_tag_v4])

        assert action.recommended.reference == "sha-for-v6"
        assert action.recommended.description == "v6.0.0"

    def test__set_recommended_reference_and_date_to_tag_if_exists_min_age_ignore_upgrades_too_new_tag(self) -> None:
        """Ignoring min-age upgrades to the newest tag even when it is younger than the wait."""
        action = GithubAction(
            "actions/checkout",
            "v6.0.0",
            comments=["v6.0.0", "gh-action-pulse: ignore[min-age]"],
        )
        action.actual.reference_type = "tag"
        action.min_age = 30
        now = datetime.datetime.now(datetime.UTC)
        mock_tag_v7 = MagicMock()
        mock_tag_v7.name = "v7.0.0"
        mock_tag_v7.commit.sha = "sha-for-v7"
        mock_tag_v7.commit.commit.committer.date = now - datetime.timedelta(days=5)
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_tag_v6.commit.commit.committer.date = now - datetime.timedelta(days=29)
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v4.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date_to_tag_if_exists([mock_tag_v7, mock_tag_v6, mock_tag_v4])

        assert action.recommended.reference == "sha-for-v7"
        assert action.recommended.description == "v7.0.0"

    def test__set_recommended_reference_and_date_to_tag_if_exists_does_not_downgrade_tag_reference(self) -> None:
        """Pinned tag references must not downgrade when only older tags meet min_age."""
        action = GithubAction("actions/checkout", "v6.0.0")
        action.actual.reference_type = "tag"
        action.min_age = 30
        now = datetime.datetime.now(datetime.UTC)
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_tag_v6.commit.commit.committer.date = now - datetime.timedelta(days=29)
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v4.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date_to_tag_if_exists([mock_tag_v6, mock_tag_v4])

        assert action.recommended.reference == "sha-for-v6"
        assert action.recommended.description == "v6.0.0"
        assert action.min_age_tag_date is None

    def test__set_recommended_reference_and_date_to_tag_if_exists_does_not_downgrade_tag_comment(self) -> None:
        """Pinned tag comments must not downgrade when only older tags meet min_age."""
        action = GithubAction("actions/checkout", "abc123", "v6.0.0")
        action.actual.reference_type = "sha"
        action.actual.description_type = "tag"
        action.min_age = 30
        now = datetime.datetime.now(datetime.UTC)
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_tag_v6.commit.commit.committer.date = now - datetime.timedelta(days=29)
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v4.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date_to_tag_if_exists([mock_tag_v6, mock_tag_v4])

        assert action.recommended.reference == "sha-for-v6"
        assert action.recommended.description == "v6.0.0"
        assert action.min_age_tag_date is None

    def test__set_recommended_reference_and_date_to_tag_if_exists_keeps_pinned_too_new_tag(self) -> None:
        """When pinned to a too-new tag, keep it instead of downgrading or upgrading to another too-new tag."""
        action = GithubAction("actions/checkout", "v6.0.0")
        action.actual.reference_type = "tag"
        action.min_age = 30
        now = datetime.datetime.now(datetime.UTC)
        mock_tag_v7 = MagicMock()
        mock_tag_v7.name = "v7.0.0"
        mock_tag_v7.commit.sha = "sha-for-v7"
        mock_tag_v7.commit.commit.committer.date = now - datetime.timedelta(days=5)
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_tag_v6.commit.commit.committer.date = now - datetime.timedelta(days=29)
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v4.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date_to_tag_if_exists([mock_tag_v7, mock_tag_v6, mock_tag_v4])

        assert action.recommended.reference == "sha-for-v6"
        assert action.recommended.description == "v6.0.0"
        assert action.min_age_tag_date is None

    def test__set_recommended_reference_and_date_to_tag_if_exists_upgrades_when_min_age_met(self) -> None:
        """Min-age eligible upgrades above the pinned version should still be recommended."""
        action = GithubAction("actions/checkout", "v4.0.0")
        action.actual.reference_type = "tag"
        action.min_age = 30
        now = datetime.datetime.now(datetime.UTC)
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_tag_v6.commit.commit.committer.date = now - datetime.timedelta(days=60)
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v4.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date_to_tag_if_exists([mock_tag_v6, mock_tag_v4])

        assert action.recommended.reference == "sha-for-v6"
        assert action.recommended.description == "v6.0.0"
        assert action.min_age_tag_date == mock_tag_v6.commit.commit.committer.date

    def test__get_version_tags_sets_has_version_tags(self) -> None:
        """Verify that _get_version_tags records whether semver tags exist."""
        action = GithubAction("actions/checkout", "v4")
        mock_repo = MagicMock()
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_repo.get_tags.return_value = [mock_tag_v4, mock_tag_v6]
        action.repo = mock_repo

        action._get_version_tags()

        assert action.has_version_tags is True

    def test__get_version_tags_clears_has_version_tags_when_empty(self) -> None:
        """Verify that _get_version_tags clears has_version_tags when no semver tags exist."""
        action = GithubAction("actions/checkout", "v4")
        mock_repo = MagicMock()
        mock_repo.get_tags.return_value = []
        action.repo = mock_repo

        action._get_version_tags()

        assert action.has_version_tags is False

    def test__set_recommended_reference_and_date_to_tag_if_exists_sets_min_age_tag_date(self) -> None:
        """Verify that the min-age eligible tag date is stored for freshness checks."""
        action = GithubAction("actions/checkout", "sha-for-main-old", "main")
        action.min_age = 0
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_tag_v6.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date_to_tag_if_exists([mock_tag_v6])

        assert action.min_age_tag_date == datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

    def test_is_tag_fresh_when_within_limit(self) -> None:
        """Verify is_tag_fresh returns True when the min-age eligible tag is within the allowed age."""
        action = GithubAction("actions/checkout", "v4")
        action.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=10)

        assert action.is_tag_fresh(150) is True

    def test_is_tag_fresh_when_too_old(self) -> None:
        """Verify is_tag_fresh returns False when the min-age eligible tag exceeds the allowed age."""
        action = GithubAction("actions/checkout", "v4")
        action.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=151)

        assert action.is_tag_fresh(150) is False

    def test_is_tag_fresh_when_all_tags_are_too_new_for_min_age(self) -> None:
        """Verify is_tag_fresh returns True when semver tags exist but none meet min-age yet."""
        action = GithubAction("actions/checkout", "v4")
        action.has_version_tags = True
        action.min_age_tag_date = None

        assert action.is_tag_fresh(150) is True

    def test_is_tag_fresh_when_no_semver_tags(self) -> None:
        """Verify is_tag_fresh returns False when no semver tags exist."""
        action = GithubAction("actions/checkout", "v4")
        action.has_version_tags = False
        action.min_age_tag_date = None

        assert action.is_tag_fresh(150) is False

    @patch("gh_action_pulse.actions.GithubAction._set_recommended_with_fallback")
    def test__set_recommended_for_sha_branch_without_description_is_skipped(
        self, mock__set_recommended_with_fallback: MagicMock
    ) -> None:
        """A SHA described as a branch without a name cannot fall back to a branch tip."""
        action = GithubAction("actions/checkout", "sha-for-main")
        action.actual.description_type = "branch"

        action._set_recommended_for_sha([])

        mock__set_recommended_with_fallback.assert_not_called()
        assert action.recommended.reference is None

    def test__actual_sha_matches_tag_returns_false_when_commit_lookup_fails(self) -> None:
        """Unresolved SHAs are not treated as tag-related."""
        action = GithubAction("actions/checkout", "deadbeef")
        action.actual.reference_type = "sha"
        mock_repo = MagicMock()
        mock_repo.get_commit.side_effect = GithubException(404, "Not Found", None)
        action.repo = mock_repo

        assert action._actual_sha_matches_tag() is False
        mock_repo.get_tags.assert_not_called()

    def test__set_recommended_to_latest_related_branch_skips_uncomparable_branches(self) -> None:
        """Branches that cannot be compared against the pinned SHA are ignored."""
        action = GithubAction("actions/checkout", "sha-old")
        mock_repo = MagicMock()
        mock_ok = MagicMock()
        mock_ok.name = "main"
        mock_ok.commit.sha = "sha-new"
        mock_ok.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)
        mock_bad = MagicMock()
        mock_bad.name = "broken"
        mock_bad.commit.sha = "sha-broken"
        mock_repo.get_branches.return_value = [mock_bad, mock_ok]
        mock_repo.get_branch.return_value = mock_ok

        def compare_side_effect(_base: str, head: str) -> MagicMock:
            if head == "sha-broken":
                raise GithubException(404, "Not Found", None)
            comparison = MagicMock()
            comparison.status = "identical"
            return comparison

        mock_repo.compare.side_effect = compare_side_effect
        action.repo = mock_repo

        action._set_recommended_to_latest_related_branch()

        assert action.recommended.description == "main"
        mock_repo.get_branch.assert_called_once_with("main")

    @log_capture()
    def test__set_recommended_to_latest_related_branch_with_repo_error(self, capture: LogCapture) -> None:
        """A repository-level branch listing failure is logged without a recommendation."""
        action = GithubAction("actions/checkout", "sha-old")
        mock_repo = MagicMock()
        mock_repo.get_branches.side_effect = GithubException(500, "Boom", None)
        action.repo = mock_repo

        action._set_recommended_to_latest_related_branch()

        assert action.recommended.reference is None
        capture.check(
            (
                "gh_action_pulse.actions",
                "ERROR",
                "Failed to find branches related to commit 'sha-old' for action 'actions/checkout'.",
            )
        )

    def test__set_recommended_reference_and_date_to_tag_if_exists_unknown_pinned_version(self) -> None:
        """A pinned semver that is missing from the tag list does not force a recommendation."""
        action = GithubAction("actions/checkout", "v9.0.0")
        action.actual.reference_type = "tag"
        action.min_age = 30
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v4.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date_to_tag_if_exists([mock_tag_v4])

        assert action.recommended.reference is None


OLD_DATE = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)


def _make_repo(
    tags: dict[str, str],
    branches: dict[str, str] | None = None,
    dates: dict[str, datetime.datetime] | None = None,
) -> MagicMock:
    """Build a fake repository from tag -> sha and branch -> sha mappings."""
    branches = branches or {}
    dates = dates or {}

    def make_commit(sha: str) -> MagicMock:
        commit = MagicMock()
        commit.sha = sha
        commit.commit.sha = sha
        commit.commit.committer.date = dates.get(sha, OLD_DATE)
        return commit

    def make_tag(name: str, sha: str) -> MagicMock:
        tag = MagicMock()
        tag.name = name
        tag.commit = make_commit(sha)
        return tag

    def get_commit(sha: str) -> MagicMock:
        resolved = tags.get(sha) or branches.get(sha)
        if resolved is None and sha in set(tags.values()) | set(branches.values()) | set(dates):
            resolved = sha
        if resolved is None:
            raise GithubException(404, "Not Found")
        return make_commit(resolved)

    def get_branch(name: str) -> MagicMock:
        if name not in branches:
            raise GithubException(404, "Not Found")
        branch = MagicMock()
        branch.name = name
        branch.commit = make_commit(branches[name])
        return branch

    repo = MagicMock()
    repo.get_tags.return_value = [make_tag(name, sha) for name, sha in tags.items()]
    repo.get_commit.side_effect = get_commit
    repo.get_branch.side_effect = get_branch
    repo.get_branches.return_value = [get_branch(name) for name in branches]
    repo.compare.side_effect = GithubException(404, "Not Found")
    return repo


def _recommend(action: GithubAction, repo: MagicMock, min_age: int = 0) -> GithubAction:
    action.repo = repo
    action.min_age = min_age
    action._set_recommended_reference_and_date()
    return action


class TestDegradedRecommendations:
    """Recommendations when the repository has no usable SemVer tag (issue #176)."""

    PACKAGECLOUD_TAGS: ClassVar[dict[str, str]] = {"v0.9": "sha-09", "v0.6": "sha-06", "v0.5": "sha-05"}

    def test_parse_version_tag_loose_scheme(self) -> None:
        """Loose versions accept one to three numeric components and a prerelease suffix."""
        assert str(parse_version_tag("v0.6", "loose")) == "0.6.0"
        assert str(parse_version_tag("V1", "loose")) == "1.0.0"
        assert str(parse_version_tag("2-beta.1", "loose")) == "2.0.0-beta.1"
        assert parse_version_tag("v1.2.3.4", "loose") is None
        assert parse_version_tag("latest", "loose") is None
        assert parse_version_tag("v0.6", "semver") is None

    def test_parse_tag_version_rejects_non_version_tag(self) -> None:
        """Only tags returned by _get_version_tags may be parsed as versions."""
        action = GithubAction("org/action", "v1")
        tag = MagicMock()
        tag.name = "latest"

        with pytest.raises(ValueError, match="is not a version tag"):
            action._parse_tag_version(tag)

    def test_sha_with_non_semver_tag_comment_upgrades_to_newest_loose_tag(self) -> None:
        """The issue case: @sha # v0.6 on a repo with only vX.Y tags no longer crashes."""
        action = GithubAction("computology/packagecloud-github-action", "sha-06", "v0.6", comments=["v0.6"])
        action.actual.reference_type = "sha"
        action.actual.description_type = "tag"

        _recommend(action, _make_repo(self.PACKAGECLOUD_TAGS))

        assert action.version_scheme == "loose"
        assert action.has_version_tags is True
        assert action.recommended.reference == "sha-09"
        assert action.recommended.comments == ["v0.9"]
        assert action.min_age_tag_date == OLD_DATE
        assert any("falling back to non-SemVer version tags" in warning for warning in action.warnings)

    def test_semver_tags_are_preferred_over_loose_tags(self) -> None:
        """Loose tags are ignored as soon as one SemVer tag exists."""
        action = GithubAction("org/action", "v1")
        action.actual.reference_type = "tag"

        _recommend(action, _make_repo({"v9": "sha-v9", "v1.2.3": "sha-123", "v1": "sha-123"}))

        assert action.version_scheme == "semver"
        assert action.recommended.reference == "sha-123"
        assert action.recommended.description == "v1.2.3"
        assert not action.warnings

    def test_loose_tag_too_young_keeps_pinned_tag_as_sha(self) -> None:
        """Without an eligible tag, the pinned tag is kept but pinned to its SHA."""
        young = datetime.datetime.now(datetime.UTC)
        action = GithubAction("org/action", "v2")
        action.actual.reference_type = "tag"

        _recommend(action, _make_repo({"v2": "sha-v2"}, dates={"sha-v2": young}), min_age=7)

        assert action.recommended.reference == "sha-v2"
        assert action.recommended.comments == ["v2"]

    def test_tag_reference_without_version_tag_is_pinned_to_sha(self) -> None:
        """A non-version tag reference is pinned to its SHA with a warning."""
        action = GithubAction("org/action", "latest")
        action.actual.reference_type = "tag"

        _recommend(action, _make_repo({"latest": "sha-latest"}))

        assert action.has_version_tags is False
        assert action.recommended.reference == "sha-latest"
        assert action.recommended.comments == ["latest"]
        assert any("pinning current tag 'latest'" in warning for warning in action.warnings)

    def test_sha_matching_non_version_tags_uses_most_precise_tag(self) -> None:
        """A bare SHA matching several tags keeps the most precise version-like name."""
        action = GithubAction("org/action", "sha-x")
        action.actual.reference_type = "sha"

        _recommend(action, _make_repo({"stable": "sha-x", "release-2024": "sha-x"}))

        assert action.recommended.reference == "sha-x"
        assert action.recommended.comments == ["release-2024"]

    def test_sha_matching_floating_and_precise_semver_tags_prefers_precise(self) -> None:
        """SemVer tags that are all too young fall back to the most precise tag at the pinned SHA."""
        young = datetime.datetime.now(datetime.UTC)
        action = GithubAction("org/action", "sha-x", comments=["gh-action-pulse: ignore[max-age]"])
        action.actual.reference_type = "sha"
        action.actual.description_type = "bullshit"

        _recommend(
            action,
            _make_repo({"v1": "sha-x", "v1.2.0": "sha-x"}, dates={"sha-x": young}),
            min_age=7,
        )

        assert action.recommended.reference == "sha-x"
        assert action.recommended.comments == ["v1.2.0", "gh-action-pulse: ignore[max-age]"]

    def test_branch_comment_without_tags_follows_branch(self) -> None:
        """@sha # branch keeps following the branch when there is no tag at all."""
        action = GithubAction("org/action", "sha-old", "main", comments=["main"])
        action.actual.reference_type = "sha"
        action.actual.description_type = "branch"

        _recommend(action, _make_repo({}, branches={"main": "sha-main"}, dates={"sha-old": OLD_DATE}))

        assert action.recommended.reference == "sha-main"
        assert action.recommended.comments == ["main"]

    def test_missing_branch_falls_back_to_unchanged_reference(self) -> None:
        """When nothing can be resolved, the line is kept unchanged instead of crashing."""
        action = GithubAction("org/action", "sha-old", "gone", comments=["gone", "note"])
        action.actual.reference_type = "sha"
        action.actual.description_type = "branch"

        _recommend(action, _make_repo({}, dates={"sha-old": OLD_DATE}))

        assert action.recommended.reference is None
        assert action.recommended.comments == ["gone", "note"]
        assert action.get_updated_uses_replacement("sha-old", ["gone", "note"]) is None
        assert any("keeping the current reference unchanged" in warning for warning in action.warnings)

    def test_sha_tag_comment_unresolvable_falls_back_to_related_branch(self) -> None:
        """A stale tag comment on a SHA falls back to the newest branch containing that SHA."""
        action = GithubAction("org/action", "sha-old", "v0.1", comments=["v0.1"])
        action.actual.reference_type = "sha"
        action.actual.description_type = "tag"
        repo = _make_repo({}, branches={"main": "sha-main"}, dates={"sha-old": OLD_DATE})
        repo.compare.side_effect = None
        repo.compare.return_value = MagicMock(status="ahead")

        _recommend(action, repo)

        assert action.recommended.reference == "sha-main"
        assert action.recommended.comments == ["main"]
        assert any("newest branch containing" in warning for warning in action.warnings)

    def test_related_branch_search_is_not_repeated(self) -> None:
        """A bare SHA with no tag and no related branch is searched only once."""
        action = GithubAction("org/action", "sha-old")
        action.actual.reference_type = "sha"
        repo = _make_repo({}, branches={"main": "sha-main"}, dates={"sha-old": OLD_DATE})

        _recommend(action, repo)

        assert repo.compare.call_count == 1
        assert action.recommended.reference is None
