# Cleanup policies

The `cleanup_policies` section manages the project's package cleanup policies
(`/artifactory/api/cleanup/packages/policies`). Requires Artifactory >= 7.98.7
with an Enterprise X or Enterprise+ license; a 404 from the API produces a
hint to that effect.

Policy keys are automatically prefixed with `<projectKey>-` as Artifactory
requires; write either the short or the full key in the config. Entities are
passed through to the API (snake_case -> camelCase), so any policy field
works.

In the Artifactory UI these policies live under **Retention Policies**, where
"Cleanup Policy" is the policy type. The config section follows the REST API
and the type name, hence `cleanup_policies`.

## Fields

```yaml
cleanup_policies:
  enforce: true
  docker-30d:                        # becomes team-x-docker-30d
    description: "Delete docker packages not downloaded for 30 days"
    cron_exp: "0 0 1 * * ?"          # when the policy runs (Quartz cron)
    duration_in_minutes: 120         # max runtime of one policy run
    skip_trashcan: false             # false = deleted versions go to trash
    search_criteria:
      package_types: [docker]
      repos: [team-x-docker-dev-local]
      included_packages: ["**"]
      # excluded_packages: ["com/example/keep-me"]
      # included_package_versions: ["*-*"]    # pre-releases; >= 7.125.7
      created_before_in_days: 30
      last_downloaded_before_in_days: 30
      # keep_last_n_versions: 5     # mutually exclusive with the time conditions
```

Day and month variants of a time condition (`created_before_in_days` vs
`created_before_in_months`) are mutually exclusive, as are time conditions
and `keep_last_n_versions`; ArtiForm handles the API's placeholder fields so
you only write the variant you use.

## Generated policies

`generate` expands into one policy per combination of `package_types` and
named `rules`. Each rule has a `maturity` selecting the generated repository
it targets (`<projectKey>-<tech>-<maturity>-local`, see
[generated repositories](repositories.md#generated-repositories)); all other
rule fields are merged into the policy as-is. The policy key becomes
`<projectKey>-<tech>-<ruleName>`.

```yaml
cleanup_policies:
  enforce: true
  generate:
    package_types: [maven, npm, helmoci, docker]
    rules:
      dev-prerelease-14d:
        maturity: dev
        cron_exp: "0 0 1 * * ?"      # daily at 01:00
        search_criteria:
          included_package_versions: ["*-*"]   # requires >= 7.125.7
          created_before_in_days: 14
          last_downloaded_before_in_days: 14
      dev-all-90d:
        maturity: dev
        cron_exp: "0 0 2 * * ?"      # daily at 02:00
        search_criteria:
          created_before_in_days: 90
          last_downloaded_before_in_days: 90
      prod-365d:
        maturity: prod
        cron_exp: "0 0 3 ? * 1"      # weekly, Sunday at 03:00
        search_criteria:
          created_before_in_days: 365
          last_downloaded_before_in_days: 365
```

Generated policies default to `included_packages: ["**"]` and behave exactly
like explicitly listed ones: `defaults.cleanup_policy` applies and enforce
counts them as managed. An explicit entry overrides fields of the generated
spec; use either the plain `<tech>-<ruleName>` key or the final prefixed
`<projectKey>-<tech>-<ruleName>` key.

## Known behaviors

- Policies are created disabled and enabled afterwards, as the API requires;
  enabling/disabling goes through the dedicated enablement endpoint.
- Policy updates merge the config on top of the current policy, so fields set
  outside the config are preserved.
- The policy listing also contains global/system policies
  (`system_repo_cleanup_policy`); ArtiForm recognizes the project's own
  policies and `enforce` never touches global ones.
- Deleting a policy does not delete any packages; it only stops the scheduled
  cleanup.
