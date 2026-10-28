# Repositories

The `repositories` section of a project manages the repositories assigned to
it. Repository keys must start with `<projectKey>-` (Artifactory requires
the prefix).

Entities are passed through to the
[repository configuration REST API](https://jfrog.com/help/r/jfrog-rest-apis/repository-configuration-json),
so **any field the API supports works**. Write fields in `snake_case`;
ArtiForm converts to the API's camelCase. Two special keys exist: `type`
maps to `rclass`, and `share_with` is reserved for
[sharing](#sharing-repositories-with-other-projects).

## Common fields

```yaml
repositories:
  enforce: true                      # see docs/enforce.md

  team-x-maven-dev-local:
    type: local                      # local | remote | virtual | federated
    package_type: maven              # maven, npm, docker, helmoci, pypi, generic, ...
    environments: [DEV]              # default [DEV] (or defaults.repository)
    description: "Team X snapshots"
    notes: "internal notes, visible in the UI"
    includes_pattern: "com/example/**"  # comma-separated ant-style patterns;
    excludes_pattern: "**/*-tmp/**"  # artifacts must match includes and not excludes
    xray_index: true
    max_unique_snapshots: 10         # maven/gradle/ivy/sbt/nuget/docker

  team-x-docker-remote:
    type: remote
    package_type: docker
    url: https://registry-1.docker.io
    username: $DOCKER_REMOTE_USERNAME    # upstream credentials from CI
    password: $DOCKER_REMOTE_PASSWORD    # variables, see below

  team-x-maven-virtual:
    type: virtual
    package_type: maven
    repositories: [team-x-maven-dev-local, team-x-maven-prod-local]
    default_deployment_repo: team-x-maven-dev-local
```

## Remote repository credentials

Upstream `username`/`password` of a remote are ordinary passthrough fields;
reference them as CI variables via
[environment variable substitution](../configuration.md#environment-variables).

The `password` is write-only in the Artifactory API: a GET returns it
encrypted, never the configured value. ArtiForm therefore excludes its value
from drift detection (and from logs) and sends it along with every create and
update. Adding a password to a repository that had none is detected (shown
masked as `****`), but a rotation of an existing password alone is not; it is
applied the next time the repository is updated for any other reason. Change
another field (e.g. `description`) in the same commit to force it.

## Generated repositories

`generate` expands into one local repository per combination of
`package_types` and `maturities`, named `<projectKey>-<tech>-<maturity>-local`
following the [JFrog naming convention](https://jfrog.com/whitepaper/best-practices-structuring-naming-artifactory-repositories/).
The maturity maps to the repository's environment (`dev` -> `DEV`,
`prod` -> `PROD`).

```yaml
repositories:
  enforce: true
  generate:                  # team-x-<tech>-<maturity>-local per combination
    package_types: [maven, npm, helmoci, docker]
    maturities: [dev, prod]
  team-x-maven-prod-local:   # override one generated repo by its exact key
    xray_index: true
```

Generated repos behave exactly like explicitly listed ones:
`defaults.repository` applies, enforce counts them as managed, and an
explicit entry with the same key overrides fields of the generated spec.

## Ordering

A virtual repository may only include repositories that exist and are
assigned to or shared with its own project, so the order in which
repositories are created matters. ArtiForm derives it from the config,
so you do not have to:

- Within a project, local, remote and federated repositories are created
  in config order first; virtual repositories follow, each after the
  configured repositories it includes (a virtual may include another
  virtual). The order in the YAML, and the position of
  [generated](#generated-repositories) repositories, is irrelevant. Two
  virtuals that include each other are a config error.
- Across projects, a project whose virtuals include repositories of other
  projects is processed after those projects, so their repositories and
  shares exist by then. Projects without such a dependency keep their config
  order. A cycle between projects is logged as a warning and falls back to
  config order; a second run then converges.
- Before any section runs, every project entity is created or updated, so a
  share or a virtual never fails because the other project does not exist
  yet.

The members of a virtual that is about to be created or updated are
validated up front, in dry-run too: a member that does not exist (and is not
defined in the config), that belongs to a project that does not share it
with the virtual's project, or that is listed in another project's config
with a `share_with` not covering the virtual's project, is reported as a
failed change for that virtual instead of failing on apply. A member that
another project's config shares with the virtual's project is accepted even
when it does not exist yet, since the same run creates it. A virtual that is
already up to date is never validated, so drift in a member that ArtiForm
does not touch cannot fail the run.

With a `--project` filter only the projects in the run count as "defined in
the config": a share that a filtered-out project would create does not exist,
so the dry-run reports exactly what the apply would hit.

The same repository key defined in two projects is a config error (the key
is global in Artifactory, so the two projects would fight over it); the run
aborts with exit 1 before anything is changed.

## Sharing repositories with other projects

A repository (local or remote only) can be shared with other projects via the
reserved `share_with` key:

```yaml
share_with:
  projects: [team-x, team-y]   # explicit consumers, or:
  all: true                    # every project, including future ones
  read_only: true              # default true; repo-level, not per target
```

When `share_with` is present its content is authoritative: shares not listed
are removed (`share_with: {}` clears all shares). When absent, sharing is
left untouched. Target project members get access according to their roles in
their own project, capped to read-only when `read_only` is true.

### Recommended setup: a platform-owned project for central repositories

With many teams, do not duplicate remotes per team (each duplicate is a
separate cache and upstream connection) and do not let a regular team own a
repo that 50 others consume (team reorganizations then break everyone; only
the owner can delete the repo). Instead define one platform-owned project in
the main config file that owns the central repositories. Its key is your
choice (`shared` and `common` are typical); it becomes the prefix of every
repository in it, so pick it once and keep it short. The examples below use
`shared`:

```yaml
projects:
  shared:
    display_name: "Shared repositories (platform)"
    repositories:
      enforce: true
      # Universal remotes: every team gets them, now and in the future.
      shared-docker-remote:
        type: remote
        package_type: docker
        url: https://registry-1.docker.io
        username: $DOCKER_REMOTE_USERNAME
        password: $DOCKER_REMOTE_PASSWORD
        share_with:
          all: true
          read_only: false   # see note below
      # Niche remotes: an explicit list documents in Git who consumes it.
      shared-gradle-plugins-remote:
        type: remote
        package_type: maven
        url: https://plugins.gradle.org/m2
        share_with:
          projects: [team-x, team-y]
          read_only: false
```

Use `all: true` for remotes everyone needs (new projects are covered
automatically, no config change per team) and explicit `projects:` lists for
niche repos, where "who uses this" is valuable information in Git.

### Cluster-facing virtuals over team repositories

The same platform project can own the virtual repositories that serve as
the registry entry points for a container platform (one URL per stage to
allowlist on the clusters). A virtual may only include repositories assigned
to or shared with its own project, so this works in the *reverse* direction
of the remotes above: each team shares its docker locals with the platform
project, and the virtuals list them explicitly.

Use one virtual per stage: the prod virtual lists only `*-prod-local` repos,
so the production clusters can pull promoted images and nothing else. The
dev virtual contains everything *including* the prod locals, so promoted
images can also be spun up in dev (for example to reproduce a production
issue); the reverse direction stays impossible.

```yaml
# In a team file:
team-x-docker-dev-local:
  share_with:
    projects: [shared]
    read_only: true      # the clusters only pull
team-x-docker-prod-local:
  share_with:
    projects: [shared]
    read_only: true

# In the main file, project 'shared':
shared-docker-dev-virtual:
  type: virtual
  package_type: docker
  description: "Registry for the dev clusters: all team images"
  repositories:
    - team-x-docker-dev-local
    - team-x-docker-prod-local
    - team-y-docker-dev-local
    - team-y-docker-prod-local
shared-docker-prod-virtual:
  type: virtual
  package_type: docker
  description: "Registry for the prod clusters: promoted images only"
  repositories:
    - team-x-docker-prod-local
    - team-y-docker-prod-local
```

Name virtuals after their *content* (the tech, per the naming convention),
not after their consumer: repositories cannot be renamed, consumers can
change, and "for the Kubernetes clusters" belongs in the description.

The member lists are maintained by hand on purpose: onboarding a team is a
few reviewable lines in the platform file, next to the team's own shares.
Notes:

- Promotion itself (dev-local -> prod-local) is a pipeline concern, not
  ArtiForm's; project roles already gate it, since Developers can only
  write to DEV-environment repos and Release Managers to PROD.
- Virtual repositories cannot themselves be shared; the clusters' pull
  accounts get read access through a membership (e.g. Viewer) in the
  platform project.
- Virtual repositories have no `environments` field; ArtiForm only applies
  its `[DEV]` default to other repo types. Do not set `environments` on a
  virtual yourself either, including via `defaults.repository` (defaults
  merge into every repository, virtuals too).
- This converges in one run, also on a completely empty instance: ArtiForm
  creates all project entities before any repository, and processes the
  platform project's repositories after those of the teams whose
  repositories its virtuals include (see [Ordering](#ordering)). The
  platform project may therefore live in an included file as well (for
  example `projects/common.yml`); its position among the team files does
  not matter.

### Notes

- `read_only` applies to the repo's sharing as a whole; the API has no
  per-target flag. Changing it recreates the shares (unshare + share).
- For **remote** repos on Artifactory < 7.173: with `read_only: true`,
  requests through the share do not trigger upstream fetches, so uncached
  artifacts return 404 for consuming teams. Set `read_only: false` if
  consumers must be able to pull artifacts that are not cached yet (remotes
  accept no deploys, so this does not allow writes to the upstream).
- Sharing requires Artifactory >= 7.90.1 (`read_only` >= 7.94) and only
  works for local and remote repositories.
- A share targets a project that must exist. All project entities are
  created before any repository section runs, so a share to a brand-new
  project succeeds in the same run, whatever the order of the files or
  projects in the config.
- A consuming project's `enforce` never deletes repositories that are merely
  shared with it; ArtiForm verifies real ownership first (see
  [Enforce](../enforce.md#safety-guards)).
- Artifactory >= 7.173.8 adds *project-aware sharing* (consumers get an
  internal remote per project, enabling per-team usage attribution and
  policies). ArtiForm manages direct sharing; project-aware sharing
  currently requires a manual connect step per consuming project in the UI.

## Known behaviors

- `rclass` (`type`) and `package_type` are immutable; changing them is
  reported as an error (also in `--dry-run`) instead of silently recreating
  the repository.
- A configured repository that already exists outside the project is adopted
  via the attach API with `force=true`; the `projectKey` field is ignored on
  repository updates.
- With `enforce: true`, unmanaged repositories of the project are deleted
  **including all their artifacts**.
