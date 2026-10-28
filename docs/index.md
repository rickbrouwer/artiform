# ArtiForm documentation

Config-as-code for JFrog Artifactory: describe your Artifactory **projects**,
their **repositories**, **members** (users and LDAP groups with project
roles) and **package cleanup policies** in YAML in Git, and let a CI pipeline
reconcile Artifactory against it.

## Contents

- [Running ArtiForm](running.md) - CLI, authentication, exit codes, GitLab CI
- [Configuration file](configuration.md) - file structure, defaults,
  environment variables, one file per team
- [Enforce (deletions)](enforce.md) - authoritative mode and its safety guards
- Reference, one page per section:
  - [Projects](reference/projects.md)
  - [Repositories](reference/repositories.md) - including generated
    repositories and sharing with other projects
  - [Members](reference/members.md) - users, groups, LDAP import
  - [Cleanup policies](reference/cleanup_policies.md) - "Retention Policies"
    in the Artifactory UI; including generated policies

## How it works

For every project in the config, ArtiForm compares the desired state (your
YAML) with the current state (the REST APIs) and creates, updates or deletes
entities to close the gap. Three properties shape everything:

- **Asymmetric comparison**: only fields present in your config are compared.
  Server-side defaults and server-populated fields never cause spurious
  updates, and you only manage the fields you care about.
- **Passthrough fields**: repository and cleanup-policy entities are passed to
  the API as-is (snake_case in YAML, converted to the API's camelCase), so
  any field the REST API supports works without ArtiForm needing to know it.
- **Opt-in deletions**: nothing is ever deleted unless a section sets
  `enforce: true` (or the top level sets `enforce_projects: true`). See
  [Enforce](enforce.md).

## Requirements

- Artifactory self-hosted 7.x with a license that includes Projects.
- Package cleanup policies additionally require Artifactory >= 7.98.7 with an
  Enterprise X or Enterprise+ license;
  `included_package_versions` requires >= 7.125.7.
- An access token of a platform admin (see [Running](running.md)).

## Examples

- [examples/artiform.yml](../examples/artiform.yml) - a complete
  single-file config
- [examples/multi-team](../examples/multi-team) - one file per team, with a
  platform-owned `shared` project for central remotes

The GitLab CI pipeline that runs ArtiForm from a config repo is documented
in [Running](running.md#gitlab-ci).
