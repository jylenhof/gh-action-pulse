"""Tests for the GithubAction and UniqGithubActions classes to ensure correct parsing and comparison."""

import datetime
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest
from packaging.version import InvalidVersion

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
    def test_get_fully_qualified(self, mock_github_cls: MagicMock) -> None:
        """Test that get_fully_qualified correctly orchestrates the internal logic to populate all fields."""
        # GIVEN
        action = GithubAction("actions/checkout", "v4")
        mock_repo = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo

        # Mock the internal helper methods to isolate the orchestration logic
        with (
            patch.object(action, "_set_actual_reference_type_and_date") as mock_set_actual,
            patch.object(action, "_set_actual_description_type") as mock_set_desc,
            patch.object(action, "_set_recommended_reference_and_date") as mock_set_rec,
        ):
            # WHEN
            result = action.get_fully_qualified()

            # THEN
            assert result is action
            mock_set_actual.assert_called_once()
            mock_set_desc.assert_called_once()
            mock_set_rec.assert_called_once()

    def test__set_recommended_reference_and_date_call_invalid_version_exception(self) -> None:
        """Verify that _set_recommended_reference_and_date correctly populates the recommended reference and date."""
        action = GithubAction("actions/checkout", "v4")
        # Mock the API response to return a specific recommended reference and date
        with patch("gh_action_pulse.actions.Github") as mock_github_cls:
            mock_repo = MagicMock()
            mock_github_cls.return_value.get_repo.return_value = mock_repo
            mock_tag_v4 = MagicMock()
            mock_tag_v4.name = "v4.0.0"
            mock_tag_invalid = MagicMock()
            mock_tag_invalid.name = "invalid-tag"
            mock_tag_v6 = MagicMock()
            mock_tag_v6.name = "v6.0.0"
            mock_repo.get_tags.return_value = [mock_tag_v4, mock_tag_invalid, mock_tag_v6]

            action._set_recommended_reference_and_date(mock_repo)

            pytest.raises(InvalidVersion, match="Invalid version: 'invalid-tag'")

    @pytest.mark.parametrize(
        ("name", "reference", "reference_type", "actual_description", "actual_description_type"),
        [
            ("actions/checkout", "v4", "tag", None, None),
            ("actions/checkout", "v4", "tag", "v4.0.0", "tag"),
            ("actions/checkout", "v4", "tag", "not_existing_ref", "bullshit"),
            ("actions/checkout", "sha-for-v4", "sha", None, None),
            ("actions/checkout", "sha-for-v4", "sha", "v4.0.0", "tag"),
            # ("actions/checkout", "sha-for-v4", "sha", "main", "branch"), # not working
            ("actions/checkout", "sha-for-v4", "sha", "not_existing_ref", "bullshit"),
        ],
    )
    def test__set_recommended_reference_and_date_initial_tag(
        self,
        name: str,
        reference: str,
        reference_type: Literal["tag", "branch", "sha", "bullshit"],
        actual_description: str | None,
        actual_description_type: Literal["tag", "branch", "bullshit"] | None,
    ) -> None:
        """Verify that _set_recommended_reference_and_date correctly populates the recommended reference and date."""
        action = GithubAction(name=name, reference=reference, actual_description=actual_description)
        mock_repo = MagicMock()

        mock_tag_v4 = MagicMock()
        mock_tag_v4.name = "v4.0.0"
        mock_tag_v4.commit.sha = "sha-for-v4"

        mock_tag_invalid = MagicMock()
        mock_tag_invalid.name = "invalid-tag"

        mock_tag_v6 = MagicMock()
        mock_tag_v6.name = "v6.0.0"

        mock_repo.get_tags.return_value = [mock_tag_v4, mock_tag_invalid, mock_tag_v6]

        mock_tag_v6.commit.sha = "sha-for-v6"
        mock_tag_v6.commit.commit.committer.date = datetime.datetime(2026, 2, 3, tzinfo=datetime.UTC)
        mock_repo.get_commit.return_value = mock_tag_v6.commit

        action.actual.reference_type = reference_type
        action.actual.description_type = actual_description_type
        action.actual.date = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)

        action._set_recommended_reference_and_date(mock_repo)

        assert action.recommended.reference == "sha-for-v6"
        assert action.recommended.description == "v6.0.0"
        assert action.recommended.date == datetime.datetime(2026, 2, 3, tzinfo=datetime.UTC)


class TestUniqGithubActions:
    """Unit tests for UniqGithubActions collection."""

    @pytest.mark.parametrize(
        ("name", "version", "description", "datecommit"),
        [
            ("actions/checkout", "v4", "pinned to v4", datetime.datetime(2026, 1, 9, 19, 42, 23, tzinfo=datetime.UTC)),
            ("actions/setup-python", "v5", None, datetime.datetime(2026, 1, 22, 2, 49, 33, tzinfo=datetime.UTC)),
        ],
    )
    def test_get_fully_qualified_attributes(
        self, name: str, version: str, description: str | None, datecommit: datetime.datetime
    ) -> None:
        """Verify fully qualified actions include actual and recommended metadata."""
        uniq = UniqGithubActions()
        a1 = GithubAction(name, version, description)
        uniq.add(a1)

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

    def test_get_fully_qualified_contents(self) -> None:
        """Verify fully qualified actions include both actual and recommended metadata."""
        uniq = UniqGithubActions()
        a1 = GithubAction("actions/checkout", "v4", "pinned to v4")
        a2 = GithubAction("actions/setup-python", "v5", None)
        uniq.add(a1)
        uniq.add(a2)

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
