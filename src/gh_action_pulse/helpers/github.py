"""Module for handling GitHub authentication and token retrieval."""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)


class GitHubTokenNotFoundError(RuntimeError):
    """Exception raised when the GitHub token cannot be found.

    Using a custom class avoids TRY003 (long messages in exceptions).
    """

    def __init__(self) -> None:
        """Initialize the exception with a standard message."""
        super().__init__("GitHub token not found. Please set GITHUB_TOKEN or use 'gh auth login'.")


def get_github_token() -> str:
    """Retrieve the GitHub token from the environment or the 'gh' CLI.

    Returns:
        str: The GitHub token.

    Raises:
        RuntimeError: If the token cannot be found.
    """
    # Using getenv is more idiomatic than try/except KeyError
    if token := os.getenv("GITHUB_TOKEN"):
        return token

    logger.info("GITHUB_TOKEN not found in environment. Attempting to retrieve via 'gh auth token'...")

    try:
        # Fallback: Attempt to retrieve token via the GitHub CLI
        result = subprocess.run(
            ["gh", "auth", "token"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=10,  # Best practice to add a timeout
        )
        if token := result.stdout.strip():
            logger.info("GitHub token successfully retrieved from 'gh' CLI.")
            return token
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        # Redundant str() in logging is removed to satisfy linter
        logger.debug("Failed to retrieve token from 'gh' CLI: %s", e)

    return _fail_token_retrieval()


def _fail_token_retrieval() -> str:
    """Helper to raise the custom exception to satisfy TRY003."""
    raise GitHubTokenNotFoundError
