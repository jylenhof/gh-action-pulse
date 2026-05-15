# gh-action-pulse

`gh-action-pulse` is a utility designed to monitor and analyze the health of GitHub Actions dependencies within a repository. It scans your workflow and action definition files to identify which actions are being used and provides insights into their versioning status.

## Key Features

- **Automatic Scanning**: Detects `uses:` statements across `.github/workflows` and `.github/actions`.
- **Reference Identification**: Determines if an action is pinned to a specific commit SHA, a tag, or a branch.
- **Update Recommendations**: Queries the GitHub API to compare your current references against the latest stable semantic version (SemVer) tags.
- **Metadata Insights**: Retrieves commit dates and reference types to help evaluate the "freshness" of your CI/CD dependencies.

## Setup

The tool interacts with the GitHub API and requires a GitHub Personal Access Token.

```bash
export GITHUB_TOKEN=your_github_token_here
```

## Local Installation

```bash
uv tool install . --force --reinstall
```

## Roadmap

Randoms items

- Maybe Separate unit tests with appropriate workflow (pytest)
- add check about GITHUB_TOKEN variable availability
- Add E2E tests with appropriate workflow (pytest and/or bats)
- Push wheel to pypi when sufficient interest/stability
- Be able to do modifications to actual workflows
- Be able to check for nodejs version in upstream repo
- Be able to raise some warnings if there's no recent upstream tag within x days
- Be able to pass the local emplacement of repo (today need to be in a local repository clone)
- Maybe configuration file with some ignore parameters or specific rules for some workflows
- Maybe implement typer to be able to pass some parameters
- Better logging
- Implement release please

## CONTRIBUTING

- Feel free to contribute ;-)

Jean-Yves
