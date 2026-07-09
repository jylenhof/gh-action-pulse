"""This script scans GitHub Actions workflow and action definition files for 'uses:' statements."""

import datetime
import logging
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from github import Auth, Github

from gh_action_pulse import __version__
from gh_action_pulse.actions import GithubAction, GithubActionArchivedError, UniqGithubActions
from gh_action_pulse.full_list_of_existing_actions import FullListOfExistingActions
from gh_action_pulse.helpers.constants import (
    DEFAULT_MAX_AGE,
    DEFAULT_MIN_AGE,
    DEFAULT_MINIMUM_NODEJS_VERSION,
    MAX_MIN_AGE,
    NODEJS_VERSION_ERROR_EXIT_CODE,
    SEARCH_CONFIGS,
)
from gh_action_pulse.helpers.github import get_github_token
from gh_action_pulse.nodejs_version import (
    NodeVersionChecker,
    NodeVersionViolation,
    report_node_version_violations,
)

logger = logging.getLogger(__name__)
app = typer.Typer()


def version_callback(*, value: bool) -> None:
    """Print the package version and exit when --version is passed."""
    if value:
        typer.echo(__version__)
        raise typer.Exit


def validate_min_age(min_age: int) -> int:
    """Validate that min_age is within the allowed range."""
    if min_age < 0:
        msg_min: str = "min_age must be 0 or greater."
        raise ValueError(msg_min)
    if min_age > MAX_MIN_AGE:
        msg_max: str = f"min_age cannot exceed {MAX_MIN_AGE} days."
        raise ValueError(msg_max)
    return min_age


def validate_min_age_cli(min_age: int) -> int:
    """Typer callback that validates min_age using shared business logic."""
    try:
        return validate_min_age(min_age)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def validate_max_age(max_age: int) -> int:
    """Validate that max_age is within the allowed range."""
    if max_age < 0:
        msg: str = "max_age must be 0 or greater."
        raise ValueError(msg)
    return max_age


def validate_max_age_cli(max_age: int) -> int:
    """Typer callback that validates max_age using shared business logic."""
    try:
        return validate_max_age(max_age)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def validate_minimum_nodejs_version(minimum_nodejs_version: int) -> int:
    """Validate that the minimum Node.js version is 0 or greater (0 disables the check)."""
    if minimum_nodejs_version < 0:
        msg: str = "minimum_nodejs_version must be 0 or greater."
        raise ValueError(msg)
    return minimum_nodejs_version


def validate_minimum_nodejs_version_cli(minimum_nodejs_version: int) -> int:
    """Typer callback that validates minimum_nodejs_version using shared business logic."""
    try:
        return validate_minimum_nodejs_version(minimum_nodejs_version)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


class LogLevel(StrEnum):
    """Logging levels supported by the CLI."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def check_node_versions(
    g: Github,
    results: dict[Path, list[dict[int, str]]],
    minimum_nodejs_version: int,
) -> list[NodeVersionViolation]:
    """Run the recursive Node.js version check and report any violations found."""
    if minimum_nodejs_version <= 0:
        return []
    checker = NodeVersionChecker(g, minimum_nodejs_version)
    violations = checker.check_scanned_uses(results)
    report_node_version_violations(violations, minimum_nodejs_version)
    return violations


def apply_recommended_updates(
    results: dict[Path, list[dict[int, str]]],
    uniq_github_actions: UniqGithubActions,
    *,
    dry_run: bool,
) -> None:
    """Rewrite scanned files with recommended action references (unless in dry-run mode)."""
    action_pattern: re.Pattern[str] = re.compile(r"^\s*[-]?\s{0,1}uses:\s*([^@\s]+)@([^\s#]+)(?:\s+#\s+(.+))?")
    for file, actions_list in results.items():
        logger.info("Reading all file to update github actions: %s", file)
        with Path.open(file) as f:
            file_lines = f.readlines()  # start with index 0
        logger.info("File read to update github actions: %s\n", file)
        for action_with_line in actions_list:
            for line_number, full_line in action_with_line.items():
                logger.info("Changing line number: %s", line_number)
                if match := action_pattern.search(full_line):
                    name: str = match.group(1)
                    actual_reference: str = match.group(2)
                    actual_description: str | None = match.group(3) if match.group(3) is not None else None
                    uniq_action = uniq_github_actions.get_item(name, actual_reference, actual_description)
                    logger.info("from:\n%s", file_lines[line_number - 1])
                    if replacement := uniq_action.get_updated_uses_replacement(actual_reference, actual_description):
                        file_lines[line_number - 1] = re.sub(
                            pattern=r"^(\s*[-]?\s{0,1}uses:\s*)(?:[^@\s]+)@[^\s#]+(?:\s+#\s+.+)?",
                            repl=r"\1" + replacement,
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


def warn_about_stale_actions(stale_actions: list[GithubAction], max_age: int) -> None:
    """Log warnings for actions whose min-age eligible tag exceeds the freshness threshold."""
    for action in stale_actions:
        if not action.has_semver_tags:
            logger.warning(
                "No semver tag found for action '%s'; cannot verify tag freshness within %d days.",
                action.name,
                max_age,
            )
        elif action.min_age_tag_date is not None:
            age_days = (datetime.datetime.now(datetime.UTC) - action.min_age_tag_date.astimezone(datetime.UTC)).days
            logger.error(
                "Min-age eligible tag for action '%s' is %d days old (limit: %d days).",
                action.name,
                age_days,
                max_age,
            )


@app.command(help="Scan for 'uses:' statements in GitHub Actions workflow and action definition files.")
def main(
    *,  # to avoid ruff alert
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
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
    min_age_in_days: Annotated[
        int,
        typer.Option(
            "--min-age",
            help=f"Minimum age of actions to consider (in days, max {MAX_MIN_AGE})",
            show_default=True,
            callback=validate_min_age_cli,
        ),
    ] = DEFAULT_MIN_AGE,
    max_age_in_days: Annotated[
        int,
        typer.Option(
            "--max-age",
            help="Fail when the min-age eligible upstream tag is older than this many days (0 disables the check)",
            show_default=True,
            callback=validate_max_age_cli,
        ),
    ] = DEFAULT_MAX_AGE,
    minimum_nodejs_version: Annotated[
        int,
        typer.Option(
            "--minimum-nodejs-version",
            help=(
                "Fail when an action (or any of its composite/local dependencies) runs on a "
                "Node.js version below this major version (0 disables the check)"
            ),
            show_default=True,
            callback=validate_minimum_nodejs_version_cli,
        ),
    ] = DEFAULT_MINIMUM_NODEJS_VERSION,
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

    try:
        uniq_github_actions.get_fully_qualified(g, min_age_in_days)
    except GithubActionArchivedError:
        raise typer.Exit(code=1) from None

    stale_actions = uniq_github_actions.get_stale_actions(max_age_in_days)
    warn_about_stale_actions(stale_actions, max_age_in_days)

    node_version_violations = check_node_versions(g, results, minimum_nodejs_version)

    apply_recommended_updates(results, uniq_github_actions, dry_run=dry_run)

    if node_version_violations:
        raise typer.Exit(code=NODEJS_VERSION_ERROR_EXIT_CODE)

    if stale_actions:
        raise typer.Exit(code=1)


# Run the main function when the script is executed directly (useful for vscode debugger)
if __name__ == "__main__":
    app()
