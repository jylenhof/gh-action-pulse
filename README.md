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
4. Selects the newest SemVer tag that is at least `--min-age` days old (falling back to non-SemVer version tags such as `v1` or `v0.6` when the repository has no SemVer tag).
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

## Using it in GitHub Actions

`gh-action-pulse` is a CLI. Two complementary workflows cover the usual split:

1. **Policy check** on pull requests and the default branch: `--dry-run` fails only when an action is too old, runs on Node.js below 24, or is archived. Proposed SHA pins and redirects do **not** fail the job.
2. **Scheduled pull request**: apply rewrites and open a PR when files actually changed. Routine version bumps on already-pinned actions can stay with Dependabot.

The YAML below is a simplified starting point (`pip` + `GITHUB_TOKEN`). This repository runs fuller versions (mise, GitHub App token, extra cleanup): [`.github/workflows/gh-action-pulse.yml`](.github/workflows/gh-action-pulse.yml) and [`.github/workflows/gh-action-pulse-pr.yml`](.github/workflows/gh-action-pulse-pr.yml).

### Policy check (CI)

Use a high `--max-age` so the job stays green while Dependabot or the scheduled workflow refresh pins. It should fail when an upstream tag is genuinely stale (`exit 5`) or the action (including composite dependencies) still runs on Node.js below 24 (`exit 3`). Archived upstream repositories also fail the run (`exit 4`).

`--min-age 7` and `--minimum-nodejs-version 24` are already the CLI defaults; they are spelled out here so the policy is obvious in the workflow file. `--min-age 7` also matches the scheduled recipe and a typical Dependabot cooldown.

```yaml
name: Actions policy

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  gh-action-pulse:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1

      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.14"

      - name: Install gh-action-pulse
        run: pip install gh-action-pulse

      - name: Check action freshness and Node.js runtime
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh-action-pulse --dry-run \
            --min-age 7 \
            --max-age 365 \
            --minimum-nodejs-version 24
```

### Scheduled pull request

Run without `--dry-run` on a weekly schedule (and on demand). `peter-evans/create-pull-request` opens a PR only when `gh-action-pulse` wrote changes; it no-ops on a clean tree.

`--min-age 7` waits out brand-new tags. That pairs well with a Dependabot `cooldown` of about a week, so the two bots are not racing to adopt a tag that appeared yesterday.

```yaml
name: Update Actions pins

on:
  schedule:
    - cron: "0 10 * * 3"
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  gh-action-pulse-pr:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          ref: ${{ github.event.repository.default_branch }}

      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.14"

      - name: Install gh-action-pulse
        run: pip install gh-action-pulse

      - name: Update action references
        id: pulse
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          set +e
          gh-action-pulse \
            --min-age 7 \
            --max-age 365 \
            --minimum-nodejs-version 24
          status=$?
          echo "exit-code=${status}" >> "$GITHUB_OUTPUT"
          exit 0

      - uses: peter-evans/create-pull-request@5f6978faf089d4d20b00c7766989d076bb2fc7f1 # v8.1.1
        with:
          commit-message: "chore: update GitHub Actions references"
          branch: chore/gh-action-pulse
          title: "chore: update GitHub Actions references"
          body: |
            Automated pin and redirect updates from `gh-action-pulse`.
            Routine version bumps on already-pinned actions are still
            expected from Dependabot.

      - name: Fail on gh-action-pulse errors
        if: steps.pulse.outputs.exit-code != '0'
        env:
          PULSE_EXIT_CODE: ${{ steps.pulse.outputs.exit-code }}
        run: exit "$PULSE_EXIT_CODE"
```

Pulse writes rewrites first, then exits non-zero on Node.js or `--max-age` failures. The steps above still open the PR, then fail the job so a stale or too-old Node.js action stays visible.

Pulse always rewrites files under `.github/workflows`. The default `GITHUB_TOKEN` cannot push workflow-file changes, and pull requests it opens do not start other workflows. For a production bot (including this repository), use a GitHub App token with `contents: write`, `pull-requests: write`, and `workflows: write`, or a fine-grained PAT with the equivalent permissions. See [`.github/workflows/gh-action-pulse-pr.yml`](.github/workflows/gh-action-pulse-pr.yml) for the App-token variant.

### Dependabot

Keep a `github-actions` Dependabot update (optionally grouped minor/patch with a cooldown). Dependabot bumps existing `owner/repo@sha` pins when a newer release exists. `gh-action-pulse` additionally:

- converts `owner/repo@v2` / `@main` into a pinned SHA with a version comment;
- rewrites redirected action repositories to their canonical name;
- ignores tags younger than `--min-age` when choosing a recommendation;
- fails the policy job on Node.js runtime, `--max-age`, or archived upstreams.

The two overlap on “newer SHA for the same action”. That is expected. Pulse PRs should stay rare if Dependabot is healthy.

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
- `6`: a `uses:` reference does not exist upstream (neither a branch, a tag nor a commit SHA); every invalid reference is listed with its `file:line`.

When multiple failing conditions are detected in the same run, the exit code with the lowest number is returned: authentication (`2`), archived repositories (`4`) and invalid references (`6`) stop the run early, and among end-of-run checks the Node.js exit code (`3`) takes precedence over stale tags (`5`).

## Limitations

- Local actions such as `./.github/actions/my-action` are not part of the GitHub API lookup flow.
- Recommendations work best with repositories exposing SemVer tags. Without them, the tool uses a degraded mode
  (non-SemVer version tags, then the pinned tag or branch pinned to its SHA) and lists those actions under
  "Degraded recommendations" (see [rules.md](rules.md#degraded-mode-no-usable-semver-tag)).
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
