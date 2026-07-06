"""Tests for CLI validation helpers in main."""

from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from gh_action_pulse.main import app, validate_max_age, validate_max_age_cli, validate_min_age, validate_min_age_cli

runner = CliRunner()


class TestValidateCliOptions:
    """Unit tests for CLI option validation helpers."""

    @patch("gh_action_pulse.main.__version__", "1.2.3")
    def test_version_option_prints_version_and_exits(self) -> None:
        """Verify that --version prints the package version and exits successfully."""
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert result.output.strip() == "1.2.3"

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

    def test_validate_min_age_rejects_negative_value(self) -> None:
        """Verify that negative min_age values are rejected."""
        with pytest.raises(ValueError, match=r"min_age must be 0 or greater\."):
            validate_min_age(-1)

    def test_validate_min_age_cli_wraps_value_error(self) -> None:
        """Verify that the Typer callback converts ValueError into BadParameter."""
        with pytest.raises(typer.BadParameter, match=r"min_age must be 0 or greater\."):
            validate_min_age_cli(-1)
