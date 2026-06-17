# gh-action-pulse

`gh-action-pulse` is a utility designed to monitor and analyze the health of GitHub Actions dependencies within a repository. It scans your workflow and action definition files to identify which actions are being used and updates them to the last existing tag using (./rules.md)

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

If you haven't one, there's a fallback which will create a token using gh command

You will need python >= 3.14 to make this program works correctly.

## Local Installation

```bash
uv tool install . --force --reinstall
```

## Installation from last pypi release

### Using uv

```bash
uv tool install gh-action-pulse
```

### Using pipx

```bash
pipx install gh-action-pulse
```

## Roadmap

Randoms items

- Maybe Separate unit tests with appropriate workflow (pytest)
- Add E2E tests with appropriate workflow (pytest and/or bats)
- Be able to check for nodejs version in upstream repo
- Be able to raise some warnings if there's no recent upstream tag within x days
- Maybe configuration file with some ignore parameters or specific rules for some workflows
- Check eventual redirection of action to update to new URL

## CONTRIBUTING

- Feel free to contribute ;-)

Jean-Yves
