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

"""This script scans GitHub Actions workflow and action definition files for 'uses:' statements."""

import datetime
import logging
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from github import Auth, Github
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gh_action_pulse import __version__
from gh_action_pulse.actions import GithubAction, GithubActionArchivedError
from gh_action_pulse.full_list_of_existing_actions import FullListOfExistingActions
from gh_action_pulse.helpers.console import console, error, phase_status
from gh_action_pulse.helpers.constants import (
    ARCHIVED_ACTION_ERROR_EXIT_CODE,
    DEFAULT_MAX_AGE,
    DEFAULT_MIN_AGE,
    DEFAULT_MINIMUM_NODEJS_VERSION,
    GITHUB_TOKEN_ERROR_EXIT_CODE,
    MAX_MIN_AGE,
    NODEJS_VERSION_ERROR_EXIT_CODE,
    SEARCH_CONFIGS,
    STALE_TAG_ERROR_EXIT_CODE,
)
from gh_action_pulse.helpers.github import get_github_token
from gh_action_pulse.helpers.uses_line import USES_LINE_PATTERN, parse_trailing_comments
from gh_action_pulse.nodejs_version import (
    NodeVersionChecker,
    NodeVersionViolation,
    report_node_version_violations,
)
from gh_action_pulse.uniq_actions import UniqGithubActions

logger = logging.getLogger(__name__)
app = typer.Typer()


@dataclass(frozen=True)
class Replacement:
    """A single uses-line rewrite proposed or applied by the tool."""

    file: Path
    line_number: int
    old: str
    new: str


@dataclass
class UpdateResult:
    """Outcome of applying (or dry-running) recommended action updates."""

    files_changed: int = 0
    replacements: list[Replacement] = field(default_factory=list)


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


def configure_logging(log_level: LogLevel) -> None:
    """Configure logging with RichHandler for diagnostic output on stderr."""
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                show_path=False,
                rich_tracebacks=True,
                markup=False,
            )
        ],
        force=True,
    )


def check_node_versions(
    g: Github,
    uniq_github_actions: UniqGithubActions,
    minimum_nodejs_version: int,
) -> list[NodeVersionViolation]:
    """Run the recursive Node.js version check on recommended references and report violations."""
    if minimum_nodejs_version <= 0:
        return []
    checker = NodeVersionChecker(g, minimum_nodejs_version)
    started = time.perf_counter()
    violations = checker.check_actions(uniq_github_actions.get_actions())
    report_node_version_violations(
        violations,
        minimum_nodejs_version,
        elapsed=time.perf_counter() - started,
    )
    return violations


def _format_uses_change(old_line: str, new_line: str) -> str:
    """Build a compact old → new display for a rewritten uses line."""
    old_match = re.search(r"uses:\s*(.+)$", old_line.strip())
    new_match = re.search(r"uses:\s*(.+)$", new_line.strip())
    old_ref = old_match.group(1) if old_match else old_line.strip()
    new_ref = new_match.group(1) if new_match else new_line.strip()
    return f"{old_ref} → {new_ref}"


def apply_recommended_updates(
    results: dict[Path, list[dict[int, str]]],
    uniq_github_actions: UniqGithubActions,
    *,
    dry_run: bool,
) -> UpdateResult:
    """Rewrite scanned files with recommended action references (unless in dry-run mode)."""
    result = UpdateResult()
    started = time.perf_counter()
    for file, actions_list in results.items():
        logger.debug("Reading %s file to update github actions", file)
        with Path.open(file) as f:
            file_lines = f.readlines()  # start with index 0
        logger.debug("%s file read to update github actions\n", file)
        file_changed = False
        for action_with_line in actions_list:
            for line_number, full_line in action_with_line.items():
                if match := USES_LINE_PATTERN.search(full_line):
                    name: str = match.group("name")
                    actual_reference: str = match.group("reference")
                    actual_description, actual_comments = parse_trailing_comments(match.group("comments"))
                    uniq_action = uniq_github_actions.get_item(
                        name, actual_reference, actual_description, actual_comments
                    )
                    if replacement := uniq_action.get_updated_uses_replacement(
                        actual_reference=actual_reference,
                        actual_comments=actual_comments,
                    ):
                        old_line = file_lines[line_number - 1]
                        logger.debug("Changing line number: %s", line_number)
                        logger.debug("from:\n%s", old_line)
                        file_lines[line_number - 1] = re.sub(
                            pattern=(
                                r"^(?P<prefix>\s*[-]?\s{0,1}uses:\s*)"
                                r"(?:[^@\s]+)@[^\s#]+(?:\s+#\s+.+)?"
                            ),
                            repl=r"\g<prefix>" + replacement,
                            string=file_lines[line_number - 1],
                        )
                        new_line = file_lines[line_number - 1]
                        logger.debug("to:\n%s", new_line)
                        result.replacements.append(
                            Replacement(
                                file=file,
                                line_number=line_number,
                                old=old_line.rstrip("\n"),
                                new=new_line.rstrip("\n"),
                            )
                        )
                        file_changed = True
        if file_changed:
            result.files_changed += 1
            if dry_run:
                logger.debug("Dry Run Mode! So Would have normally update github actions in %s file", file)
            else:
                logger.debug("Writing these changes to update github actions in %s file", file)
                with Path.open(file, mode="wt") as f:
                    f.writelines(file_lines)
                logger.debug("End of writing %s file to update github actions\n", file)

    _print_updates_table(result, dry_run=dry_run, elapsed=time.perf_counter() - started)
    return result


def _print_updates_table(result: UpdateResult, *, dry_run: bool, elapsed: float | None = None) -> None:
    """Render a Rich table of proposed or applied uses-line rewrites."""
    if not result.replacements:
        phase_status("Applying updates…", "No changes needed", elapsed=elapsed)
        return

    count = len(result.replacements)
    status = f"{count} proposed" if dry_run else f"{count} applied"
    style = "yellow" if dry_run else "cyan"
    phase_status("Applying updates…", status, style=style, elapsed=elapsed)

    title = "Updates (dry-run)" if dry_run else "Updates"
    table = Table(title=title, show_header=True, header_style=style)
    table.add_column("File")
    table.add_column("Line", justify="right")
    table.add_column("Change")
    for replacement in result.replacements:
        table.add_row(
            str(replacement.file),
            str(replacement.line_number),
            Text(_format_uses_change(replacement.old, replacement.new)),
        )
    console.print(Panel(table, border_style=style))


def warn_about_stale_actions(
    stale_actions: list[GithubAction],
    max_age: int,
    *,
    elapsed: float | None = None,
) -> None:
    """Log warnings for actions whose min-age eligible tag exceeds the freshness threshold."""
    if max_age <= 0:
        return

    if not stale_actions:
        phase_status("Checking tag freshness…", "OK", elapsed=elapsed)
        return

    phase_status(
        "Checking tag freshness…",
        f"{len(stale_actions)} stale",
        style="yellow",
        elapsed=elapsed,
    )

    table = Table(title=f"Stale tags (max-age {max_age} days)", show_header=True, header_style="yellow")
    table.add_column("Action")
    table.add_column("Detail")

    for action in stale_actions:
        if not action.has_semver_tags:
            detail = f"No semver tag found; cannot verify freshness within {max_age} days."
            table.add_row(action.name, detail)
            logger.warning(
                "No semver tag found for action '%s'; cannot verify tag freshness within %d days.",
                action.name,
                max_age,
            )
        elif action.min_age_tag_date is not None:
            age_days = (datetime.datetime.now(datetime.UTC) - action.min_age_tag_date.astimezone(datetime.UTC)).days
            detail = f"{age_days} days old (limit: {max_age} days)"
            table.add_row(action.name, detail)
            logger.error(
                "Min-age eligible tag for action '%s' is %d days old (limit: %d days).",
                action.name,
                age_days,
                max_age,
            )
    console.print(table)


def _print_summary(
    *,
    update_result: UpdateResult,
    stale_actions: list[GithubAction],
    node_version_violations: list[NodeVersionViolation],
    dry_run: bool,
    exit_code: int,
) -> None:
    """Print a final Rich Panel summarizing the run outcome."""
    parts: list[str] = []
    update_count = len(update_result.replacements)
    if update_count:
        verb = "proposed" if dry_run else "applied"
        parts.append(f"{update_count} update{'s' if update_count != 1 else ''} {verb}")
    else:
        parts.append("no updates")

    if stale_actions:
        parts.append(f"{len(stale_actions)} stale tag{'s' if len(stale_actions) != 1 else ''}")
    if node_version_violations:
        parts.append(
            f"{len(node_version_violations)} Node.js violation{'s' if len(node_version_violations) != 1 else ''}"
        )

    parts.append(f"exit {exit_code}")
    border = "green" if exit_code == 0 else "red"
    console.print(Panel(" · ".join(parts), title="Summary", border_style=border))


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
            envvar="GH_ACTION_PULSE_DRY_RUN",
        ),
    ] = False,
    log_level: Annotated[
        LogLevel,
        typer.Option(
            "--log-level",
            help="Set the logging level (e.g., DEBUG, INFO, WARNING, ERROR, CRITICAL)",
            show_default=True,
            envvar="GH_ACTION_PULSE_LOG_LEVEL",
        ),
    ] = LogLevel.INFO,
    min_age_in_days: Annotated[
        int,
        typer.Option(
            "--min-age",
            help=f"Minimum age of actions to consider (in days, max {MAX_MIN_AGE})",
            show_default=True,
            callback=validate_min_age_cli,
            envvar="GH_ACTION_PULSE_MIN_AGE",
        ),
    ] = DEFAULT_MIN_AGE,
    max_age_in_days: Annotated[
        int,
        typer.Option(
            "--max-age",
            help="Fail when the min-age eligible upstream tag is older than this many days (0 disables the check)",
            show_default=True,
            callback=validate_max_age_cli,
            envvar="GH_ACTION_PULSE_MAX_AGE",
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
            envvar="GH_ACTION_PULSE_MINIMUM_NODEJS_VERSION",
        ),
    ] = DEFAULT_MINIMUM_NODEJS_VERSION,
) -> None:
    """Main function to scan for 'uses:' statements and analyze them."""
    configure_logging(log_level)

    try:
        token = get_github_token()
    except RuntimeError as e:
        error("Failed to get GitHub token")
        logger.exception("Failed to get GitHub token")
        raise typer.Exit(code=GITHUB_TOKEN_ERROR_EXIT_CODE) from e

    g = Github(auth=Auth.Token(token))

    scan_started = time.perf_counter()
    full_list_of_existing_actions = FullListOfExistingActions(
        search_configs=SEARCH_CONFIGS,
    )
    results = full_list_of_existing_actions.get_results()

    uniq_github_actions = UniqGithubActions()
    uniq_github_actions.init_from_full_list(results)
    phase_status(
        "Scanning workflows and action definitions…",
        "OK",
        elapsed=time.perf_counter() - scan_started,
    )
    console.print(
        f"  Found [cyan]{len(uniq_github_actions.get_actions())}[/cyan] unique actions "
        f"in [cyan]{len(results)}[/cyan] files"
    )

    try:
        uniq_github_actions.get_fully_qualified(g, min_age_in_days)
    except GithubActionArchivedError as exc:
        error(str(exc))
        _print_summary(
            update_result=UpdateResult(),
            stale_actions=[],
            node_version_violations=[],
            dry_run=dry_run,
            exit_code=ARCHIVED_ACTION_ERROR_EXIT_CODE,
        )
        raise typer.Exit(code=ARCHIVED_ACTION_ERROR_EXIT_CODE) from None

    stale_started = time.perf_counter()
    stale_actions = uniq_github_actions.get_stale_actions(max_age_in_days)
    warn_about_stale_actions(
        stale_actions,
        max_age_in_days,
        elapsed=time.perf_counter() - stale_started,
    )

    node_version_violations = check_node_versions(g, uniq_github_actions, minimum_nodejs_version)

    update_result = apply_recommended_updates(results, uniq_github_actions, dry_run=dry_run)

    if node_version_violations:
        _print_summary(
            update_result=update_result,
            stale_actions=stale_actions,
            node_version_violations=node_version_violations,
            dry_run=dry_run,
            exit_code=NODEJS_VERSION_ERROR_EXIT_CODE,
        )
        raise typer.Exit(code=NODEJS_VERSION_ERROR_EXIT_CODE)

    if stale_actions:
        _print_summary(
            update_result=update_result,
            stale_actions=stale_actions,
            node_version_violations=node_version_violations,
            dry_run=dry_run,
            exit_code=STALE_TAG_ERROR_EXIT_CODE,
        )
        raise typer.Exit(code=STALE_TAG_ERROR_EXIT_CODE)

    _print_summary(
        update_result=update_result,
        stale_actions=stale_actions,
        node_version_violations=node_version_violations,
        dry_run=dry_run,
        exit_code=0,
    )


# Run the main function when the script is executed directly (useful for vscode debugger)
if __name__ == "__main__":
    app()
