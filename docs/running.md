# Running ArtiForm

```
artiform [-c artiform.yml] [--dry-run] [-p PROJECT]... [-v] [--version]
```

| Flag | Description |
|---|---|
| `-c, --config` | Path to the config file (default `artiform.yml`) |
| `-n, --dry-run` | Show what would change without changing anything |
| `-p, --project` | Only process this project (repeatable). Disables `enforce_projects` for the run |
| `-v, --verbose` | Debug logging, including request details |
| `--version` | Print the ArtiForm version and exit |

## Authentication

Authentication is token-only: set `ARTIFACTORY_TOKEN` (and `ARTIFACTORY_URL`)
as environment variables, or `artifactory.token`/`artifactory.url` in the
config file (environment wins). Both reference tokens and full identity
tokens work; they are sent as `Authorization: Bearer`, which works on both
the `/artifactory` and `/access` APIs (basic auth is rejected on `/access`
by many instances). The token must belong to a platform admin.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success, all changes applied (or planned, in dry-run) |
| `1` | Config or connection error; nothing was changed |
| `2` | One or more changes failed. The run continues past individual failures and reports a summary at the end |

## Output

Every run starts with the ArtiForm version, so a CI log always shows which
version produced the result:

```
INFO ArtiForm version: <version>
```

The project entities are created or updated first, then each project's
sections are announced with a progress counter, so a long run shows where
it is. Projects are processed in dependency order, not necessarily config
order (see
[Ordering](reference/repositories.md#ordering)):

```
INFO * Ensuring 3 project(s) exist
INFO ✅ project/platform: up to date
INFO ✅ project/team-a: up to date
INFO ➕ CREATE project/team-b
INFO * (1/3) Processing project: team-a
INFO * (2/3) Processing project: team-b
INFO * (3/3) Processing project: platform
```

Every change is logged with an icon: ➕ create, ✏️ update, 🗑️ delete,
✅ up to date, ❌ failure. The run ends with a summary of action counts, and
all (planned) deletions are repeated at WARNING level so they stand out:

```
WARNING ⚠️ Deletions planned (1):
WARNING   🗑️ team-x/repositories/team-x-old-local (not in config (enforce))
```

Review a `--dry-run` before every apply that could delete something.

## GitLab CI

ArtiForm is meant to run from the CI pipeline of the repository that holds
`artiform.yml` (the config repo), like GitLabForm: every merge request
dry-runs the full config so the MR shows exactly what will happen, and the
default branch applies it.

Jobs run in the ArtiForm image. Build it from this repository's `Dockerfile`
and push it to your own registry (the image contains only ArtiForm and its
dependencies; add your CA bundle or base-image mirror in your own build if
you need them). There is no supported way to install ArtiForm inside a job.

`.gitlab-ci.yml` in the config repo:

```yaml
stages:
  - plan
  - apply

.artiform:
  image: registry.example.com/artiform:latest
  variables:
    ARTIFACTORY_URL: https://artifactory.example.com

plan:
  extends: .artiform
  stage: plan
  script:
    - artiform --config artiform.yml --dry-run
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

apply:
  extends: .artiform
  stage: apply
  script:
    - artiform --config artiform.yml
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

CI/CD variables:

- `ARTIFACTORY_TOKEN`: an access token (reference or identity) of a platform
  admin, as a masked and protected variable, so it is only available to
  pipelines on protected branches.
- Every secret referenced from the YAML as `$VAR` (typically remote
  repository credentials, see
  [Configuration](configuration.md#environment-variables)) is an additional
  masked variable. An unset or empty variable fails the run before anything
  is changed.

Exit code `1` (config or connection error) and `2` (one or more changes
failed) both fail the job, so a broken MR cannot be merged unnoticed and a
partially failed apply is visible in the pipeline. The run continues past
individual failures and lists them in the summary at the end of the log.

With [one file per team](configuration.md#one-config-file-per-team), the
same pipeline covers all team files: protect `artiform.yml`, give each team
CODEOWNERS ownership of its own `projects/<team>.yml`, and the MR pipeline
dry-runs the merged config, including all planned deletions.
