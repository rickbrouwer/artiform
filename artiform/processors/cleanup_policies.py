from artiform.exceptions import ArtiformError, ConfigError, NotFoundError
from artiform.processors.base import SectionProcessor
from artiform.util import deep_merge, strip_nones, to_camel, to_snake

LICENSE_HINT = (
    "the Package Cleanup Policies API requires Artifactory >= 7.98.7 with an Enterprise X or Enterprise+ license"
)

# The API rejects the day and month variant of a time condition together,
# and keep_last_n_versions combined with time conditions.
DAY_TO_MONTH_FIELDS = {
    "created_before_in_days": "created_before_in_months",
    "last_downloaded_before_in_days": "last_downloaded_before_in_months",
}
TIME_CONDITION_FIELDS = set(DAY_TO_MONTH_FIELDS) | set(DAY_TO_MONTH_FIELDS.values())


class CleanupPoliciesProcessor(SectionProcessor):
    """Manages project-scoped package cleanup policies.

    Policy keys are automatically prefixed with '<projectKey>-' as required
    by Artifactory. Fields use snake_case mirroring the API (cron_exp,
    search_criteria.package_types, ...) and are passed through.
    """

    section = "cleanup_policies"

    def desired_entities(self, project_key: str, cfg: dict) -> dict[str, dict]:
        prefix = f"{project_key}-"
        entities = {}
        for name, spec in cfg.items():
            policy_key = name if name.startswith(prefix) else f"{prefix}{name}"
            if policy_key in entities:
                raise ConfigError(
                    f"Cleanup policies in project {project_key!r} collide on "
                    f"key {policy_key!r} after prefixing; rename one of them"
                )
            payload = dict(spec)
            payload["key"] = policy_key
            payload["project_key"] = project_key
            payload.setdefault("enabled", True)
            # The API requires includedProjects to be present (an absent
            # field causes a server-side NullPointerException on create).
            criteria = dict(payload.get("search_criteria") or {})
            criteria.setdefault("included_projects", [])
            payload["search_criteria"] = criteria
            entities[policy_key] = payload
        return entities

    def current_entities(self, project_key: str, desired: dict[str, dict]) -> dict[str, dict]:
        try:
            policies = self.client.list_cleanup_policies(project_key)
        except NotFoundError:
            # Either the project does not exist yet (dry-run before creation)
            # or the cleanup API is unavailable; creation will surface the
            # latter with a clear error.
            return {}
        entities = {}
        prefix = f"{project_key}-"
        for summary in policies:
            key = summary["key"]
            # The listing can include global/system policies (such as
            # system_repo_cleanup_policy); only this project's own policies
            # are managed, so enforce never touches the others. Prefer an
            # explicitly declared projectKey (listing or GET response); the
            # GET does not always echo it, so fall back to the mandatory
            # '<projectKey>-' prefix to recognize our policies.
            declared = to_snake(summary).get("project_key")
            if declared is not None and declared != project_key:
                continue
            policy = self.client.get_cleanup_policy(key)
            if policy is None:
                continue
            policy = to_snake(policy)
            if declared is None:
                declared = policy.get("project_key")
            if declared is not None:
                if declared != project_key:
                    continue
            elif not key.startswith(prefix):
                continue
            policy["project_key"] = project_key
            # Normalize the server's null placeholder so the injected
            # included_projects: [] default does not diff forever.
            criteria = policy.get("search_criteria")
            if isinstance(criteria, dict) and criteria.get("included_projects") is None:
                criteria["included_projects"] = []
            entities[key] = policy
        return entities

    def create_entity(self, project_key: str, name: str, desired: dict) -> None:
        enabled = desired.get("enabled", True)
        # The API requires enabled=false at creation time.
        payload = {**desired, "enabled": False}
        try:
            self.client.create_cleanup_policy(name, to_camel(payload))
        except NotFoundError as exc:
            raise ArtiformError(f"Cannot create cleanup policy {name!r}: {LICENSE_HINT} ({exc})") from exc
        if enabled:
            self.client.set_cleanup_policy_enabled(name, True)

    def update_entity(self, project_key: str, name: str, desired: dict, current: dict) -> None:
        # PUT replaces the whole policy, so apply desired on top of the
        # current state to preserve fields not managed in the config. The
        # GET response carries null placeholders, so strip those first.
        desired_clean = {k: v for k, v in desired.items() if k != "enabled"}
        payload = deep_merge(
            strip_nones({k: v for k, v in current.items() if k != "enabled"}),
            desired_clean,
        )
        self._drop_conflicting_conditions(
            payload.get("search_criteria") or {},
            desired_clean.get("search_criteria") or {},
        )
        # The PUT body must carry the current enablement unchanged: a missing
        # 'enabled' reads as false and the API refuses enable/disable via
        # update. Toggling happens through the enablement endpoint below.
        payload["enabled"] = bool(current.get("enabled"))
        self.client.update_cleanup_policy(name, to_camel(payload))
        want_enabled = desired.get("enabled", True)
        if current.get("enabled") != want_enabled:
            self.client.set_cleanup_policy_enabled(name, want_enabled)

    @staticmethod
    def _drop_conflicting_conditions(criteria: dict, desired_criteria: dict) -> None:
        """Remove condition fields that only came from the current state and
        conflict with fields the config uses. Applies to every day/month
        pair, also when the config manages neither variant (the server keeps
        0-valued placeholders that survive strip_nones)."""
        for days_field, months_field in DAY_TO_MONTH_FIELDS.items():
            if days_field not in criteria or months_field not in criteria:
                continue
            if days_field in desired_criteria and months_field not in desired_criteria:
                criteria.pop(months_field)
            elif months_field in desired_criteria and days_field not in desired_criteria:
                criteria.pop(days_field)
            elif criteria[months_field] in (0, None):
                criteria.pop(months_field)
            elif criteria[days_field] in (0, None):
                criteria.pop(days_field)
            else:
                criteria.pop(months_field)
        uses_time = any(f in desired_criteria for f in TIME_CONDITION_FIELDS)
        if uses_time and "keep_last_n_versions" not in desired_criteria:
            criteria.pop("keep_last_n_versions", None)
        if "keep_last_n_versions" in desired_criteria:
            for field in TIME_CONDITION_FIELDS - set(desired_criteria):
                criteria.pop(field, None)

    def delete_entity(self, project_key: str, name: str) -> None:
        self.client.delete_cleanup_policy(name)
