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

"""Shared Rich console and styled helpers for user-facing CLI feedback."""

from rich.console import Console

console = Console(stderr=True)

_SECONDS_PER_MINUTE = 60


def format_duration(seconds: float) -> str:
    """Format a duration for compact CLI status lines."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < _SECONDS_PER_MINUTE:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(seconds, _SECONDS_PER_MINUTE)
    return f"{int(minutes)}m {secs:.0f}s"


def phase(message: str) -> None:
    """Print a cyan in-progress / phase label."""
    console.print(f"[cyan]●[/cyan] {message}")


def phase_status(label: str, status: str, *, style: str = "green", elapsed: float | None = None) -> None:
    """Print a phase completion line, optionally including elapsed time."""
    timing = f" [dim]({format_duration(elapsed)})[/dim]" if elapsed is not None else ""
    console.print(f"[cyan]●[/cyan] {label} [{style}]{status}[/{style}]{timing}")


def format_status_with_ignored(status: str, ignored_count: int) -> str:
    """Append an ignored-count suffix when at least one check was skipped."""
    if ignored_count <= 0:
        return status
    return f"{status} ({ignored_count} ignored)"


def success(message: str) -> None:
    """Print a green success message."""
    console.print(f"[green]{message}[/green]")


def warn(message: str) -> None:
    """Print a yellow warning message."""
    console.print(f"[yellow]{message}[/yellow]")


def error(message: str) -> None:
    """Print a red error message."""
    console.print(f"[red]{message}[/red]")
