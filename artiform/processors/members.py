from artiform.exceptions import ArtiformError, ConfigError, NotFoundError
from artiform.processors.base import SectionProcessor

KINDS = ("users", "groups")


class MembersProcessor(SectionProcessor):
    """Manages project membership for users and groups, including importing
    groups from LDAP when they do not exist in Artifactory yet.

    Entities are keyed as 'users:<name>' / 'groups:<name>'. Only the roles
    are compared; 'import_from_ldap' is a provisioning hint, not state.
    """

    section = "members"

    def desired_entities(self, project_key: str, cfg: dict) -> dict[str, dict]:
        entities = {}
        for kind in KINDS:
            for name, spec in (cfg.get(kind) or {}).items():
                if name != name.lower():
                    raise ConfigError(
                        f"{project_key}.members.{kind}.{name}: member names must "
                        "be lowercase (Artifactory normalizes names to lowercase, "
                        "which would make enforce remove the member every run)"
                    )
                if not isinstance(spec, dict) or not spec.get("roles"):
                    raise ConfigError(f"{project_key}.members.{kind}.{name} needs a non-empty 'roles' list")
                unknown = set(spec) - {"roles", "import_from_ldap"}
                if unknown:
                    raise ConfigError(
                        f"Unknown keys in {project_key}.members.{kind}.{name}: {', '.join(sorted(unknown))}"
                    )
                entities[f"{kind}:{name}"] = {
                    "roles": sorted(spec["roles"]),
                    "import_from_ldap": spec.get("import_from_ldap"),
                }
        return entities

    def current_entities(self, project_key: str, desired: dict[str, dict]) -> dict[str, dict]:
        entities = {}
        for kind in KINDS:
            try:
                members = self.client.list_project_members(project_key, kind)
            except NotFoundError:
                # Project does not exist yet (dry-run before creation).
                continue
            for member in members:
                entities[f"{kind}:{member['name']}"] = {"roles": sorted(member.get("roles", []))}
        return entities

    def entity_needs_update(self, current: dict, desired: dict) -> bool:
        return current["roles"] != desired["roles"]

    def describe_update(self, current: dict, desired: dict) -> str:
        return f"roles: {current['roles']} -> {desired['roles']}"

    def create_entity(self, project_key: str, name: str, desired: dict) -> None:
        kind, member_name = name.split(":", 1)
        if kind == "groups":
            self._ensure_group_exists(member_name, desired.get("import_from_ldap"))
        self.client.set_project_member(project_key, kind, member_name, desired["roles"])

    def update_entity(self, project_key: str, name: str, desired: dict, current: dict) -> None:
        kind, member_name = name.split(":", 1)
        self.client.set_project_member(project_key, kind, member_name, desired["roles"])

    def delete_entity(self, project_key: str, name: str) -> None:
        kind, member_name = name.split(":", 1)
        self.client.remove_project_member(project_key, kind, member_name)

    def _ensure_group_exists(self, group_name: str, ldap_setting: str | None) -> None:
        if self.client.get_group(group_name) is not None:
            return
        if not ldap_setting:
            raise ArtiformError(
                f"Group {group_name!r} does not exist in Artifactory; "
                "set 'import_from_ldap: <ldap-group-setting>' to import it, "
                "or create the group first"
            )
        self.client.import_ldap_group(group_name, ldap_setting)
