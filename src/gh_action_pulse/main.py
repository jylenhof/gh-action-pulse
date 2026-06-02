"""This script scans GitHub Actions workflow and action definition files for 'uses:' statements."""

import logging
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from github import Auth, Github

from gh_action_pulse.actions import UniqGithubActions
from gh_action_pulse.full_list_of_existing_actions import FullListOfExistingActions
from gh_action_pulse.helpers.constants import SEARCH_CONFIGS
from gh_action_pulse.helpers.github import get_github_token

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
    *,  # to avoid ruff alert
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Dry run mode",
            show_default=True,
        ),
    ] = False,
    log_level: Annotated[
        LogLevel,
        typer.Option(
            "--log-level",
            help="Set the logging level (e.g., DEBUG, INFO, WARNING, ERROR, CRITICAL)",
            show_default=True,
        ),
    ] = LogLevel.INFO,
) -> None:
    """Main function to scan for 'uses:' statements and analyze them."""
    logging.basicConfig(level=getattr(logging, log_level), format="%(message)s")

    try:
        token = get_github_token()
    except RuntimeError as e:
        logger.exception("Failed to get GitHub token")
        raise typer.Exit(code=1) from e

    g = Github(auth=Auth.Token(token))

    full_list_of_existing_actions = FullListOfExistingActions(
        search_configs=SEARCH_CONFIGS,
    )
    results = full_list_of_existing_actions.get_results()

    uniq_github_actions = UniqGithubActions()
    uniq_github_actions.init_from_full_list(results)

    uniq_github_actions.get_fully_qualified(g)

    for file, actions_list in results.items():
        logger.info("Reading all file to update github actions: %s", file)
        with Path.open(file) as f:
            file_lines = f.readlines()  # start with index 0
        logger.info("File read to update github actions: %s\n", file)
        for action_with_line in actions_list:
            for line_number, full_line in action_with_line.items():
                logger.info("Changing line number: %s", line_number)
                action_pattern: re.Pattern[str] = re.compile(
                    r"^\s*[-]?\s{0,1}uses:\s*([^@\s]+)@([^\s#]+)(?:\s+#\s+(.+))?"
                )
                if match := action_pattern.search(full_line):
                    name: str = match.group(1)
                    actual_reference: str = match.group(2)
                    actual_description: str | None = match.group(3) if match.group(3) is not None else None
                    uniq_action = uniq_github_actions.get_item(name, actual_reference, actual_description)
                    logger.info("from:\n%s", file_lines[line_number - 1])
                    if uniq_action.recommended.reference and uniq_action.recommended.description:
                        replacement_pattern = (
                            r"\1@" + uniq_action.recommended.reference + " # " + uniq_action.recommended.description
                        )
                        file_lines[line_number - 1] = re.sub(
                            pattern=r"^(\s*[-]?\s{0,1}uses:\s*[^@\s]+)@[^\s#]+(?:\s+#\s+.+)?",
                            repl=replacement_pattern,
                            string=file_lines[line_number - 1],
                        )
                        logger.info("to:\n%s", file_lines[line_number - 1])
        if dry_run:
            logger.info("Dry Run Mode! So Would have normally update github actions in: %s", file)
        else:
            logger.info("Writing these changes to update github actions in: %s", file)
            with Path.open(file, mode="wt") as f:
                f.writelines(file_lines)
            logger.info("End of writing file to update github actions: %s\n", file)


# Run the main function when the script is executed directly (useful for vscode debugger)
if __name__ == "__main__":
    app()
