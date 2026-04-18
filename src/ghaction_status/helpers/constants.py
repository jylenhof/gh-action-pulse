"""Constants used across the ghaction_status project."""

from pathlib import Path

SEARCH_CONFIGS: list[tuple[Path, str]] = [
    (Path(".github/workflows"), "*.yml"),
    (Path(".github/workflows"), "*.yaml"),
    (Path(".github/actions"), "**/*.yml"),
    (Path(".github/actions"), "**/*.yaml"),
]
