# Development

```
python -m venv .venv && . .venv/bin/activate
pip install -e . --group dev      # runtime deps, pytest and the lint tools
pytest
```

The tests run straight from source (`pytest.ini_options.pythonpath` puts the
repo root on `sys.path`), so an editable install is a convenience, not a
requirement.

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
`main`. `release.yml` runs on a version tag and publishes the container
image; see [Releases](releases.md).

Dependabot (`.github/dependabot.yml`) opens update PRs for the Python
dependencies (the lint tools grouped into one PR), the Dockerfile base image
and the action versions, each only after a three-day cooldown since the
release. It does not read `.pre-commit-config.yaml`: after merging a
lint-tools PR, run `pre-commit autoupdate` and commit the new hook revs.

## Coding guidelines

- Python 3.11 is the oldest supported version; do not use newer syntax or
  stdlib features without a fallback. mypy checks against 3.11 whatever
  interpreter runs it.
- Config fields are snake_case in YAML and passed through to the APIs as-is
  (camelCase for `/artifactory` endpoints), so a new REST field normally
  needs no code.
- Every change comes with tests. The suite runs against a `FakeClient`
  (`tests/conftest.py`) that mimics the real server, including its quirks.
  If a change works around a new API quirk, teach `FakeClient` the same
  behavior so every test exercises it.
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
