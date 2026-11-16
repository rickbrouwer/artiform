# Development

```
python -m venv .venv && . .venv/bin/activate
pip install -e . --group dev      # runtime deps, pytest and the lint tools
pytest
```

The tests run straight from source (`pytest.ini_options.pythonpath` puts the
repo root on `sys.path`), so an editable install is a convenience, not a
requirement.

`pytest` runs the unit tests in `tests/unit`, which exercise everything
against a `FakeClient`. The [acceptance tests](#acceptance-tests) in
`tests/acceptance` run against a real Artifactory and are started explicitly.

## Acceptance tests

`tests/acceptance` runs ArtiForm against a real Artifactory in Docker:

```
export $(tests/acceptance/artifactory.sh up)   # starts Artifactory, prints ARTIFACTORY_URL/TOKEN
pytest tests/acceptance -v -rs
tests/acceptance/artifactory.sh down
```

`artifactory.sh up` starts `docker-compose.yml` (Artifactory plus the
PostgreSQL it requires), waits until it answers and creates an admin token;
`access.config.patch.yml` allows that with the admin password, since Access
otherwise rejects basic auth. Startup takes a few minutes. Without
`ARTIFACTORY_URL` and `ARTIFACTORY_TOKEN` the tests are skipped.

For now this is Artifactory OSS, which needs no license but supports almost
nothing ArtiForm manages (repository configuration, projects and cleanup
policies are Pro or Enterprise features), so the tests cover the HTTP layer,
a dry run and how ArtiForm reports those limits. Testing the project
management itself against a licensed Artifactory is the goal once a license
is available for CI.

In CI (`tests-acceptance.yml`) the job runs in the **Acceptance Tests**
GitHub environment with the maintainers as required reviewers, so a run
starts only after a maintainer approves it in the pull request.

## Static analysis

The code base is formatted and checked by tooling that runs in CI, so
reviews are about behavior, not style. The tools and their pinned
versions live in the `lint` dependency group of `pyproject.toml`:

| Tool | What it checks | Command |
|---|---|---|
| ruff format | Formatting (black-compatible, line length 120) | `ruff format artiform tests` |
| ruff check | pyflakes, pycodestyle, import order, pyupgrade, bugbear, simplify | `ruff check artiform tests` |
| mypy | Types in `artiform/`, including untyped function bodies | `mypy` |
| bandit | Common security mistakes in `artiform/` | `bandit -c pyproject.toml -q -r artiform` |
| codespell | Spelling in code and docs | `codespell` |

All of them are configured in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`,
`[tool.bandit]`, `[tool.codespell]`), so running them without arguments from
the repo root picks up the same settings as CI. `ruff check --fix` and
`ruff format` apply the fixable findings.

### Git hooks

`.pre-commit-config.yaml` runs the same tools on every commit:

```
pre-commit install
pre-commit run --all-files      # once, to check the whole tree
```

The hook versions match the `lint` group; bump both together.

### CI

GitHub Actions (`.github/workflows/`) runs `pytest` from source and one job
per lint tool, on the same pinned versions, so a finding fails the pipeline
the same way it fails the local hook: `tests-unit.yml` runs the tests on
every supported Python version (3.11 to 3.15), `static-analysis.yml` runs
ruff, mypy, bandit and codespell. Both run on pull requests and on pushes to
`main`. `tests-acceptance.yml` runs the [acceptance tests](#acceptance-tests)
against an Artifactory OSS started in Docker on the runner.
`release.yml` runs on a version tag and publishes the container image; see
[Releases](releases.md).

Dependabot (`.github/dependabot.yml`) opens update PRs for the Python
dependencies (the lint tools grouped into one PR), the Dockerfile base image,
the Artifactory and PostgreSQL images of the acceptance test stack and the
action versions, each only after a three-day cooldown since the release. It
does not read `.pre-commit-config.yaml`: after merging a lint-tools PR, run
`pre-commit autoupdate` and commit the new hook revs.

## Coding guidelines

- Python 3.11 is the oldest supported version; do not use newer syntax or
  stdlib features without a fallback. mypy checks against 3.11 whatever
  interpreter runs it.
- Config fields are snake_case in YAML and passed through to the APIs as-is
  (camelCase for `/artifactory` endpoints), so a new REST field normally
  needs no code.
- Every change comes with tests. The unit tests run against a `FakeClient`
  (`tests/unit/conftest.py`) that mimics the real server, including its
  quirks. If a change works around a new API quirk, teach `FakeClient` the
  same behavior so every test exercises it, and add an acceptance test where
  Artifactory OSS supports it.
- Nothing is deleted unless the user opted in with `enforce`. Changes that
  touch deletion, the dry-run output or the end-of-run summary need extra
  care and tests; see [Enforce](../enforce.md) for the guarantees users rely
  on.
- When behavior changes, update the matching page in `docs/` (one reference
  page per config section, plain Markdown, no build step), not only the
  README.
- Commit messages follow the `type: summary` convention (`feat:`, `fix:`,
  `docs:`, `chore:`, ...).

### Blame

Commits that only re-format code (for example after a ruff upgrade changes
its style) go in `.git-blame-ignore-revs`, as a separate commit with nothing
else in it, so `git blame` skips them. Enable it once per clone:

```
git config blame.ignoreRevsFile .git-blame-ignore-revs
```
