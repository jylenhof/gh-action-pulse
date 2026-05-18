"""This script scans GitHub Actions workflow and action definition files for 'uses:' statements."""

import logging
from enum import StrEnum
from typing import Annotated

import typer

from gh_action_pulse.actions import UniqGithubActions
from gh_action_pulse.full_list_of_existing_actions import FullListOfExistingActions
from gh_action_pulse.helpers.constants import SEARCH_CONFIGS

logger = logging.getLogger(__name__)
app = typer.Typer()


class LogLevel(StrEnum):
    """Logging levels supported by the CLI."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@app.command(help="Scan for 'uses:' statements in GitHub Actions workflow and action definition files.")
def main(
    log_level: Annotated[
        LogLevel,
        typer.Option(
            "--log_level", help="Set the logging level (e.g., DEBUG, INFO, WARNING, ERROR, CRITICAL)", show_default=True
        ),
    ] = LogLevel.INFO,
) -> None:
    """Main function to scan for 'uses:' statements and analyze them."""
    logging.basicConfig(level=getattr(logging, log_level), format="%(message)s")
    full_list_of_existing_actions = FullListOfExistingActions(
        search_configs=SEARCH_CONFIGS,
    )
    results = full_list_of_existing_actions.get_results()

    uniq_github_actions = UniqGithubActions()
    uniq_github_actions.init_from_full_list(results)

    uniq_github_actions.get_fully_qualified()


# Run the main function when the script is executed directly (useful for vscode debugger)
if __name__ == "__main__":
    app()
