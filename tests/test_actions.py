"""Tests for the GithubAction and UniqGithubActions classes to ensure correct parsing and comparison."""

import datetime
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest
from github.GithubException import GithubException
from testfixtures import LogCapture, log_capture

from gh_action_pulse.actions import GithubAction, UniqGithubActions


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

    @patch("gh_action_pulse.actions.Github")
    @patch("gh_action_pulse.actions.GithubAction._set_actual_reference_type_and_date")
    @patch("gh_action_pulse.actions.GithubAction._set_actual_description_type")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date")
    def test_get_fully_qualified(
        self, mock_set_rec: MagicMock, mock_set_desc: MagicMock, mock_set_actual: MagicMock, mock_github_cls: MagicMock
    ) -> None:
        """Test that get_fully_qualified correctly orchestrates the internal logic to populate all fields."""
        # GIVEN
        action = GithubAction("actions/checkout", "v4")
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo

        # WHEN
        result = action.get_fully_qualified()

        # THEN
        assert result is action
        mock_set_actual.assert_called_once()
        mock_set_desc.assert_called_once()
        mock_set_rec.assert_called_once()

    @patch("gh_action_pulse.actions.Github")
    def test__set_actual_reference_type_and_date_with_tag(self, mock_github_cls: MagicMock) -> None:
        """Verify that _set_actual_reference_type_and_date correctly identifies the reference type and date."""
        action = GithubAction("actions/checkout", "v4")
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v4.commit.commit.sha = "sha-for-v4"
        mock_tag_v4.commit.commit.committer.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_repo.get_commit.return_value = mock_tag_v4.commit

        action._set_actual_reference_type_and_date(mock_repo)

        assert action.actual.reference_type == "tag"
        assert action.actual.date == datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        assert mock_repo.get_commit.call_count == 1
        mock_repo.get_commit.assert_called_once_with(sha="v4")
        mock_repo.get_git_ref("heads/v4").assert_not_called()

    @patch("gh_action_pulse.actions.Github")
    def test__set_actual_reference_type_and_date_with_sha(self, mock_github_cls: MagicMock) -> None:
        """Verify that _set_actual_reference_type_and_date correctly identifies the reference type and date."""
        action = GithubAction("actions/checkout", "sha-for-v4")
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_sha_v4 = MagicMock()
        mock_sha_v4.commit.commit.sha = "sha-for-v4"
        mock_sha_v4.commit.commit.committer.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_repo.get_commit.return_value = mock_sha_v4.commit

        action._set_actual_reference_type_and_date(mock_repo)

        assert action.actual.reference_type == "sha"
        assert action.actual.date == datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        assert mock_repo.get_commit.call_count == 1
        mock_repo.get_commit.assert_called_once_with(sha="sha-for-v4")
        mock_repo.get_git_ref("heads/sha-for-v4").assert_not_called()

    @patch("gh_action_pulse.actions.Github")
    def test__set_actual_reference_type_and_date_with_branch(self, mock_github_cls: MagicMock) -> None:
        """Verify that _set_actual_reference_type_and_date correctly identifies the reference type and date."""
        action = GithubAction("actions/checkout", "main")
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_branch = MagicMock()
        mock_branch.commit.commit.sha = "sha-for-main"
        mock_branch.commit.commit.committer.date = datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        mock_repo.get_commit.side_effect = [GithubException(404, "Not Found", None), mock_branch.commit]
        mock_repo.get_git_ref.return_value = mock_branch.commit

        action._set_actual_reference_type_and_date(mock_repo)

        assert action.actual.reference_type == "branch"
        assert action.actual.date == datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC)
        assert mock_repo.get_commit.call_count == 2
        mock_repo.get_git_ref.assert_called_once_with("heads/main")

    @patch("gh_action_pulse.actions.Github")
    def test__set_actual_reference_type_and_date_with_invalid_ref(self, mock_github_cls: MagicMock) -> None:
        """Verify that _set_actual_reference_type_and_date correctly handles invalid references."""
        action = GithubAction("actions/checkout", "invalid-ref")
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_repo.get_commit.side_effect = GithubException(404, "Not Found", None)
        mock_repo.get_git_ref.side_effect = GithubException(404, "Not Found", None)

        action._set_actual_reference_type_and_date(mock_repo)

        assert action.actual.reference_type == "bullshit"
        assert action.actual.date is None
        assert mock_repo.get_commit.call_count == 1
        mock_repo.get_commit.assert_called_once_with(sha="invalid-ref")
        mock_repo.get_git_ref.assert_called_once_with("heads/invalid-ref")

    @patch("gh_action_pulse.actions.Github")
    def test__set_actual_description_type_with_none(self, mock_github_cls: MagicMock) -> None:
        """Verify that _set_actual_description_type correctly handles None description."""
        action = GithubAction("actions/checkout", "v4", None)
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo

        action._set_actual_description_type(mock_repo)

        assert action.actual.description_type is None
        mock_repo.get_git_ref.assert_not_called()

    @patch("gh_action_pulse.actions.Github")
    def test__set_actual_description_type_with_tag(self, mock_github_cls: MagicMock) -> None:
        """Verify that _set_actual_description_type correctly identifies a tag description."""
        action = GithubAction("actions/checkout", "v4", "v4.0.0")
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_repo.get_git_ref.return_value = MagicMock()  # Simulate tag exists

        action._set_actual_description_type(mock_repo)

        assert action.actual.description_type == "tag"
        mock_repo.get_git_ref.assert_called_once_with("tags/v4.0.0")

    @patch("gh_action_pulse.actions.Github")
    def test__set_actual_description_type_with_branch(self, mock_github_cls: MagicMock) -> None:
        """Verify that _set_actual_description_type correctly identifies a branch description."""
        action = GithubAction("actions/checkout", "v4", "main")
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_repo.get_git_ref.return_value = MagicMock()  # Simulate branch exists
        mock_repo.get_git_ref.side_effect = [
            GithubException(404, "Not Found", None),
            mock_repo.get_git_ref.return_value,
        ]

        action._set_actual_description_type(mock_repo)

        assert action.actual.description_type == "branch"
        assert mock_repo.get_git_ref.call_count == 2
        mock_repo.get_git_ref.assert_any_call("tags/main")
        mock_repo.get_git_ref.assert_any_call("heads/main")

    @patch("gh_action_pulse.actions.Github")
    def test__set_actual_description_type_with_invalid_ref(self, mock_github_cls: MagicMock) -> None:
        """Verify that _set_actual_description_type correctly handles invalid description references."""
        action = GithubAction("actions/checkout", "v4", "invalid-desc")
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_repo.get_git_ref.side_effect = GithubException(404, "Not Found", None)

        action._set_actual_description_type(mock_repo)

        assert action.actual.description_type == "bullshit"
        assert mock_repo.get_git_ref.call_count == 2
        mock_repo.get_git_ref.assert_any_call("tags/invalid-desc")
        mock_repo.get_git_ref.assert_any_call("heads/invalid-desc")

    @patch("gh_action_pulse.actions.Github")
    @patch("gh_action_pulse.actions.GithubAction._get_valid_semver_tags")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_reference_and_date_to_tag_if_exists")
    def test__set_recommended_reference_and_date_tag(
        self,
        mock__set_recommended_reference_and_date_to_tag_if_exists: MagicMock,
        mock__get_valid_semver_tags: MagicMock,
        mock_github_cls: MagicMock,
    ) -> None:
        """Verify that _set_recommended_reference_and_date calls the correct method when reference is a tag."""
        action = GithubAction("actions/checkout", "v4")
        action.actual.reference_type = "tag"
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v6 = MagicMock()
        mock__get_valid_semver_tags.return_value = [mock_tag_v6, mock_tag_v4]
        mock_valid_semver_tags = mock__get_valid_semver_tags.return_value

        action._set_recommended_reference_and_date(mock_repo)

        mock__get_valid_semver_tags.assert_called_once_with(mock_repo)
        mock__set_recommended_reference_and_date_to_tag_if_exists.assert_called_once_with(mock_valid_semver_tags)

    @patch("gh_action_pulse.actions.Github")
    @patch("gh_action_pulse.actions.GithubAction._get_valid_semver_tags")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_with_fallback")
    def test__set_recommended_reference_and_date_branch(
        self,
        mock__set_recommended_with_fallback: MagicMock,
        mock__get_valid_semver_tags: MagicMock,
        mock_github_cls: MagicMock,
    ) -> None:
        """Verify that _set_recommended_reference_and_date calls the correct method when reference is a branch."""
        action = GithubAction("actions/checkout", "main")
        action.actual.reference_type = "branch"
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v6 = MagicMock()
        mock__get_valid_semver_tags.return_value = [mock_tag_v6, mock_tag_v4]
        mock_valid_semver_tags = mock__get_valid_semver_tags.return_value

        action._set_recommended_reference_and_date(mock_repo)

        mock__get_valid_semver_tags.assert_called_once_with(mock_repo)
        mock__set_recommended_with_fallback.assert_called_once_with(mock_repo, mock_valid_semver_tags, "main")

    @patch("gh_action_pulse.actions.Github")
    @patch("gh_action_pulse.actions.GithubAction._get_valid_semver_tags")
    @patch("gh_action_pulse.actions.GithubAction._set_recommended_for_sha")
    def test__set_recommended_reference_and_date_sha(
        self,
        mock__set_recommended_for_sha: MagicMock,
        mock__get_valid_semver_tags: MagicMock,
        mock_github_cls: MagicMock,
    ) -> None:
        """Check that _set_recommended_reference_and_date calls the correct method when reference is a sha."""
        action = GithubAction("actions/checkout", "sha-for-v4", "v4.0.0")
        action.actual.reference_type = "sha"
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v6 = MagicMock()
        mock__get_valid_semver_tags.return_value = [mock_tag_v6, mock_tag_v4]
        mock_valid_semver_tags = mock__get_valid_semver_tags.return_value

        action._set_recommended_reference_and_date(mock_repo)

        mock__get_valid_semver_tags.assert_called_once_with(mock_repo)
        mock__set_recommended_for_sha.assert_called_once_with(mock_repo, mock_valid_semver_tags)

    @pytest.mark.parametrize(
        ("reference_type", "error_message"),
        [
            ("bullshit", "Cannot recommend update for invalid reference type."),
            (None, "Unknown reference type encountered, that should not happen."),
        ],
    )
    @log_capture()
    @patch("gh_action_pulse.actions.Github")
    @patch("gh_action_pulse.actions.GithubAction._get_valid_semver_tags")
    def test__set_recommended_reference_and_date_bullshit(
        self,
        mock__get_valid_semver_tags: MagicMock,
        mock_github_cls: MagicMock,
        capture: LogCapture,
        reference_type: Literal["bullshit", "sha", "tag", "branch"] | None,
        error_message: str,
    ) -> None:
        """Check that _set_recommended_reference_and_date calls the correct method when reference is bullshit."""
        action = GithubAction("actions/checkout", "sha-for-main", "main")
        action.actual.reference_type = reference_type
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_tag_v4 = MagicMock()
        mock_tag_v6 = MagicMock()
        mock__get_valid_semver_tags.return_value = [mock_tag_v6, mock_tag_v4]

        with pytest.raises(SystemExit):
            action._set_recommended_reference_and_date(mock_repo)

        mock__get_valid_semver_tags.assert_called_once_with(mock_repo)
        capture.check(("gh_action_pulse.actions", "ERROR", error_message))


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

        def mock_impl() -> GithubAction:
            a1.recommended.date = datecommit
            return a1

        mock_get_fq.side_effect = mock_impl

        fully_qualified_actions = uniq.get_fully_qualified()
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
            Path("test_actions.py"): [
                {10: "uses: actions/checkout@v4 # pinned to v4"},
                {15: "- uses: some-owner/some-repo@master"},
            ]
        }
        uniq = UniqGithubActions()
        uniq.init_from_full_list(full_list=full_list)
        assert len(uniq._actions) == 2

    def test_add(self) -> None:
        """Verify that adding a GithubAction stores it in the unique actions collection."""
        uniq = UniqGithubActions()
        a1 = GithubAction("actions/checkout", "v4", "pinned to v4")
        uniq.add(a1)
        assert len(uniq._actions) == 1

    def test_get_actions(self) -> None:
        """Verify get_actions returns the stored unique actions."""
        uniq = UniqGithubActions()
        a1 = GithubAction("actions/checkout", "v4", "pinned to v4")
        uniq.add(a1)
        actions = uniq.get_actions()
        assert len(actions) == 1
        # Convert to list to access by index
        assert next(iter(actions)).name == "actions/checkout"

    @patch("gh_action_pulse.actions.GithubAction.get_fully_qualified")
    def test_get_fully_qualified_contents(self, mock_get_fq: MagicMock) -> None:
        """Verify fully qualified actions include both actual and recommended metadata."""
        uniq = UniqGithubActions()
        a1 = GithubAction("actions/checkout", "v4", "pinned to v4")
        a2 = GithubAction("actions/setup-python", "v5", None)
        uniq.add(a1)
        uniq.add(a2)

        mock_get_fq.side_effect = [a1, a2]

        fully_qualified_actions = uniq.get_fully_qualified()
        assert len(fully_qualified_actions) == 2

        # Convert to list for iteration, and find specific actions by name
        checkout_action = next((a for a in fully_qualified_actions if a.name == "actions/checkout"), None)
        setup_python_action = next((a for a in fully_qualified_actions if a.name == "actions/setup-python"), None)

        assert checkout_action is not None
        assert setup_python_action is not None

        # Check checkout action
        assert checkout_action.name == "actions/checkout"
        assert checkout_action.actual.description == "pinned to v4"

        # Check setup-python action
        assert setup_python_action.name == "actions/setup-python"
        assert setup_python_action.actual.description is None
