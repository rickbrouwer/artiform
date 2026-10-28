# Contributing to ArtiForm

Thanks for taking the time. Bug reports, API-quirk reports from other
Artifactory versions, documentation fixes and code changes are all welcome.

## Reporting a bug

Open a GitHub issue with:

- the ArtiForm version (first line of every run, or `artiform --version`),
- the Artifactory version and license tier (self-hosted 7.x; Projects and
  cleanup policies depend on the license),
- the relevant part of your `artiform.yml`, with hostnames and secrets
  removed,
- the log of a `--dry-run` with `-v` if the problem is a wrong diff, or the
  error summary at the end of the run if a change failed.

ArtiForm talks to a long list of Artifactory REST endpoints, and several of
them behave differently from their documentation. If you hit one of those on
a version we have not seen, the request and response details from `-v` are
the most useful thing you can share.

Do not report security problems in a public issue. Use the repository's
private vulnerability reporting ("Report a vulnerability" under the Security
tab) instead.

## Proposing a change

Open an issue first for anything beyond a small fix, so we can agree on the
approach before you spend time on it. Then:

1. Fork the repository and create a branch from `main`.
2. Set up a development environment and run the tests and the linters; see
   [Development](docs/contrib/development.md). `pre-commit install` runs
   the same checks on every commit.
3. Make your change, with tests. The test suite runs against a `FakeClient`
   (`tests/conftest.py`) that mimics the real server, including its quirks.
   If your change works around a new API quirk, teach `FakeClient` the same
   behavior so every test exercises it.
4. Update the documentation in `docs/` when behavior changes: one reference
   page per config section, plain Markdown, no build step.
5. Open a pull request against `main`. CI runs the tests on every supported
   Python version and each linter as a separate job, so a failure names the
   tool.

Please leave `docs/changelog.md` and the version in `pyproject.toml` alone;
the maintainer updates both when cutting a release
(see [Releases](docs/contrib/releases.md)).

## Ground rules

- Python 3.11 is the oldest supported version; do not use newer syntax or
  stdlib features without a fallback.
- Config fields are snake_case in YAML and passed through to the APIs as-is
  (camelCase for `/artifactory` endpoints), so a new REST field normally
  needs no code.
- Nothing is deleted unless the user opted in with `enforce`. Changes that
  touch deletion, the dry-run output or the end-of-run summary need extra
  care and tests; see [Enforce](docs/enforce.md) for the guarantees users
  rely on.
- Commit messages follow the `type: summary` convention
  (`feat:`, `fix:`, `docs:`, `chore:`, ...).

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
