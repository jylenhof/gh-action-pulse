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
- **Comment preservation**: Keeps extra trailing comments on `uses:` lines when rewriting references.
- **Per-line ignore hints**: Skip `--max-age`, `--min-age`, or the Node.js runtime check for a specific `uses:` line with a `# gh-action-pulse: ignore[...]` comment.
- **Per-line override hints**: Change `--max-age`, `--min-age`, or `--minimum-nodejs-version` for a specific `uses:` line with a `# gh-action-pulse: override[max-age=200]` comment.

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
- keep extra trailing comments such as ignore and override hints,
- skip `--max-age`, `--min-age`, or Node.js checks for a specific `uses:` line when an ignore hint is present,
- use a different `--max-age`, `--min-age`, or Node.js minimum for a specific `uses:` line when an override hint is present,
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

To skip a check for one `uses:` line, add a trailing ignore hint. Quoted and unquoted check ids are both accepted:

```yaml
- uses: actions/setup-node@abc123 # v4.4.0 # gh-action-pulse: ignore[max-age]
- uses: some/old-action@def456 # v1.2.3 # gh-action-pulse: ignore[max-age, min-age, nodejs-version]
```

The matching step is skipped for that line, the CLI reports the skip, and the run does not fail for that check. `ignore[min-age]` still rewrites the line, but selects the newest tag without waiting for `--min-age`. Unknown check ids are reported as warnings and do not skip anything. The hint stays on the line when the reference is rewritten.

To change a threshold for one `uses:` line instead of skipping the check, add an override hint. Several assignments can be comma-separated inside the brackets:

```yaml
- uses: actions/setup-node@abc123 # v4.4.0 # gh-action-pulse: override[max-age=200]
- uses: some/old-action@def456 # v1.2.3 # gh-action-pulse: override[max-age=200, min-age=3, nodejs-version=20]
```

The matching check still runs, but uses the per-line value. `ignore[...]` on the same line wins over `override[...]` for that check. Unknown keys and out-of-range values are reported as warnings and are not applied. The hint stays on the line when the reference is rewritten.

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

### Output

The CLI uses [Rich](https://github.com/Textualize/rich) for progress and summaries on stderr:

- a progress bar while enriching actions from the GitHub API (and while checking Node.js runtimes);
- colored phase lines for scan, freshness, and Node.js checks;
- a table of proposed or applied `uses:` rewrites (yellow header in `--dry-run`);
- a table of checks skipped by `# gh-action-pulse: ignore[...]` hints;
- a table of per-line thresholds from `# gh-action-pulse: override[...]` hints;
- a closing summary panel with update counts, warnings, and the exit code.

Routine per-file and per-action chatter is logged at `DEBUG`. Use `--log-level DEBUG` (or `WARNING` / `ERROR`) when you need diagnostic detail; warnings and errors still use Rich-formatted logging without repeating the main user-facing summary.

## CLI Options

- `--dry-run` (`GH_ACTION_PULSE_DRY_RUN`): show the updates without writing files.
- `--log-level` (`GH_ACTION_PULSE_LOG_LEVEL`): set the logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
- `--min-age` (`GH_ACTION_PULSE_MIN_AGE`): require tags to be at least this many days old before recommending them.
- `--max-age` (`GH_ACTION_PULSE_MAX_AGE`): fail when the chosen `--min-age`-eligible upstream tag is older than this many days. Use `0` to disable the check.
- `--minimum-nodejs-version` (`GH_ACTION_PULSE_MINIMUM_NODEJS_VERSION`): fail when an action, or any of its composite/local dependencies, runs on a Node.js major version below this value (default `24`). Use `0` to disable the check.
- `--version`: print the package version and exit.

CLI flags override the matching environment variables when both are set.

## Exit Codes

`gh-action-pulse` uses its exit code to signal the outcome of a run:

- `0`: the run completed and no failing condition was detected.
- `2`: GitHub authentication failed (`GITHUB_TOKEN` could not be resolved).
- `3`: a Node.js runtime problem was detected in the repository. When an action, or any of its composite/local composite dependencies, runs on a Node.js major version below `--minimum-nodejs-version` (default `24`), the tool logs an error and exits with status `3`. Set `--minimum-nodejs-version 0` to disable this check.
- `4`: a referenced upstream action repository is archived.
- `5`: a `--max-age` staleness failure occurred.

When multiple failing conditions are detected in the same run, the exit code with the lowest number is returned: authentication (`2`) and archived repositories (`4`) stop the run early, and among end-of-run checks the Node.js exit code (`3`) takes precedence over stale tags (`5`).

## Limitations

- Local actions such as `./.github/actions/my-action` are not part of the GitHub API lookup flow.
- Recommendations depend on repositories exposing usable SemVer tags.
- The tool needs GitHub API access, so rate limits and authentication still apply.

### Node.js version check (`--minimum-nodejs-version`)

The Node.js runtime check does not inspect every `uses:` line in the repository. In practice it:

- only starts from remote GitHub Actions referenced as `owner/repo@ref` (or `owner/repo/path@ref`) in `.github/workflows` and `.github/actions`;
- skips local actions such as `uses: ./.github/actions/my-action` because they do not match the `name@reference` pattern used during scanning;
- inspects the **recommended** upstream reference (the one the tool would update to), not the currently pinned reference when a recommendation exists;
- only flags JavaScript actions whose manifest declares `runs.using: nodeXX` (for example `node20`, `node24`);
- skips Docker actions (`docker://`), unresolvable references, missing manifests, and other non-`nodeXX` runtimes;
- walks composite actions recursively and checks nested `uses:` dependencies, including relative `./path` steps inside a **remote** composite action (resolved within that upstream repository);
- does not meaningfully check reusable workflows referenced as `uses: org/repo/.github/workflows/foo.yml@ref`, because it looks for `action.yml`/`action.yaml` manifests rather than workflow files.

Set `--minimum-nodejs-version 0` to disable this check entirely.

### Ignore hints (`# gh-action-pulse: ignore[...]`)

Ignore hints apply only to the `uses:` line they are written on. Supported check ids:

- `max-age`: skip the `--max-age` stale-tag failure for that line
- `min-age`: recommend the newest SemVer tag for that line without waiting for `--min-age`
- `nodejs-version`: skip the `--minimum-nodejs-version` check for that line, including its composite dependencies

The hint must be a trailing comment on the `uses:` line itself (a comment on the previous YAML line is not read). Extra comments are preserved when the line is rewritten. A config-file ignore list is not implemented yet; see the roadmap below.

### Override hints (`# gh-action-pulse: override[...]`)

Override hints apply only to the `uses:` line they are written on. Supported assignments (quoted and unquoted keys/values are both accepted):

- `max-age`: use this many days as the stale-tag limit for that line
- `min-age`: wait this many days before recommending a SemVer tag for that line
- `nodejs-version`: require this Node.js major version for that line, including its composite dependencies

Several assignments can be comma-separated: `override[max-age=200, min-age=3, nodejs-version=20]`. Duplicate keys keep the last value. `0` disables that check for the line. An `ignore[...]` hint for the same check on the same line takes precedence. Unknown keys and values outside the CLI bounds are reported as warnings and ignored.

The hint must be a trailing comment on the `uses:` line itself. Extra comments are preserved when the line is rewritten.

## Roadmap

Possible future improvements:

- Maybe Separate unit tests with appropriate workflow (pytest) if checks takes times
- Add E2E tests with appropriate workflow (pytest and/or bats)
- Change to versioned version of tools in mise.toml when near stable version (could depend on tools)

Potential future CLI options (to get the idea):

- `--config-file`: load configuration, including ignore parameters or specific rules for some workflows (needs thinking).
- `--only-workflow`: restrict scanning to a specific workflow.
- `--workflow-omit`: exclude specific workflows from scanning.
- `--github-action-omit`: exclude specific GitHub Actions from the checks.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the code layout, local setup, and the full list of linters and checks run in CI.
