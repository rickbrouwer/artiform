# Configuration file

The whole configuration lives in one YAML file (default `artiform.yml`),
optionally split into one file per team with
[`include_projects`](#one-config-file-per-team).

## Top-level keys

```yaml
config_version: 1         # required, exactly 1

artifactory:
  url: https://artifactory.example.com   # or env ARTIFACTORY_URL (env wins)
  # token: ...            # or (better) env ARTIFACTORY_TOKEN
  verify_ssl: true        # default true
  timeout: 30             # seconds, default 30

enforce_projects: false   # danger: true deletes projects not in this file,
                          # see docs/enforce.md

defaults: {}              # merged into every project / repository / policy

include_projects: null    # glob(s) for per-team files, see below

projects: {}              # project key -> project config
```

Unknown top-level keys are rejected, as are unknown keys in `artifactory`,
`defaults` and project settings, so typos fail the run instead of being
silently ignored.

## `defaults`

Defaults are deep-merged under every entity of the matching kind; the
entity's own fields win:

```yaml
defaults:
  project:                # merged into every project's settings
    admin_privileges:
      manage_members: true
      manage_resources: true
      index_resources: true
  repository:             # merged into every repository
    environments: [DEV]
  cleanup_policy:         # merged into every cleanup policy
    duration_in_minutes: 120
    skip_trashcan: false
```

## Environment variables

Any string value in the config may reference an environment variable as
`$NAME` or `${NAME}`; ArtiForm substitutes it at load time (also inside
included team files and `include_projects` patterns). This is the intended
way to keep secrets such as remote repository credentials out of Git: define
them as masked CI variables and reference them in the YAML:

```yaml
team-x-docker-remote:
  type: remote
  package_type: docker
  url: https://registry-1.docker.io
  username: $DOCKER_REMOTE_USERNAME
  password: $DOCKER_REMOTE_PASSWORD
```

Rules, strict by design:

- A referenced variable that is **not set or empty** aborts the run with
  exit 1 before anything is changed, so a typo cannot silently apply an
  empty credential.
- A malformed reference (`${NAME` without closing brace, `${}`) is an error.
- `$$` produces a literal dollar sign; a `$` not followed by a valid variable
  name (letters, digits, underscores, not starting with a digit) is left
  alone.
- Substitution always produces a *string*, so it cannot feed boolean fields:
  `enforce` and `enforce_projects` only accept literal `true`/`false`.

## One config file per team

With many teams, keep one main file (platform-owned) and one file per team:

```
artiform.yml          # artifactory, defaults, enforce_projects, shared project
projects/
  team-x.yml           # projects: { team-x: ... }
  team-y.yml
```

The platform-owned shared project may also live in its own included file
(`projects/common.yml`) instead of the main file; see below.

```yaml
# artiform.yml
include_projects: projects/*.yml   # glob(s), relative to this file
```

Team files may contain exactly one `projects:` mapping and nothing else, so
teams cannot override platform settings (`defaults`, `enforce_projects`,
`artifactory`). All files are loaded as one configuration, so
`enforce_projects` always sees the union: a project with a file is never
deleted. The loading is deliberately strict because of that same enforce:
a pattern matching no files, an invalid or empty team file, or the same
project key in two files aborts the whole run with exit 1 before anything
is changed.

Recommended GitLab setup: protect `artiform.yml` and give each team
CODEOWNERS ownership of its own `projects/<team>.yml`, so teams self-service
through merge requests (the MR pipeline dry-runs the full merged config and
shows all planned deletions). See [examples/multi-team](../examples/multi-team).

Central repositories that many teams consume (typically remotes) belong in a
platform-owned project, not in a team file; see
[Sharing repositories](reference/repositories.md#sharing-repositories-with-other-projects).
That project can be defined in the main file or in its own included file
(for example `projects/common.yml`). The processing order does not depend on
file names: ArtiForm creates all projects first and processes a project
after the projects whose repositories its virtuals include; see
[Ordering](reference/repositories.md#ordering).
