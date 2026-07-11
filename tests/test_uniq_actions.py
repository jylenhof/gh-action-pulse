"""Tests for the UniqGithubActions collection."""

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gh_action_pulse.actions import GithubAction, GithubActionNotFoundError
from gh_action_pulse.uniq_actions import UniqGithubActions


class TestUniqGithubActions:
    """Unit tests for UniqGithubActions collection."""

    @pytest.mark.parametrize(
        ("name", "version", "description", "datecommit"),
        [
            ("actions/checkout", "v4", "pinned to v4", datetime.datetime(2026, 1, 9, 19, 42, 23, tzinfo=datetime.UTC)),
            ("actions/setup-python", "v5", None, datetime.datetime(2026, 1, 22, 2, 49, 33, tzinfo=datetime.UTC)),
        ],
    )
    @patch("gh_action_pulse.uniq_actions.GithubAction.get_fully_qualified")
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

    @patch("gh_action_pulse.uniq_actions.GithubAction.get_fully_qualified")
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
