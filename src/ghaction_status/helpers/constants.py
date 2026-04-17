"""Constants used across the ghaction_status project."""

from pathlib import Path

SEARCH_CONFIGS: list[tuple[Path, str, str]] = [
    (Path(".github/workflows"), "*.yml", "uses:"),
    (Path(".github/workflows"), "*.yaml", "uses:"),
    (
        Path(".github/actions"),
        "**/*.yml",
        "uses:",
    ),
    (Path(".github/actions"), "**/*.yaml", "uses:"),
]
