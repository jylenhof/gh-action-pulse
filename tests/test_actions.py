"""Tests for the GithubAction class to ensure correct parsing and comparison."""

import datetime
from typing import TYPE_CHECKING, Literal
from unittest.mock import MagicMock, patch

import pytest
from github.GithubException import GithubException
from testfixtures import LogCapture, log_capture

from gh_action_pulse.actions import (
    GithubAction,
    GithubActionArchivedError,
)

if TYPE_CHECKING:
    from collections.abc import Callable


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

    def test_equality(self) -> None:
        """Verify equality and hash semantics for GithubAction instances."""
        a1 = GithubAction("repo", "v1", "desc")
        a2 = GithubAction("repo", "v1", "desc")
        a3 = GithubAction("repo", "v2", "desc")

        assert a1 == a2
        assert a1 != a3
        assert len({a1, a2}) == 1

        # Coverage for line 73: comparison with a different type
        assert a1 != "not a GithubAction"

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

        assert action.get_updated_uses_replacement(actual_reference, actual_description) == expected

    def test__set_actual_reference_type_and_date_with_tag(self) -> None:
        """Verify that _set_actual_reference_type_and_date correctly identifies the reference type and date."""
        action = GithubAction("actions/checkout", "v4")
        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v4.commit.commit.sha = "sha-for-v4"
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
        mock_sha_v4.commit.commit.sha = target_sha
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

    @patch("gh_action_pulse.actions.GithubAction._get_valid_semver_tags")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    def test__set_recommended_reference_and_date_tag(
        self,
        mock__set_recommended_reference_and_date_to_tag_if_exists: MagicMock,
        mock__get_valid_semver_tags: MagicMock,
    ) -> None:
        """Verify that _set_recommended_reference_and_date calls the correct method when reference is a tag."""
        action = GithubAction("actions/checkout", "v4")
        action.actual.reference_type = "tag"
        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v6 = MagicMock()
        mock__get_valid_semver_tags.return_value = [mock_tag_v6, mock_tag_v4]
        mock_valid_semver_tags = mock__get_valid_semver_tags.return_value

        action._set_recommended_reference_and_date()

        mock__get_valid_semver_tags.assert_called_once_with()
        mock__set_recommended_reference_and_date_to_tag_if_exists.assert_called_once_with(mock_valid_semver_tags)

    @patch("gh_action_pulse.actions.GithubAction._get_valid_semver_tags")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_with_fallback")
    def test__set_recommended_reference_and_date_branch(
        self,
        mock__set_recommended_with_fallback: MagicMock,
        mock__get_valid_semver_tags: MagicMock,
    ) -> None:
        """Verify that _set_recommended_reference_and_date calls the correct method when reference is a branch."""
        action = GithubAction("actions/checkout", "main")
        action.actual.reference_type = "branch"
        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v6 = MagicMock()
        mock__get_valid_semver_tags.return_value = [mock_tag_v6, mock_tag_v4]
        mock_valid_semver_tags = mock__get_valid_semver_tags.return_value

        action._set_recommended_reference_and_date()

        mock__get_valid_semver_tags.assert_called_once_with()
        mock__set_recommended_with_fallback.assert_called_once_with(mock_valid_semver_tags, "main")

    @patch("gh_action_pulse.actions.GithubAction._get_valid_semver_tags")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_for_sha")
    def test__set_recommended_reference_and_date_sha(
        self,
        mock__set_recommended_for_sha: MagicMock,
        mock__get_valid_semver_tags: MagicMock,
    ) -> None:
        """Check that _set_recommended_reference_and_date calls the correct method when reference is a sha."""
        action = GithubAction("actions/checkout", "sha-for-v4", "v4.0.0")
        action.actual.reference_type = "sha"
        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v6 = MagicMock()
        mock__get_valid_semver_tags.return_value = [mock_tag_v6, mock_tag_v4]
        mock_valid_semver_tags = mock__get_valid_semver_tags.return_value

        action._set_recommended_reference_and_date()

        mock__get_valid_semver_tags.assert_called_once_with()
        mock__set_recommended_for_sha.assert_called_once_with(mock_valid_semver_tags)

    @pytest.mark.parametrize(
        ("reference_type", "error_message"),
        [
            ("bullshit", "Cannot recommend update for invalid reference type."),
            (None, "Unknown reference type encountered, that should not happen."),
        ],
    )
    @log_capture()
    @patch("gh_action_pulse.actions.GithubAction._get_valid_semver_tags")
    def test__set_recommended_reference_and_date_bullshit(
        self,
        mock__get_valid_semver_tags: MagicMock,
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
        mock__get_valid_semver_tags.return_value = [mock_tag_v6, mock_tag_v4]

        with pytest.raises(SystemExit):
            action._set_recommended_reference_and_date()

        mock__get_valid_semver_tags.assert_called_once_with()
        capture.check(("gh_action_pulse.actions", "ERROR", error_message))

    def test__get_valid_semver_tags(self, create_mock_tag: Callable[..., MagicMock]) -> None:  # pylint: disable=redefined-outer-name
        """Verify that _get_valid_semver_tags correctly filters and sorts tags based on semantic versioning."""
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

        results = action._get_valid_semver_tags()

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
        mock_tag_v4.commit.commit.sha = "sha-for-v4"
        mock_tag_v6 = MagicMock()
        mock_tag_v6.commit.commit.sha = "sha-for-v6"
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
        mock_tag.commit.commit.sha = full_sha
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
            comparison.status = "behind" if head in {"sha-for-main-new", "sha-for-develop"} else "diverged"
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
        """Equal tag and branch dates should prefer the branch recommendation."""
        action = GithubAction("actions/checkout", "main")
        same_date = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)
        action.actual.date = same_date
        action.recommended.date = same_date
        mock_tag_v6 = MagicMock()

        action._set_recommended_with_fallback([mock_tag_v6], "main")

        mock__set_recommended_reference_and_date_to_tag_if_exists.assert_called_once_with([mock_tag_v6])
        mock__set_recommended_to_branch.assert_called_once_with("main")

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

    def test__get_valid_semver_tags_sets_has_semver_tags(self) -> None:
        """Verify that _get_valid_semver_tags records whether semver tags exist."""
        action = GithubAction("actions/checkout", "v4")
        mock_repo = MagicMock()
        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"
        mock_repo.get_tags.return_value = [mock_tag_v4, mock_tag_v6]
        action.repo = mock_repo

        action._get_valid_semver_tags()

        assert action.has_semver_tags is True

    def test__get_valid_semver_tags_clears_has_semver_tags_when_empty(self) -> None:
        """Verify that _get_valid_semver_tags clears has_semver_tags when no semver tags exist."""
        action = GithubAction("actions/checkout", "v4")
        mock_repo = MagicMock()
        mock_repo.get_tags.return_value = []
        action.repo = mock_repo

        action._get_valid_semver_tags()

        assert action.has_semver_tags is False

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
        action.has_semver_tags = True
        action.min_age_tag_date = None

        assert action.is_tag_fresh(150) is True

    def test_is_tag_fresh_when_no_semver_tags(self) -> None:
        """Verify is_tag_fresh returns False when no semver tags exist."""
        action = GithubAction("actions/checkout", "v4")
        action.has_semver_tags = False
        action.min_age_tag_date = None

        assert action.is_tag_fresh(150) is False
