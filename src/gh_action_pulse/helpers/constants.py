"""Constants used across the ghaction_status project."""

from pathlib import Path

SEARCH_CONFIGS: list[tuple[Path, str]] = [
    (Path(".github/workflows"), "*.yml"),
    (Path(".github/workflows"), "*.yaml"),
    (Path(".github/actions"), "**/*.yml"),
    (Path(".github/actions"), "**/*.yaml"),
]

DEFAULT_MIN_AGE = 20
MAX_MIN_AGE = 60
DEFAULT_MAX_AGE = 150

# Minimum Node.js major version GitHub Actions (and their recursive dependencies)
# are expected to run on. Set to 0 to disable the check.
DEFAULT_MINIMUM_NODEJS_VERSION = 24

# Dedicated exit code raised when at least one action runs on a Node.js version
# older than the configured minimum. Kept distinct from the generic exit code 1.
NODEJS_VERSION_ERROR_EXIT_CODE = 3
