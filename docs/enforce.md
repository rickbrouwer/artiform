# Enforce: authoritative mode and deletions

Without enforce, ArtiForm only creates and updates. Enforce makes the config
authoritative: whatever exists in Artifactory but not in the config gets
**deleted**.

## Per section

`enforce: true` inside `repositories`, `members` or `cleanup_policies`
deletes unmanaged entities of that section in that project:

```yaml
projects:
  team-x:
    repositories:
      enforce: true      # repos of team-x not listed below are deleted,
      ...                # INCLUDING ALL THEIR ARTIFACTS
```

## Whole projects

The top-level `enforce_projects: true` deletes projects that exist in
Artifactory but are not in the config, deleting their repositories first.

## Safety guards

These guards are built in; none of them can be switched off from the
config or the command line:

- Enforce is **opt-in** per section and for projects.
- `enforce: true` on a section with no entities is rejected, as is
  `enforce_projects: true` with an empty `projects` map: a config mistake
  must not translate into "delete everything".
- `enforce` and `enforce_projects` only accept literal booleans; a string
  (for example from environment variable substitution) is rejected.
- A `--project` filter disables `enforce_projects` for that run, because the
  filtered view would make every other project look unmanaged.
- With `include_projects`, a broken, empty or missing team file aborts the
  whole run before anything is changed, so a team's project is never deleted
  because its file failed to load.
- Repositories merely **shared with** a project are never touched by that
  project's enforce: ArtiForm verifies real ownership (the repo's own
  `projectKey`) before deleting, both in section enforce and in
  `enforce_projects`.
- Every run ends with a summary that repeats all (planned) deletions at
  WARNING level; always review a `--dry-run` before an apply with enforce
  enabled.
