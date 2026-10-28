# Projects

Each key under `projects:` is an Artifactory project. The project key must be
2-32 characters, lowercase alphanumeric or hyphens, starting with a letter
(Artifactory's own rules).

```yaml
projects:
  team-x:
    display_name: "Team X"          # default: the project key
    description: "Managed by ArtiForm"
    storage_quota_bytes: -1         # -1 = unlimited
    admin_privileges:
      manage_members: true
      manage_resources: true
      index_resources: true

    repositories: ...               # see reference/repositories.md
    members: ...                    # see reference/members.md
    cleanup_policies: ...           # see reference/cleanup_policies.md
```

All settings are optional; `defaults.project` from the
[configuration file](../configuration.md#defaults) is merged under them.

Behavior:

- A project that does not exist is created; an existing one is updated.
  Updates apply your fields on top of the current server state, so settings
  managed outside ArtiForm are preserved.
- If creating a project fails, its sections are skipped for that run (they
  would all fail anyway) and the run continues with the next project.
- Deleting projects is only done by
  [`enforce_projects`](../enforce.md#whole-projects).
