# gh-action-pulse

`gh-action-pulse` scans a repository for GitHub Actions `uses:` references, checks them against the GitHub API, and rewrites them to safer or more current references when a better upstream target exists.

It is aimed at repositories that want to keep GitHub Actions dependencies understandable, current, and pinned with more confidence.

## Key Features

- **Automatic scanning**: Detects `uses:` statements across workflow and reusable action files.
- **Reference classification**: Distinguishes whether an action is currently pinned to a commit SHA, tag, or branch.
- **Recommendation engine**: Looks up upstream metadata and recommends an updated reference based on available SemVer tags and branch state.
- **Repository redirect handling**: Rewrites moved repositories to their canonical name when GitHub reports a redirect.
- **Freshness checks**: Warns or fails when the newest eligible SemVer tag is older than your configured threshold.
- **Node.js runtime check**: Recursively verifies that actions, including composite and local composite dependencies, run on at least a configurable minimum Node.js version (`--minimum-nodejs-version`, default `24`), failing with a dedicated exit code (`3`) when an outdated runtime is detected.

## How It Works

For each detected `uses:` line, `gh-action-pulse`:

1. Finds GitHub Actions references in the configured workflow and action directories.
2. Queries the GitHub API for the referenced repository.
3. Detects whether the current reference is a tag, branch, or SHA.
4. Selects the newest SemVer tag that is at least `--min-age` days old.
5. Falls back to a branch recommendation when that is safer or newer than the eligible tag.
6. Rewrites redirected repositories to their canonical upstream name.

In practice, this means the tool can:

- convert branch or tag references into pinned SHAs annotated with the matching tag,
- preserve branch intent when no suitable tag exists,
- surface stale upstream action releases with a non-zero exit code.

## Example

Before:

```yaml
- uses: google-github-actions/auth@v2
```

After:

```yaml
- uses: google-github-actions/auth@<commit-sha> # v2.1.10
```

If an action repository has moved, the repository name may also be rewritten to the canonical upstream location.

## Setup

`gh-action-pulse` talks to the GitHub API.

Set a token explicitly:

```bash
export GITHUB_TOKEN=your_github_token_here
```

If `GITHUB_TOKEN` is not set, the tool can fall back to using the GitHub CLI authentication flow when `gh` is available.

The project currently requires `Python >= 3.14`.

## Installation

### Install from PyPI with `uv`

```bash
uv tool install gh-action-pulse
```

### Install from PyPI with `pipx`

```bash
pipx install gh-action-pulse
```

### Install the local checkout

```bash
uv tool install . --force --reinstall
```

## CLI Usage

Run against the current repository:

```bash
gh-action-pulse
```

Preview changes without writing files:

```bash
gh-action-pulse --dry-run
```

Require action tags to be at least 14 days old before they can be selected:

```bash
gh-action-pulse --min-age 14
```

Fail when the newest eligible tag is older than 180 days:

```bash
gh-action-pulse --min-age 14 --max-age 180
```

Require actions to run on at least Node.js 20:

```bash
gh-action-pulse --minimum-nodejs-version 20
```

Show more detail while debugging:

```bash
gh-action-pulse --log-level DEBUG
```

Print the installed version:

```bash
gh-action-pulse --version
```

## CLI Options

- `--dry-run`: show the updates without writing files.
- `--log-level`: set the logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
- `--min-age`: require tags to be at least this many days old before recommending them.
- `--max-age`: fail when the chosen `--min-age`-eligible upstream tag is older than this many days. Use `0` to disable the check.
- `--minimum-nodejs-version`: fail when an action, or any of its composite/local dependencies, runs on a Node.js major version below this value (default `24`). Use `0` to disable the check.
- `--version`: print the package version and exit.

## Limitations

- Local actions such as `./.github/actions/my-action` are not part of the GitHub API lookup flow.
- Recommendations depend on repositories exposing usable SemVer tags.
- Archived action repositories cause the command to exit with an error.
- The tool needs GitHub API access, so rate limits and authentication still apply.

## Roadmap

Possible future improvements:

- Maybe Separate unit tests with appropriate workflow (pytest) if checks takes times
- Add E2E tests with appropriate workflow (pytest and/or bats)
- Maybe configuration file with some ignore parameters or specific rules for some workflows (needs thinking)
- Change to versioned version of tools in mise.toml when near stable version (could depend on tools)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the code layout, local setup, and the full list of linters and checks run in CI.
