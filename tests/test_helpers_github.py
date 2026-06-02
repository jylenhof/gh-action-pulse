"""Tests for the GitHub helper functions."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from gh_action_pulse.helpers.github import GitHubTokenNotFoundError, get_github_token


class TestGetGithubToken:
    """Tests for the get_github_token helper function."""

    @patch.dict(os.environ, {"GITHUB_TOKEN": "env_token"})
    def test_get_github_token_from_env(self) -> None:
        """Verify token is retrieved from environment variable if present."""
        assert get_github_token() == "env_token"

    @patch.dict(os.environ, {}, clear=True)
    @patch("subprocess.run")
    def test_get_github_token_from_gh_cli(self, mock_run: MagicMock) -> None:
        """Verify token is retrieved from 'gh' CLI if environment variable is missing."""
        mock_result = MagicMock()
        mock_result.stdout = "cli_token\n"
        mock_run.return_value = mock_result

        assert get_github_token() == "cli_token"
        mock_run.assert_called_once_with(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )

    @patch.dict(os.environ, {}, clear=True)
    @patch("subprocess.run")
    def test_get_github_token_from_gh_cli_empty_stdout(self, mock_run: MagicMock) -> None:
        """Verify GitHubTokenNotFoundError is raised if 'gh auth token' returns an empty string."""
        mock_result = MagicMock()
        mock_result.stdout = "   \n"  # Whitespace only
        mock_run.return_value = mock_result

        with pytest.raises(GitHubTokenNotFoundError):
            get_github_token()

    @patch.dict(os.environ, {}, clear=True)
    @patch("subprocess.run")
    def test_get_github_token_not_found(self, mock_run: MagicMock) -> None:
        """Verify RuntimeError is raised if token is not found in env or via CLI."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh auth token")

        with pytest.raises(RuntimeError) as excinfo:
            get_github_token()

        assert "GitHub token not found" in str(excinfo.value)

    @patch.dict(os.environ, {}, clear=True)
    @patch("subprocess.run")
    def test_get_github_token_gh_not_installed(self, mock_run: MagicMock) -> None:
        """Verify RuntimeError is raised if 'gh' is not installed."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(RuntimeError) as excinfo:
            get_github_token()

        assert "GitHub token not found" in str(excinfo.value)
