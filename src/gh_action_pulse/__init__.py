"""Package for checking the status of GitHub Actions in a repository."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("gh-action-pulse")
except PackageNotFoundError:
    __version__ = "unknown"
