# Members

The `members` section manages who is a member of the project, with which
roles. Users and groups are managed separately:

```yaml
members:
  enforce: true            # memberships not listed here are removed
  groups:
    team-x-developers:
      import_from_ldap: corporate-ldap-groups   # name of the LDAP group setting
      roles: [Developer]
    team-x-release:
      import_from_ldap: corporate-ldap-groups
      roles: [Release Manager]
  users:
    alice:
      roles: [Project Admin]
```

`roles` takes the project roles as Artifactory names them. The predefined
ones are `Developer`, `Contributor`, `Viewer`, `Release Manager`,
`Security Manager` and `Project Admin`; custom roles work too. Role lists
are compared order-insensitively.

## LDAP groups

LDAP server settings and LDAP group settings are assumed to be configured
already (one-time setup in the UI or via the API). When a group listed under
`members.groups` does not exist in Artifactory and has
`import_from_ldap: <ldap-group-setting-name>`, ArtiForm imports it from LDAP
(equivalent to the UI's Import button, via `POST /access/api/v2/groups`) and
then assigns it to the project with the given roles. Group members appear as
users as they log in.

A group without `import_from_ldap` must already exist; otherwise the change
fails for that member and the run continues.

## Known behaviors

- Member names (users and groups) must be **lowercase**, matching how
  Artifactory normalizes them; a mixed-case name would make enforce remove
  and re-add the member on every run, so ArtiForm rejects it.
- `enforce: true` removes memberships (the user or group loses access to the
  project); it never deletes the user or group itself.
