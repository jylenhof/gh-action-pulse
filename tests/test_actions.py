"""Tests for the GithubAction and UniqGithubActions classes to ensure correct parsing and comparison."""

import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from unittest.mock import MagicMock, patch

import pytest
from github.GithubException import GithubException
from testfixtures import LogCapture, log_capture

from gh_action_pulse.actions import GithubAction, GithubActionNotFoundError, UniqGithubActions

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
        mock_g.get_repo.return_value = mock_repo

        # WHEN
        result = action.get_fully_qualified(mock_g, 0)

        # THEN
        assert result is action
        mock_set_actual.assert_called_once()
        mock_set_desc.assert_called_once()
        mock_set_rec.assert_called_once()

    def test__set_actual_reference_type_and_date_with_tag(self) -> None:
        """Verify that _set_actual_reference_type_and_date correctly identifies the reference type and date."""
        action = GithubAction("actions/checkout", "v4")
        mock_repo = MagicMock()
        action.repo = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v4.commit.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_repo.get_commit.return_value = mock_tag_v4.commit

        action._set_actual_reference_type_and_date()

        assert action.actual.reference_type == "tag"
        assert action.actual.date == datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        assert mock_repo.get_commit.call_count == 1
        mock_repo.get_commit.assert_called_once_with(sha="v4")
        mock_repo.get_git_ref("heads/v4").assert_not_called()

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

        action._set_actual_reference_type_and_date()

        assert action.actual.reference_type == "sha"
        assert action.actual.date == datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        assert mock_repo.get_commit.call_count == 1
        mock_repo.get_commit.assert_called_once_with(sha=target_sha)
        mock_repo.get_git_ref(f"heads/{target_sha}").assert_not_called()

    def test__set_actual_reference_type_and_date_with_branch(self) -> None:
        """Verify that _set_actual_reference_type_and_date correctly identifies the reference type and date."""
        action = GithubAction("actions/checkout", "main")
        mock_repo = MagicMock()
        mock_branch = MagicMock()
        mock_branch.commit.commit.sha = "sha-for-main"
        mock_branch.commit.commit.committer.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_repo.get_commit.side_effect = [GithubException(404, "Not Found", None), mock_branch.commit]
        mock_repo.get_git_ref.return_value = mock_branch.commit
        action.repo = mock_repo

        action._set_actual_reference_type_and_date()

        assert action.actual.reference_type == "branch"
        assert action.actual.date == datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        assert mock_repo.get_commit.call_count == 2
        mock_repo.get_git_ref.assert_called_once_with("heads/main")

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
        mock_repo.get_git_ref.assert_called_once_with("heads/invalid-ref")

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

        assert mock__set_recommended_reference_and_date_to_tag_if_exists.call_once_with(mock_valid_semver_tags)

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

        assert mock__set_recommended_with_fallback.call_once_with(mock_valid_semver_tags, "main")

    @patch("gh_action_pulse.actions.GithubAction._actual_sha_matches_tag")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_to_branch")
    def test__set_recommended_for_sha_when_description_is_bullshit_or_none_and_sha_is_tag_related(
        self,
        mock__set_recommended_to_branch: MagicMock,
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
        action.recommended.reference = "v6.0.0"

        action._set_recommended_for_sha(mock_valid_semver_tags)

        assert mock__set_recommended_reference_and_date_to_tag_if_exists.call_once_with(mock_valid_semver_tags)
        assert mock__set_recommended_to_branch.call_once_with("main")

    @patch("gh_action_pulse.actions.GithubAction._actual_sha_matches_tag")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_to_branch")
    def test__set_recommended_for_sha_when_description_is_bullshit_or_none_and_sha_is_not_tag_related(
        self,
        mock__set_recommended_to_branch: MagicMock,
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

        assert mock__set_recommended_reference_and_date_to_tag_if_exists.call_count == 0
        assert mock__set_recommended_to_branch.call_once_with("main")

    def test__actual_sha_matches_tag(self) -> None:
        """Verify that _actual_sha_matches_tag correctly identifies when the actual sha matches a tag."""
        action = GithubAction("actions/checkout", "sha-for-v4", "v4.0.0")
        mock_repo = MagicMock()
        mock_tag_v4 = MagicMock()
        mock_tag_v4.commit.commit.sha = "sha-for-v4"
        mock_tag_v6 = MagicMock()
        mock_tag_v6.commit.commit.sha = "sha-for-v6"
        mock_repo.get_tags.return_value = [mock_tag_v4, mock_tag_v6]
        action.repo = mock_repo

        result = action._actual_sha_matches_tag()

        assert result is True

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
        """Checks that tags newer than the min_age cutoff are not recommended."""
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


class TestUniqGithubActions:
    """Unit tests for UniqGithubActions collection."""

    @pytest.mark.parametrize(
        ("name", "version", "description", "datecommit"),
        [
            ("actions/checkout", "v4", "pinned to v4", datetime.datetime(2026, 1, 9, 19, 42, 23, tzinfo=datetime.UTC)),
            ("actions/setup-python", "v5", None, datetime.datetime(2026, 1, 22, 2, 49, 33, tzinfo=datetime.UTC)),
        ],
    )
    @patch("gh_action_pulse.actions.GithubAction.get_fully_qualified")
    def test_get_fully_qualified_attributes(
        self, mock_get_fq: MagicMock, name: str, version: str, description: str | None, datecommit: datetime.datetime
    ) -> None:
        """Verify fully qualified actions include actual and recommended metadata."""
        uniq = UniqGithubActions()
        a1 = GithubAction(name, version, description)
        uniq.add(a1)

        def mock_impl(_: MagicMock, min_age: int) -> GithubAction:
            a1.recommended.date = datecommit
            a1.min_age = min_age
            return a1

        mock_get_fq.side_effect = mock_impl

        fully_qualified_actions = uniq.get_fully_qualified(MagicMock(), 0)
        assert len(fully_qualified_actions) == 1
        # Convert to list to access by index, or iterate.
        # Since we expect only one, converting to list and taking the first element is acceptable.
        action = next(iter(fully_qualified_actions))
        assert action.name == name
        assert action.actual.description == description
        assert action.recommended.date == datecommit

    def test_init_from_full_list(self) -> None:
        """Verify initialization from a full action list populates unique actions."""
        full_list = {
            Path("test_actions.yml"): [
                {10: "uses: actions/checkout@v4.0.0 # v4.0.0"},
                {15: "- uses: some-owner/some-repo@master"},
            ],
            Path("another_file.yaml"): [
                {5: "uses: actions/setup-python@v5"},
                {25: "uses: actions/checkout@v4.0.0 # v4.0.0"},
            ],
        }
        uniq = UniqGithubActions()
        uniq.init_from_full_list(full_list=full_list)
        assert len(uniq._actions) == 3

    def test_init_from_full_list_with_mixed_content(self) -> None:
        """Verify that valid actions are parsed and invalid ones (like local actions) are skipped."""
        full_list = {
            Path("test.yml"): [
                {1: "uses: actions/checkout@v4"},  # Valid: matches regex
                {2: "uses: ./local-action"},  # Invalid: missing @, should be skipped
            ]
        }
        uniq = UniqGithubActions()
        uniq.init_from_full_list(full_list)
        # Covers the False branch of the regex match and ensures line 245 is hit for the valid one
        assert len(uniq.get_actions()) == 1

    def test_init_from_full_list_empty(self) -> None:
        """Verify that initialization with an empty list handles the loop exit branches correctly."""
        uniq = UniqGithubActions()
        # Test with empty outer dict
        uniq.init_from_full_list({})
        assert len(uniq.get_actions()) == 0

        # Test with empty inner lists
        uniq.init_from_full_list({Path("empty.yml"): []})
        assert len(uniq.get_actions()) == 0

    def test_get_fully_qualified_empty(self) -> None:
        """Verify get_fully_qualified returns an empty set if no actions are present."""
        uniq = UniqGithubActions()
        assert uniq.get_fully_qualified(MagicMock(), 0) == set()

    def test_add(self) -> None:
        """Verify that adding a GithubAction stores it in the unique actions collection."""
        uniq = UniqGithubActions()
        a1 = GithubAction("actions/checkout", "v4.0.0", "v4.0.0")
        uniq.add(a1)
        assert len(uniq._actions) == 1

    def test_get_actions(self) -> None:
        """Verify get_actions returns the stored unique actions."""
        uniq = UniqGithubActions()
        a1 = GithubAction("actions/checkout", "v4.0.0", "v4.0.0")
        uniq.add(a1)
        actions = uniq.get_actions()
        assert len(actions) == 1
        # Convert to list to access by index
        assert next(iter(actions)).name == "actions/checkout"

    def test___getitem__(self) -> None:
        """Verify that __getitem__ allows indexing into the set of actions and handles out-of-bounds."""
        uniq = UniqGithubActions()
        a1 = GithubAction("actions/checkout", "v4.0.0", "v4.0.0")
        a2 = GithubAction("actions/setup-python", "v5", None)
        uniq.add(a1)
        uniq.add(a2)

        # Ensure the two added actions are present when indexed
        # The order of elements when converting a set to a list is not guaranteed.
        # So, we check for membership rather than strict equality at a specific index.
        retrieved_0 = uniq[0]
        retrieved_1 = uniq[1]

        assert retrieved_0 in [a1, a2]
        assert retrieved_1 in [a1, a2]
        assert retrieved_0 != retrieved_1  # Ensure different actions are retrieved

        # Test out-of-bounds positive index
        with pytest.raises(IndexError):
            _ = uniq[2]

        # Test out-of-bounds negative index
        with pytest.raises(IndexError):
            _ = uniq[-3]

    def test_get_item_found(self) -> None:
        """Verify that __getitem__ allows indexing into the set of actions and handles out-of-bounds."""
        uniq_actions = UniqGithubActions()
        a1 = GithubAction("actions/checkout", "v4.0.0", "v4.0.0")
        a2 = GithubAction("actions/setup-python", "v5", None)
        uniq_actions.add(a1)
        uniq_actions.add(a2)

        result = uniq_actions.get_item(name="actions/checkout", reference="v4.0.0", description="v4.0.0")

        assert result == a1

    def test_get_item_not_found(self) -> None:
        """Verify that __getitem__ allows indexing into the set of actions and handles out-of-bounds."""
        uniq_actions = UniqGithubActions()
        a1 = GithubAction("actions/checkout", "v4.0.0", "v4.0.0")
        a2 = GithubAction("actions/setup-python", "v5", None)
        uniq_actions.add(a1)
        uniq_actions.add(a2)

        with pytest.raises(GithubActionNotFoundError):
            uniq_actions.get_item(name="actions/checkout", reference="v6.0.0", description="v4.0.0")

    def test_get_stale_actions_returns_stale_actions(self) -> None:
        """Verify get_stale_actions returns actions with min-age eligible tags older than the threshold."""
        uniq = UniqGithubActions()
        fresh = GithubAction("actions/checkout", "v4")
        fresh.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=10)
        stale = GithubAction("actions/setup-python", "v5")
        stale.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=200)
        uniq.add(fresh)
        uniq.add(stale)

        result = uniq.get_stale_actions(150)

        assert result == [stale]

    def test_get_stale_actions_returns_empty_when_check_disabled(self) -> None:
        """Verify get_stale_actions skips the check when max_age is 0."""
        uniq = UniqGithubActions()
        stale = GithubAction("actions/setup-python", "v5")
        stale.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=200)
        uniq.add(stale)

        assert uniq.get_stale_actions(0) == []

    @patch("gh_action_pulse.actions.GithubAction.get_fully_qualified")
    def test_get_fully_qualified_contents(self, mock_get_fq: MagicMock) -> None:
        """Verify fully qualified actions include both actual and recommended metadata."""
        uniq = UniqGithubActions()
        a1 = GithubAction("actions/checkout", "v4.0.0", "v4.0.0")
        a2 = GithubAction("actions/setup-python", "v5", None)
        uniq.add(a1)
        uniq.add(a2)

        mock_get_fq.side_effect = [a1, a2]

        fully_qualified_actions = uniq.get_fully_qualified(MagicMock(), 0)
        assert len(fully_qualified_actions) == 2

        # Convert to list for iteration, and find specific actions by name
        checkout_action = next((a for a in fully_qualified_actions if a.name == "actions/checkout"), None)
        setup_python_action = next((a for a in fully_qualified_actions if a.name == "actions/setup-python"), None)

        assert checkout_action is not None
        assert setup_python_action is not None

        # Check checkout action
        assert checkout_action.name == "actions/checkout"
        assert checkout_action.actual.description == "v4.0.0"

        # Check setup-python action
        assert setup_python_action.name == "actions/setup-python"
        assert setup_python_action.actual.description is None
