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

"""Tests for the UniqGithubActions collection."""

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gh_action_pulse.actions import GithubAction, GithubActionNotFoundError
from gh_action_pulse.helpers.uses_line import UsesOccurrence, parse_uses_line
from gh_action_pulse.uniq_actions import UniqGithubActions


def _occurrence(raw_line: str, path: str = "test.yml", line_number: int = 1) -> UsesOccurrence:
    parsed = parse_uses_line(raw_line, file=Path(path), line_number=line_number)
    assert parsed is not None
    return parsed


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
                _occurrence("uses: actions/checkout@v4.0.0 # v4.0.0", path="test_actions.yml", line_number=10),
                _occurrence("- uses: some-owner/some-repo@master", path="test_actions.yml", line_number=15),
            ],
            Path("another_file.yaml"): [
                _occurrence("uses: actions/setup-python@v5", path="another_file.yaml", line_number=5),
                _occurrence("uses: actions/checkout@v4.0.0 # v4.0.0", path="another_file.yaml", line_number=25),
            ],
        }
        uniq = UniqGithubActions()
        uniq.init_from_full_list(full_list=full_list)
        assert len(uniq._actions) == 3
        checkout = uniq.get_item("actions/checkout", "v4.0.0", "v4.0.0")
        assert checkout.actual.description == "v4.0.0"
        setup_python = uniq.get_item("actions/setup-python", "v5", None)
        assert setup_python.actual.description is None

    def test_init_from_full_list_uses_first_comment_as_description(self) -> None:
        """Verify only the first trailing comment is stored as the action description."""
        full_list = {
            Path("test.yml"): [
                _occurrence("uses: actions/checkout@abc123 # v4.2.2 # extra note"),
                _occurrence(
                    "uses: actions/setup-python@def456 # v5.0.0 # gh-action-pulse: ignore[max-days]",
                    line_number=2,
                ),
                _occurrence("uses: actions/cache@ghi789 # gh-action-pulse: ignore[max-days]", line_number=3),
            ]
        }
        uniq = UniqGithubActions()
        uniq.init_from_full_list(full_list)

        checkout = uniq.get_item("actions/checkout", "abc123", "v4.2.2")
        assert checkout.actual.description == "v4.2.2"
        assert checkout.actual.comments == ["v4.2.2", "extra note"]
        setup_python = uniq.get_item("actions/setup-python", "def456", "v5.0.0")
        assert setup_python.actual.description == "v5.0.0"
        assert setup_python.actual.comments == ["v5.0.0", "gh-action-pulse: ignore[max-days]"]
        assert setup_python.actual.ignore_hint.unknown == frozenset({"max-days"})
        cache = uniq.get_item("actions/cache", "ghi789", "gh-action-pulse: ignore[max-days]")
        assert cache.actual.description == "gh-action-pulse: ignore[max-days]"
        assert cache.actual.comments == ["gh-action-pulse: ignore[max-days]"]

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

    def test_get_item_matches_exact_comments(self) -> None:
        """Actions that share a pin but differ in extra comments must not be confused."""
        uniq_actions = UniqGithubActions()
        shared = ("actions/checkout", "abc123", "v4.2.0")
        with_ignore = GithubAction(*shared, comments=["v4.2.0", "gh-action-pulse: ignore[max-days]"])
        with_note = GithubAction(*shared, comments=["v4.2.0", "keep me"])
        uniq_actions.add(with_ignore)
        uniq_actions.add(with_note)

        assert uniq_actions.get_item(*shared) in {with_ignore, with_note}
        assert uniq_actions.get_item(*shared, comments=["v4.2.0", "gh-action-pulse: ignore[max-days]"]) is with_ignore
        assert uniq_actions.get_item(*shared, comments=["v4.2.0", "keep me"]) is with_note
        with pytest.raises(GithubActionNotFoundError):
            uniq_actions.get_item(*shared, comments=["v4.2.0"])

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

    def test_get_stale_actions_skips_actions_with_max_age_ignore_hint(self) -> None:
        """A stale action is omitted from freshness failures when max-age is ignored."""
        uniq = UniqGithubActions()
        ignored = GithubAction(
            "actions/setup-python",
            "v5",
            "v5",
            comments=["v5", "gh-action-pulse: ignore[max-age]"],
        )
        ignored.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=200)
        stale = GithubAction("actions/checkout", "v4")
        stale.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=200)
        uniq.add(ignored)
        uniq.add(stale)

        result = uniq.get_stale_actions(150)

        assert result == [stale]

    def test_get_stale_actions_uses_max_days_override(self) -> None:
        """A max-age override raises the freshness limit for that action only."""
        uniq = UniqGithubActions()
        overridden = GithubAction(
            "actions/setup-python",
            "v5",
            "v5",
            comments=["v5", "gh-action-pulse: override[max-age=200]"],
        )
        overridden.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=180)
        stale = GithubAction("actions/checkout", "v4")
        stale.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=180)
        uniq.add(overridden)
        uniq.add(stale)

        result = uniq.get_stale_actions(150)

        assert result == [stale]

    def test_get_stale_actions_override_can_enable_disabled_check(self) -> None:
        """A max-age override still runs when the CLI max-age check is disabled."""
        uniq = UniqGithubActions()
        overridden = GithubAction(
            "actions/setup-python",
            "v5",
            "v5",
            comments=["v5", "gh-action-pulse: override[max-age=150]"],
        )
        overridden.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=200)
        plain = GithubAction("actions/checkout", "v4")
        plain.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=200)
        uniq.add(overridden)
        uniq.add(plain)

        result = uniq.get_stale_actions(0)

        assert result == [overridden]

    def test_get_stale_actions_returns_empty_when_check_disabled(self) -> None:
        """Verify get_stale_actions skips the check when max_age is 0."""
        uniq = UniqGithubActions()
        stale = GithubAction("actions/setup-python", "v5")
        stale.min_age_tag_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=200)
        uniq.add(stale)

        assert not uniq.get_stale_actions(0)

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
