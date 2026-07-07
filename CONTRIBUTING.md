# Contributing

Contributions are welcome. This document explains how the code is organized and which checks must pass before a change is merged.

## Development setup

The project targets **Python 3.14** and uses [`uv`](https://docs.astral.sh/uv/) for dependency management.

Install the runtime and development tools with `mise`:

```bash
mise install
uv sync --frozen
```

`mise` provides the non-Python tooling used by the repository (formatters, linters, GitHub Actions validators, and `prek`). Python dependencies are managed in `pyproject.toml` and locked in `uv.lock`.

Set a GitHub token when running the CLI locally:

```bash
export GITHUB_TOKEN=your_github_token_here
```

If `GITHUB_TOKEN` is not set, the CLI can fall back to `gh auth token` when the GitHub CLI is installed and authenticated.

## Code structure

The package lives under `src/gh_action_pulse/` and is installed as `gh-action-pulse`.

```text
src/gh_action_pulse/
├── main.py                        # Typer CLI entry point
├── actions.py                     # Action metadata and recommendation logic
├── full_list_of_existing_actions.py
└── helpers/
    ├── constants.py               # Scan paths and default CLI thresholds
    └── github.py                  # GitHub token retrieval

tests/
├── test_main.py
├── test_actions.py
├── test_full_list_of_existing_actions.py
└── test_helpers_github.py
```

### Module responsibilities

| Module | Role |
| --- | --- |
| `main.py` | Defines the `gh-action-pulse` CLI, validates options, orchestrates scanning, API lookups, file rewrites, and exit codes. |
| `full_list_of_existing_actions.py` | Scans workflow and reusable action files for `uses:` lines. |
| `actions.py` | Models each action reference, queries the GitHub API, and computes the recommended replacement. |
| `helpers/constants.py` | Centralizes scan locations (`.github/workflows`, `.github/actions`) and default `--min-age` / `--max-age` values. |
| `helpers/github.py` | Resolves `GITHUB_TOKEN` from the environment or from the `gh` CLI. |

### Data flow

1. `FullListOfExistingActions` scans configured directories and returns file/line matches.
2. `UniqGithubActions` deduplicates parsed references.
3. Each `GithubAction` fetches upstream metadata and computes a recommendation.
4. `main.py` rewrites matching lines in place, unless `--dry-run` is set.

Recommendation behavior is documented in [`rules.md`](rules.md). When changing update logic, update both the implementation and that document.

## Running the project locally

Run the CLI from the repository root:

```bash
uv run gh-action-pulse --dry-run
```

Run a single Python check or test directly:

```bash
uv run pytest tests/test_actions.py -k "test_name"
uv run ruff check src tests
uv run ty check
```

VS Code launch configurations are available in `.vscode/launch.json`.

## Verification

All checks are wired through [`prek`](https://github.com/j178/prek) in [`.pre-commit-config.yaml`](.pre-commit-config.yaml). This is the same entry point used in CI.

Run the full suite locally before opening a pull request:

```bash
prek run --all-files --show-diff-on-failure
```

Install the git hooks once so checks run automatically on commit:

```bash
prek install
```

### Python checks

| Tool | Command | Purpose |
| --- | --- | --- |
| Ruff format | `uv run ruff format` | Python formatting |
| Ruff lint | `uv run ruff check` | Python linting (`ALL` rules, with project-specific ignores in `ruff_defaults.toml`) |
| Pylint | `uv run pylint src tests` | Additional static analysis |
| ty | `uv run ty check` | Static type checking for `src/` and `tests/` |
| pytest | `uv run pytest` | Unit tests with coverage |

Pytest is configured in [`.pytest.toml`](.pytest.toml):

- parallel execution via `pytest-xdist` (`-nauto`)
- coverage reporting to terminal and `lcov.info`
- minimum coverage threshold of **80%** (`--cov-fail-under=80`)

Coverage settings live in [`.coveragerc.toml`](.coveragerc.toml).

### Repository hygiene checks

| Tool | Scope | Purpose |
| --- | --- | --- |
| commit-check | commits and branches | Conventional commit messages and branch naming |
| editorconfig-checker | repository files | Enforces `.editorconfig` |
| rumdl | `*.md` | Markdown linting |
| tombi | `*.toml` | TOML formatting and linting |
| shfmt / shellcheck | shell scripts | Shell formatting and linting |
| Built-in pre-commit hooks | mixed | Trailing whitespace, EOF, YAML, merge conflicts, private keys, executable checks |

Commit and branch rules are configured in [`.github/commit-check.toml`](.github/commit-check.toml). Dependabot branches and `release-please--branches--*` branches are explicitly allowed.

### GitHub Actions checks

These run on workflow and action YAML files:

| Tool | Purpose |
| --- | --- |
| actionlint | Workflow syntax and expression validation |
| pinact | Pins action references to SHAs |
| ghalint | GitHub Actions workflow linting |
| zizmor | Security-oriented workflow analysis |

## Continuous integration

Two workflows validate pull requests and pushes to `main`:

| Workflow | What it runs |
| --- | --- |
| [`.github/workflows/code-checks.yml`](.github/workflows/code-checks.yml) | `prek run --all-files`, then builds the Python wheel on success |
| [`.github/workflows/commit-check.yaml`](.github/workflows/commit-check.yaml) | commit-check on commit metadata |

A green PR generally means:

1. all `prek` hooks pass,
2. commit messages and branch names follow repository conventions,
3. the package still builds successfully.

## Making a change

1. Create a branch from `main`.
2. Make focused changes and add or update tests in `tests/`.
3. Run `prek run --all-files --show-diff-on-failure`.
4. Open a pull request with a short description of the behavior change.

If you touch recommendation logic, also update [`rules.md`](rules.md). If you add CLI options, update [`README.md`](README.md) and note planned options in [`CLI.md`](CLI.md) when relevant.
