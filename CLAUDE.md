# ArtiForm

Config-as-code tool (Python) that reconciles JFrog Artifactory against one
YAML file: projects, repositories, project members (users/LDAP groups with
roles) and package cleanup policies. User-facing documentation lives in
`docs/` (plain Markdown, one reference page per config section, rendered
directly by GitHub/GitLab; deliberately no mkdocs, so the docs need no
build step and stay readable in air-gapped mirrors);
README.md is a short landing page linking into it. When behavior changes,
update the matching `docs/` page, not just README.md.

## Architecture

- `artiform/cli.py` — argparse CLI; exit codes: 0 ok, 1 config/connection
  error, 2 one or more changes failed.
- `artiform/config.py` — YAML loading (including `include_projects` globs
  for one-file-per-team setups; strict on purpose, since a silently skipped
  team file plus enforce_projects would delete that team's project),
  `$VAR`/`${VAR}` environment variable substitution in string values (strict:
  an unset or empty variable and a malformed `${...}` reference abort the
  run, so an empty secret is never applied; `$$` escapes a literal dollar;
  substitution yields strings, so `enforce`/`enforce_projects` reject
  non-boolean values), validation, defaults merging, and the
  two generators: `repositories.generate` (package_types x maturities ->
  `<project>-<tech>-<maturity>-local` repos, maturity maps to DEV/PROD
  environment) and `cleanup_policies.generate` (package_types x rules ->
  `<tech>-<ruleName>` policies targeting the rule's maturity repo).
- `artiform/client.py` — single `requests.Session` wrapper around the
  Artifactory (`/artifactory/api`, camelCase) and Access (`/access/api`,
  snake_case) REST APIs. Retries on GET/PUT/DELETE only, never POST.
- `artiform/engine.py` — orchestration in two phases: first ensure-project
  for every project (so cross-project shares and virtuals never hit a
  missing project), then the section processors per project, with projects
  ordered by the processors' `project_dependencies` (`order_projects`; e.g.
  a project whose virtuals include another project's repos runs after it; a
  cycle warns and keeps config order).
  `enforce_projects` deletes unmanaged projects (their repos first).
  Per-entity error isolation; summary lists all deletions at WARNING level.
- `artiform/processors/` — one processor per config section. The base class
  contract is mandatory: `desired_entities` / `current_entities` (dicts keyed
  by natural identifier) drive create/update/delete, diffing, `--dry-run`
  output and `enforce` deletions. Comparison is asymmetric: only keys present
  in desired are compared, so server-populated fields never cause drift.
  `desired_entities` may return an ordered dict to control create order
  (repositories: non-virtuals first, then virtuals after their members);
  `validate_entity` rejects entities the API would refuse, in dry-run too
  (repositories: virtual members must exist and be visible to the project);
  `index_config` gives a processor the section config of every project in
  the run up front (cross-project checks, duplicate repo keys,
  `project_dependencies`).
- Config fields are snake_case everywhere and passed through to the APIs
  (converted to camelCase for `/artifactory` endpoints via `util.to_camel`).

## Development

- Tests: `pytest` (or `.venv/bin/pytest`). `tests/conftest.py` has a
  `FakeClient` that mimics real server behavior, including the quirks below;
  when you fix a new API quirk, teach FakeClient the same behavior so every
  test exercises it.
- Static analysis (like GitLabForm): `ruff format` + `ruff check` (line
  length 120; rules E, W, F, I, UP, B, SIM; B027 ignored because the
  processor hooks are deliberately empty non-abstract methods), `mypy`
  (`check_untyped_defs`), `bandit` and `codespell`, all configured in
  `pyproject.toml` and pinned in its `lint` dependency group. The same
  versions are pinned in `.pre-commit-config.yaml`; bump both together.
  Run all of them before calling a change done; see
  `docs/contrib/development.md`. Pass loop variables to `_apply`/`_record`
  via `functools.partial`, not lambdas (bugbear B023).
- `pyproject.toml` deliberately uses the setuptools backend and
  `pytest.ini_options.pythonpath = ["."]`. Do not switch to hatchling or
  remove these: air-gapped CI environments cannot download build backends,
  so an install must keep working with `--no-build-isolation` and nothing
  but preinstalled setuptools, and the tests must run straight from source
  without installing the package.
- Release process mirrors GitLabForm on purpose: the version lives in
  `pyproject.toml` (mirrored into `tbump.toml` `current` by tbump; never
  edit either by hand). `artiform.__version__` reads pyproject.toml when it
  sits next to the package (source checkout; an editable install's metadata
  goes stale after a bump) and the installed metadata otherwise. Releases
  are cut with `pipx run tbump <version>`, which requires a
  `## <version>` entry in `docs/changelog.md`; see `docs/contrib/releases.md`.
  tbump is not a project dependency. Never hardcode the version elsewhere.

## Artifactory API quirks (each one broke a production run; keep them)

Verified against the target instance (self-hosted 7.161.x, Enterprise). All
are covered by regression tests.

- Auth is token-only (`ARTIFACTORY_TOKEN`, sent as `Authorization: Bearer`).
  The instance rejects Basic auth on `/access` endpoints with 401
  "Unsupported authentication method Basic". Never reintroduce
  username/password.
- Responses use vendor content types such as
  `application/vnd.org.jfrog.artifactory.system.Version+json`; anything with
  `json` in the Content-Type must be parsed as JSON. The reverse also
  happens: some write endpoints answer 200 with Content-Type
  `application/json` but a plain-text body (e.g. DELETE cleanup policy:
  "... was deleted successfully."). The client therefore tolerates a
  non-JSON body on PUT/POST/DELETE (the status code is the result) but
  raises ApiError, naming endpoint and body, on a GET (the body is the
  result; requests' JSONDecodeError is a RequestException and would
  otherwise bypass per-entity error isolation and kill the whole run).
- `GET /artifactory/api/repositories/{key}` answers **400** (not 404) for an
  unknown repo key; the client treats 400 as not-found there only.
- `projectKey` is silently ignored on repository updates; moving an existing
  repo into a project must use
  `PUT /access/api/v1/projects/_/attach/repositories/{repo}/{project}?force=true`.
  `rclass` and `packageType` are immutable (validated, also in dry-run).
- A remote repo's `password` is write-only: GET returns it encrypted, never
  the configured plaintext. The repositories processor skips the value
  comparison when the repo already has a password (adding a first password is
  still detected, logged masked as ****), keeps the plaintext out of change
  details/logs, and sends it with every create and update payload (a
  password-only rotation is therefore not detected).
- Cleanup policies (`/artifactory/api/cleanup/packages/policies`):
  - Create requires `enabled: false` in the body and
    `searchCriteria.includedProjects` present (absent -> server-side NPE 500).
    The processor injects `included_projects: []` automatically.
  - A PUT update must carry the **current** `enabled` value unchanged: a
    missing `enabled` reads as false and the API rejects enable/disable via
    update ("please use a dedicated endpoint"). Toggling goes through
    `POST .../policies/{key}/enablement`.
  - The GET response does **not** echo `projectKey`; the processor recognizes
    the project's own policies by the mandatory `<projectKey>-` key prefix.
    The listing also returns global/system policies
    (`system_repo_cleanup_policy`) which enforce must never touch.
  - GET responses carry null/0 placeholder condition fields
    (`createdBeforeInMonths` etc.). Day and month variants of a time
    condition are mutually exclusive in a PUT, as are time conditions and
    `keepLastNVersions`; the update path strips placeholders and drops the
    condition family the config does not use.
  - Policy keys must be prefixed `<projectKey>-` (auto-prefixed).
  - `includedPackageVersions` (e.g. `"*-*"` for pre-releases) requires
    Artifactory >= 7.125.7.
- Virtual repos have no `environments` field (the processor skips its [DEV]
  default for rclass virtual, or every run would flag a phantom update) and
  may only include repos assigned to or shared with their own project
  ("Virtual repository must include only repositories from the same project
  it was created with"). FakeClient enforces both.
- `GET /artifactory/api/repositories?project=X` returns both repos ASSIGNED
  to X and repos merely SHARED with X. Everything that derives ownership
  from that listing (section enforce, enforce_projects repo deletion) must
  verify the repo's own `projectKey` first, or a consuming project's enforce
  deletes another project's shared repo.
- Project Sharing of repos (`share_with` reserved key on a repo):
  - Share/unshare: `PUT/DELETE /access/api/v1/projects/_/share/repositories/{repo}[/{target}]`
    (`?readOnly=` on PUT); current state via
    `GET /access/api/v1/projects/_/repositories/{repo}` (`shared_with_projects`,
    `shared_with_all_projects`, `shared_read_only`).
  - `read_only` is **repo-level**, not per target; changing it must recreate
    the shares (unshare + share), there is no update call.
  - Only local and remote repos can be shared. On < 7.173, a read-only share
    of a remote does not trigger upstream fetches for consumers.
- LDAP group import uses `POST /access/api/v2/groups` with
  `import_from_ldap_group_setting` (equivalent to the UI Import button);
  member names must be lowercase because Artifactory normalizes them (a
  mixed-case name would make enforce remove the member every run).

## CI

- `.github/workflows/` (GitHub, the public home of the repo) and
  `.gitlab-ci.yml` (GitLab mirrors) run the same jobs: unit tests from
  source (only pytest and the runtime dependencies are installed; on GitHub
  across Python 3.11 to 3.14) plus one job per lint tool (ruff, mypy,
  bandit, codespell) from the `lint` dependency group. Keep them in sync.
  The `Dockerfile` builds the runnable image. Keep all of them free of
  organization-specific registries, labels, certificates and template
  includes: operators layer their own infrastructure on top (own base image
  mirror, CA bundle, pipeline templates).
- How a CONFIG repo (the repo holding `artiform.yml`) runs ArtiForm is
  documented inline in `docs/running.md` (GitLab CI section, `example.com`
  placeholders), like GitLabForm does; deliberately no example
  `.gitlab-ci.yml` file in `examples/`.

## Safety rules built into the tool (do not weaken)

- `enforce` is opt-in per section; deletions for repositories include all
  artifacts. `enforce: true` on an empty section is rejected, as is
  `enforce_projects: true` with zero projects defined.
- A `--project` filter disables `enforce_projects` for that run.
- Every run ends with a summary that lists all (planned) deletions at
  WARNING level; dry-run must show destructive actions before an apply.
