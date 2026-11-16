import pytest

from artiform.exceptions import ApiError, NotFoundError


class FakeClient:
    """In-memory stand-in for ArtifactoryClient with the same method surface
    and semantics (camelCase payloads, 404 behavior)."""

    base_url = "https://fake.example.com"

    def __init__(self):
        self.projects: dict[str, dict] = {}
        self.repos: dict[str, dict] = {}
        self.repo_shares: dict[str, dict] = {}
        self.groups: dict[str, dict] = {}
        self.memberships: dict[tuple[str, str], dict[str, list[str]]] = {}
        self.policies: dict[str, dict] = {}
        self.cleanup_api_available = True
        self.fail_create_project = False
        self.calls: list[tuple] = []

    def _record(self, *call):
        self.calls.append(call)

    def called(self, name: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == name]

    # -- system ---------------------------------------------------------------

    def version(self) -> str:
        return "7.150.0"

    # -- projects ---------------------------------------------------------------

    def list_projects(self):
        return list(self.projects.values())

    def get_project(self, project_key):
        return self.projects.get(project_key)

    def create_project(self, payload):
        self._record("create_project", payload)
        if self.fail_create_project:
            raise ApiError(400, "project quota exceeded")
        self.projects[payload["project_key"]] = dict(payload)

    def update_project(self, project_key, payload):
        self._record("update_project", project_key, payload)
        self.projects[project_key] = dict(payload)

    def delete_project(self, project_key):
        self._record("delete_project", project_key)
        del self.projects[project_key]

    # -- repositories -------------------------------------------------------------

    def list_repositories(self, project_key=None):
        # Like the real API, the project filter returns both repos assigned
        # to the project and repos shared with it.
        result = []
        for key, cfg in self.repos.items():
            if project_key is None:
                result.append({"key": key})
                continue
            assigned = cfg.get("projectKey") == project_key
            shares = self.repo_shares.get(key)
            shared = bool(shares and (shares["all"] or project_key in shares["projects"]))
            if assigned or shared:
                result.append({"key": key})
        return result

    def get_repository(self, repo_key):
        config = self.repos.get(repo_key)
        if config is not None and "password" in config:
            # Like the real API: the password of a remote repo is returned
            # encrypted, never as the configured plaintext.
            config = {**config, "password": "AP2EncryptedByArtifactory"}
        return config

    def _check_virtual_members(self, config: dict) -> None:
        # Like the real API: a virtual may only include repos assigned to or
        # shared with its own project ("Virtual repository must include only
        # repositories from the same project it was created with").
        if config.get("rclass") != "virtual":
            return
        project_key = config.get("projectKey")
        for member in config.get("repositories", []):
            member_cfg = self.repos.get(member)
            shares = self.repo_shares.get(member, {"projects": set(), "all": False})
            if member_cfg is None or not (
                member_cfg.get("projectKey") == project_key or shares["all"] or project_key in shares["projects"]
            ):
                raise ApiError(
                    400,
                    "Virtual repository must include only repositories from "
                    f"the same project it was created with: {member}",
                )

    def create_repository(self, repo_key, payload):
        self._record("create_repository", repo_key, payload)
        self._check_virtual_members(payload)
        self.repos[repo_key] = {"key": repo_key, **payload}

    def update_repository(self, repo_key, payload):
        self._record("update_repository", repo_key, payload)
        merged = dict(self.repos[repo_key])
        # Mirror the real API: projectKey in an update payload is ignored.
        merged.update({k: v for k, v in payload.items() if k != "projectKey"})
        self._check_virtual_members(merged)
        self.repos[repo_key] = merged

    def delete_repository(self, repo_key):
        self._record("delete_repository", repo_key)
        del self.repos[repo_key]
        self.repo_shares.pop(repo_key, None)

    def attach_repository(self, repo_key, project_key, force=True):
        self._record("attach_repository", repo_key, project_key, force)
        self.repos[repo_key]["projectKey"] = project_key

    # -- project sharing ----------------------------------------------------------

    def _shares(self, repo_key):
        return self.repo_shares.setdefault(repo_key, {"projects": set(), "all": False, "read_only": False})

    def get_repository_project_status(self, repo_key):
        self._record("get_repository_project_status", repo_key)
        repo = self.repos.get(repo_key)
        if repo is None:
            return None
        shares = self.repo_shares.get(repo_key, {"projects": set(), "all": False, "read_only": False})
        return {
            "resource_name": repo_key,
            "assigned_to": repo.get("projectKey"),
            "environments": repo.get("environments", []),
            "shared_with_projects": sorted(shares["projects"]),
            "shared_with_all_projects": shares["all"],
            "shared_read_only": shares["read_only"],
        }

    def share_repository(self, repo_key, target_project_key, read_only):
        self._record("share_repository", repo_key, target_project_key, read_only)
        shares = self._shares(repo_key)
        shares["projects"].add(target_project_key)
        shares["read_only"] = read_only

    def unshare_repository(self, repo_key, target_project_key):
        self._record("unshare_repository", repo_key, target_project_key)
        self._shares(repo_key)["projects"].discard(target_project_key)

    def share_repository_with_all(self, repo_key, read_only):
        self._record("share_repository_with_all", repo_key, read_only)
        shares = self._shares(repo_key)
        shares["all"] = True
        shares["read_only"] = read_only

    def unshare_repository_with_all(self, repo_key):
        self._record("unshare_repository_with_all", repo_key)
        self._shares(repo_key)["all"] = False

    # -- groups -------------------------------------------------------------------

    def get_group(self, name):
        return self.groups.get(name)

    def import_ldap_group(self, name, ldap_group_setting):
        self._record("import_ldap_group", name, ldap_group_setting)
        self.groups[name] = {"name": name, "realm": "ldap"}

    # -- membership -----------------------------------------------------------------

    def list_project_members(self, project_key, kind):
        if project_key not in self.projects:
            raise NotFoundError(f"project {project_key} not found")
        members = self.memberships.get((project_key, kind), {})
        return [{"name": name, "roles": roles} for name, roles in members.items()]

    def set_project_member(self, project_key, kind, name, roles):
        self._record("set_project_member", project_key, kind, name, roles)
        self.memberships.setdefault((project_key, kind), {})[name] = list(roles)

    def remove_project_member(self, project_key, kind, name):
        self._record("remove_project_member", project_key, kind, name)
        del self.memberships[(project_key, kind)][name]

    # -- cleanup policies --------------------------------------------------------------

    def list_cleanup_policies(self, project_key):
        if not self.cleanup_api_available:
            raise NotFoundError("cleanup API not found")
        # Like the real API, the listing also returns global/system policies
        # (no projectKey) alongside the project's own, and carries the
        # projectKey in the summary when the policy declares one.
        return [
            {
                "key": key,
                **({"projectKey": policy["projectKey"]} if "projectKey" in policy else {}),
            }
            for key, policy in self.policies.items()
            if policy.get("projectKey") in (project_key, None, "")
        ]

    def get_cleanup_policy(self, policy_key):
        policy = self.policies.get(policy_key)
        if policy is None:
            return None
        # Like the real API, the GET response does not echo projectKey.
        return {k: v for k, v in policy.items() if k != "projectKey"}

    def create_cleanup_policy(self, policy_key, payload):
        if not self.cleanup_api_available:
            raise NotFoundError("cleanup API not found")
        self._record("create_cleanup_policy", policy_key, payload)
        assert payload.get("enabled") is False, "API requires enabled=false at creation"
        self.policies[policy_key] = dict(payload)

    def update_cleanup_policy(self, policy_key, payload):
        self._record("update_cleanup_policy", policy_key, payload)
        current = self.policies[policy_key]
        # Like the real API: a PUT may not change enablement, and a missing
        # 'enabled' field reads as false.
        if bool(payload.get("enabled")) != bool(current.get("enabled")):
            raise ApiError(400, "please use a dedicated endpoint to enable or disable a policy")
        current.update(payload)

    def set_cleanup_policy_enabled(self, policy_key, enabled):
        self._record("set_cleanup_policy_enabled", policy_key, enabled)
        self.policies[policy_key]["enabled"] = enabled

    def delete_cleanup_policy(self, policy_key):
        self._record("delete_cleanup_policy", policy_key)
        del self.policies[policy_key]


@pytest.fixture
def client():
    return FakeClient()
