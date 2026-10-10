# Copilot instructions

<!-- Keep in sync with AGENTS.md -->

## Tooling

All tools (prek, jactionlint, zizmor, ...) are managed by [mise](https://mise.jdx.dev/) in `.mise.toml`
and are not on the plain shell `PATH`. Run them through mise:

- `mise x -- prek run --all-files` to run the checks
- `mise x -- git commit ...` so the prek git hooks can find their tools
- `mise x gh@latest -- gh ...` for GitHub CLI operations (`gh` is not installed globally)
