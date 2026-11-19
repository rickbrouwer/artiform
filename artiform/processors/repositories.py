from artiform.diff import needs_update
from artiform.exceptions import ApiError, ArtiformError, ConfigError
from artiform.processors.base import SectionProcessor
from artiform.processors.repo_xray import current_xray_state, parse_xray_config, xray_payload
from artiform.util import to_camel, to_snake

# Fixed at creation time by the Repositories API.
IMMUTABLE_FIELDS = ("rclass", "package_type")

SHARE_KEYS = {"projects", "all", "read_only"}
# Config keys handled by other APIs than the repository configuration.
RESERVED_KEYS = ("share_with", "xray")
# Only local and remote repositories can be shared across projects.
SHAREABLE_RCLASSES = ("local", "remote")


def _without_password(entity: dict) -> dict:
    return {k: v for k, v in entity.items() if k != "password"}


def _share_state(projects, all_projects: bool, read_only) -> dict:
    """Normalized sharing state. read_only is a repo-level flag in the API;
    without any share it is meaningless, so it normalizes to None to avoid
    phantom diffs."""
    if not projects and not all_projects:
        read_only = None
    return {
        "projects": sorted(projects),
        "all": bool(all_projects),
        "read_only": read_only,
    }


def _shared_with(status: dict, project_key: str) -> bool:
    return bool(status.get("shared_with_all_projects")) or project_key in (status.get("shared_with_projects") or [])


def _virtual_members(name: str, spec: dict) -> list[str]:
    members = spec.get("repositories")
    if members is None:
        return []
    if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
        raise ConfigError(f"Virtual repository {name!r}: 'repositories' must be a list of repository keys")
    return members


def _order_by_dependency(project_key: str, entities: dict[str, dict]) -> dict[str, dict]:
    """Local, remote and federated repositories first (in config order), then
    virtual repositories after every configured repository they include.
    Artifactory rejects a virtual whose member does not exist yet, so the
    YAML order (or the position of generated repositories, which are
    appended after the explicit ones) must not decide the create order."""
    ordered = {k: v for k, v in entities.items() if v["rclass"] != "virtual"}
    virtuals = {k: v for k, v in entities.items() if v["rclass"] == "virtual"}
    state: dict[str, str] = {}

    def visit(key: str, path: list[str]) -> None:
        if state.get(key) == "done":
            return
        if state.get(key) == "visiting":
            cycle = " -> ".join(path[path.index(key) :] + [key])
            raise ConfigError(
                f"{project_key}.repositories: virtual repositories include each other in a cycle: {cycle}"
            )
        state[key] = "visiting"
        for member in _virtual_members(key, virtuals[key]):
            if member == key:
                raise ConfigError(f"Virtual repository {key!r} includes itself")
            if member in virtuals:
                visit(member, path + [key])
        state[key] = "done"
        ordered[key] = virtuals[key]

    for key in virtuals:
        visit(key, [])
    return ordered


class RepositoriesProcessor(SectionProcessor):
    """Manages the repositories assigned to a project.

    Config entities use snake_case field names mirroring the Repositories
    API (which itself is camelCase); 'type' maps to rclass. Fields are
    passed through to the API, so any repository setting is supported.

    'share_with' is a reserved key managing Project Sharing of the repo:
    when present, the configured target projects (or 'all') are
    authoritative and other shares are removed; when absent, sharing is
    left untouched. read_only applies to the repo's sharing as a whole
    (the API has no per-target flag); defaults to true for locals, false
    for remotes.

    'xray' is a reserved key managing the Xray indexing configuration of the
    repo (retention, path patterns) through the Xray repos_config API; when
    absent, Xray settings are left untouched.
    """

    section = "repositories"

    def __init__(self, client):
        super().__init__(client)
        # repo key -> (owning project, share_with state or None) for every
        # repository configured in this run; see index_config.
        self._configured: dict[str, tuple[str, dict | None]] = {}
        self._dependencies: dict[str, set[str]] = {}
        # Why Xray cannot be reached, probed once per run; None when it can.
        self._xray_unavailable: str | None = None
        self._xray_probed = False

    def index_config(self, sections: dict[str, dict]) -> None:
        """Remember who owns every configured repository and with which
        projects it is shared, so a virtual can list a repository of another
        project whose share this run still has to create (first run on an
        empty instance, in dry-run too), and derive which projects must be
        processed before which. Only the projects in the run are indexed: a
        share that a filtered-out project would create does not exist. A
        section that fails to parse is skipped here; the error is reported
        when its project is processed."""
        self._configured = {}
        self._dependencies = {}
        parsed: dict[str, dict[str, dict]] = {}
        for project_key, section in sections.items():
            cfg = {k: v for k, v in section.items() if k != "enforce"}
            try:
                desired = self.desired_entities(project_key, cfg)
            except ConfigError:
                continue
            parsed[project_key] = desired
            for repo_key, spec in desired.items():
                if repo_key in self._configured:
                    # Repository keys are global in Artifactory; two projects
                    # configuring the same key would fight over it.
                    raise ConfigError(
                        f"Repository {repo_key!r} is defined in both project "
                        f"{self._configured[repo_key][0]!r} and {project_key!r}"
                    )
                self._configured[repo_key] = (project_key, spec.get("share_with"))
        for project_key, desired in parsed.items():
            self._dependencies[project_key] = {
                self._configured[member][0]
                for name, spec in desired.items()
                if spec["rclass"] == "virtual"
                for member in _virtual_members(name, spec)
                if member in self._configured and self._configured[member][0] != project_key
            }

    def project_dependencies(self) -> dict[str, set[str]]:
        return self._dependencies

    def desired_entities(self, project_key: str, cfg: dict) -> dict[str, dict]:
        prefix = f"{project_key}-"
        entities = {}
        for repo_key, spec in cfg.items():
            if not repo_key.startswith(prefix):
                raise ConfigError(
                    f"Repository {repo_key!r} must start with {prefix!r} (Artifactory requires the project key prefix)"
                )
            payload = dict(spec)
            rclass = payload.pop("type", None) or payload.get("rclass")
            if rclass not in ("local", "remote", "virtual", "federated"):
                raise ConfigError(f"Repository {repo_key!r} needs 'type: local|remote|virtual|federated'")
            payload["rclass"] = rclass
            # Virtual repositories have no environments field in Artifactory;
            # a defaulted value would never be echoed back by a GET and would
            # flag a phantom update on every run.
            if rclass != "virtual":
                payload.setdefault("environments", ["DEV"])
            payload["project_key"] = project_key
            share_cfg = payload.pop("share_with", None)
            if share_cfg is not None:
                payload["share_with"] = self._parse_share_config(project_key, repo_key, rclass, share_cfg)
            xray_cfg = payload.pop("xray", None)
            if xray_cfg is not None:
                payload["xray"] = parse_xray_config(project_key, repo_key, rclass, xray_cfg)
                # Xray only configures repositories it indexes.
                if payload.setdefault("xray_index", True) is not True:
                    raise ConfigError(f"{project_key}.repositories.{repo_key}: 'xray' requires xray_index: true")
            entities[repo_key] = payload
        return _order_by_dependency(project_key, entities)

    @staticmethod
    def _parse_share_config(project_key: str, repo_key: str, rclass: str, share_cfg) -> dict:
        where = f"{project_key}.repositories.{repo_key}.share_with"
        if not isinstance(share_cfg, dict):
            raise ConfigError(f"{where} must be a mapping")
        unknown = set(share_cfg) - SHARE_KEYS
        if unknown:
            raise ConfigError(
                f"Unknown keys in {where}: {', '.join(sorted(unknown))} "
                f"(expected one of: {', '.join(sorted(SHARE_KEYS))})"
            )
        if rclass not in SHAREABLE_RCLASSES:
            raise ConfigError(f"{where}: only local and remote repositories can be shared")
        projects = share_cfg.get("projects") or []
        if not isinstance(projects, list) or not all(isinstance(item, str) for item in projects):
            raise ConfigError(f"{where}.projects must be a list of project keys")
        for flag in ("all", "read_only"):
            if flag in share_cfg and not isinstance(share_cfg[flag], bool):
                raise ConfigError(f"{where}.{flag} must be a boolean (true/false), got {share_cfg[flag]!r}")
        all_projects = share_cfg.get("all", False)
        if all_projects and projects:
            raise ConfigError(f"{where}: 'all' and 'projects' are mutually exclusive")
        if project_key in projects:
            raise ConfigError(f"{where}: a repository cannot be shared with its own project")
        # Read on a remote only serves its cache; a read-only share blocks upstream fetches.
        read_only = share_cfg.get("read_only", rclass != "remote")
        return _share_state(set(projects), all_projects, read_only)

    def current_entities(self, project_key: str, desired: dict[str, dict]) -> dict[str, dict]:
        entities = {}
        for summary in self.client.list_repositories(project_key=project_key):
            config = self.client.get_repository(summary["key"])
            if config is None:
                continue
            config = to_snake(config)
            # The project listing also returns repos merely SHARED with the
            # project; only repos actually assigned to it are managed here,
            # or enforce would delete another project's shared repo.
            if config.get("project_key") != project_key:
                continue
            entities[summary["key"]] = config
        # A configured repo may already exist outside the project (unassigned
        # or in another project); fetch it so it is adopted via attach instead
        # of failing on a duplicate-key create.
        for repo_key in set(desired) - set(entities):
            config = self.client.get_repository(repo_key)
            if config is not None:
                entities[repo_key] = to_snake(config)
        # Fetch the sharing and Xray state only for repos whose config manages it.
        if any("xray" in spec for spec in desired.values()):
            self._probe_xray()
        for repo_key, spec in desired.items():
            if repo_key not in entities:
                continue
            if "share_with" in spec:
                entities[repo_key]["share_with"] = self._current_share_state(repo_key)
            if "xray" in spec and self._xray_unavailable is None:
                entities[repo_key]["xray"] = self._current_xray_state(repo_key)
        return entities

    def _probe_xray(self) -> None:
        """Without Xray the repos_config GET answers the same 404 as "repo not
        configured yet", so a dry-run would plan a clean update that every
        apply then fails. One version call per run tells the two apart."""
        if self._xray_probed:
            return
        self._xray_probed = True
        try:
            self.client.xray_version()
        except ApiError as exc:
            self._xray_unavailable = f"Xray is not available: {exc}"

    def _current_xray_state(self, repo_key: str) -> dict | ApiError:
        # A failing GET must not abort the whole section; the error is kept
        # in place of the state and reported for this repo by validate_update,
        # in dry-run too.
        try:
            return current_xray_state(repo_key, self.client.get_xray_repo_config(repo_key))
        except ApiError as exc:
            return exc

    def _current_share_state(self, repo_key: str) -> dict:
        status = self.client.get_repository_project_status(repo_key)
        if status is None:
            return _share_state([], False, None)
        status = to_snake(status)
        return _share_state(
            status.get("shared_with_projects") or [],
            bool(status.get("shared_with_all_projects")),
            bool(status.get("shared_read_only")),
        )

    def entity_needs_update(self, current: dict, desired: dict) -> bool:
        # 'password' (remote repo upstream credential) is write-only: the API
        # returns it encrypted, never the configured plaintext, so comparing
        # the values would flag an update on every run. Adding a password to
        # a repo that has none must still be detected, so it is only skipped
        # when the current config carries one. It is always sent with the
        # create and update payloads.
        if "password" in current:
            desired = _without_password(desired)
        return super().entity_needs_update(current, desired)

    def describe_update(self, current: dict, desired: dict) -> str:
        # Keeps the plaintext password out of logs and dry-run output.
        details = super().describe_update(current, _without_password(desired))
        if "password" in desired and "password" not in current:
            masked = "password: <unset> -> ****"
            details = f"{details}; {masked}" if details else masked
        return details

    def validate_entity(
        self,
        project_key: str,
        name: str,
        desired: dict,
        desired_all: dict[str, dict],
        current_all: dict[str, dict],
    ) -> None:
        """A virtual may only include repositories assigned to or shared with
        its own project. Checked up front (also in dry-run) instead of
        letting the create or update fail on apply."""
        if "xray" in desired and self._xray_unavailable:
            raise ArtiformError(f"Repository {name!r} has an 'xray' configuration but {self._xray_unavailable}")
        if desired["rclass"] != "virtual":
            return
        for member in _virtual_members(name, desired):
            problem = self._virtual_member_problem(project_key, member, desired_all, current_all)
            if problem:
                raise ArtiformError(f"Virtual repository {name!r} includes {member!r}, which {problem}")

    def _virtual_member_problem(self, project_key, member, desired_all, current_all) -> str | None:
        # Managed by this project: created or updated earlier in this run
        # (desired is ordered so members come first).
        if member in desired_all:
            return None
        # Configured by another project in this run: that config decides who
        # owns the repo after the run (it attaches it), and an explicit
        # share_with is authoritative for its shares.
        owner, share = self._configured.get(member, (None, None))
        if owner is not None and owner != project_key:
            if share is not None:
                if share["all"] or project_key in share["projects"]:
                    return None
                return f"belongs to project {owner!r} and its share_with does not include project {project_key!r}"
            shared, exists = self._shared_on_server(project_key, member)
            if shared:
                return None
            if not exists:
                return (
                    f"does not exist yet; project {owner!r} creates it but its "
                    f"config does not share it with project {project_key!r}"
                )
            return f"belongs to project {owner!r} and is not shared with project {project_key!r}"
        # Already assigned to this project.
        current = current_all.get(member)
        if current is not None and current.get("project_key") == project_key:
            return None
        # Not explained by the config: ask the server.
        status = self.client.get_repository_project_status(member)
        if status is None:
            return "does not exist and is not defined in the config"
        status = to_snake(status)
        if status.get("assigned_to") == project_key or _shared_with(status, project_key):
            return None
        assigned = status.get("assigned_to")
        where = f"belongs to project {assigned!r}" if assigned else "is not assigned to any project"
        return f"{where} and is not shared with project {project_key!r}"

    def _shared_on_server(self, project_key: str, member: str) -> tuple[bool, bool]:
        """(shared with project_key, repo exists) according to the server."""
        status = self.client.get_repository_project_status(member)
        if status is None:
            return False, False
        return _shared_with(to_snake(status), project_key), True

    def validate_update(self, project_key: str, name: str, desired: dict, current: dict) -> None:
        if "xray" in desired and self._xray_unavailable:
            raise ArtiformError(f"Repository {name!r} has an 'xray' configuration but {self._xray_unavailable}")
        if isinstance(current.get("xray"), ApiError):
            raise ArtiformError(f"Repository {name!r}: cannot read its Xray configuration: {current['xray']}")
        for field in IMMUTABLE_FIELDS:
            if field in desired and field in current and current[field] != desired[field]:
                raise ArtiformError(
                    f"Repository {name!r}: {field} is immutable "
                    f"({current[field]!r} -> {desired[field]!r}); "
                    "delete and recreate the repository to change it"
                )

    def create_entity(self, project_key: str, name: str, desired: dict) -> None:
        payload = {k: v for k, v in desired.items() if k not in RESERVED_KEYS}
        self.client.create_repository(name, to_camel(payload))
        if "share_with" in desired:
            self._reconcile_shares(name, desired["share_with"], _share_state([], False, None))
        if "xray" in desired:
            self.client.set_xray_repo_config(name, xray_payload(desired["xray"]))

    def update_entity(self, project_key: str, name: str, desired: dict, current: dict) -> None:
        if current.get("project_key") != project_key:
            self.client.attach_repository(name, project_key, force=True)
        # project_key is silently ignored by the repository update API;
        # attachment above is the only way to move a repo into a project.
        payload = {k: v for k, v in desired.items() if k not in ("project_key", *RESERVED_KEYS)}
        # Each API is only written when its own part drifted: a change to the
        # shares or the Xray settings alone must not rewrite the repository.
        if self.entity_needs_update(current, payload):
            self.client.update_repository(name, to_camel(payload))
        if "share_with" in desired:
            self._reconcile_shares(
                name,
                desired["share_with"],
                current.get("share_with") or _share_state([], False, None),
            )
        if "xray" in desired and needs_update(current.get("xray") or {}, desired["xray"]):
            self.client.set_xray_repo_config(name, xray_payload(desired["xray"], current.get("xray")))

    def _reconcile_shares(self, repo_key: str, want: dict, have: dict) -> None:
        read_only = want["read_only"]
        have_projects = set(have["projects"])
        have_all = have["all"]
        want_projects = set(want["projects"])

        # read_only can only be changed by recreating the shares (the API
        # offers no update; this is the vendor-exercised path).
        if have["read_only"] is not None and read_only is not None and have["read_only"] != read_only:
            for target in sorted(have_projects):
                self.client.unshare_repository(repo_key, target)
            if have_all:
                self.client.unshare_repository_with_all(repo_key)
            have_projects, have_all = set(), False
        else:
            for target in sorted(have_projects - want_projects):
                self.client.unshare_repository(repo_key, target)

        if have_all and not want["all"]:
            self.client.unshare_repository_with_all(repo_key)
        if want["all"] and not have_all:
            self.client.share_repository_with_all(repo_key, read_only)
        for target in sorted(want_projects - have_projects):
            self.client.share_repository(repo_key, target, read_only)

    def delete_entity(self, project_key: str, name: str) -> None:
        self.client.delete_repository(name)
