import logging
from dataclasses import dataclass, field
from functools import partial

from artiform.client import ArtifactoryClient
from artiform.config import Config, ProjectConfig
from artiform.diff import changed_fields, needs_update
from artiform.exceptions import ArtiformError, ConfigError
from artiform.processors import SECTION_PROCESSORS
from artiform.processors.base import ACTION_SYMBOLS, Change
from artiform.util import deep_merge

logger = logging.getLogger("artiform")


@dataclass
class RunResult:
    changes: list[Change] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.errors) or any(c.error for c in self.changes)


def order_projects(projects: dict[str, ProjectConfig], dependencies: dict[str, set[str]]) -> dict[str, ProjectConfig]:
    """Order projects so that each comes after the projects it depends on
    (as reported by the processors, e.g. the owners of the repositories its
    virtuals include). Projects without a dependency keep their config order,
    and a project only moves back as far as it has to. A dependency cycle is
    reported and falls back to config order (a second run then converges)."""
    deps = {key: {dep for dep in dependencies.get(key, ()) if dep in projects and dep != key} for key in projects}
    ordered: dict[str, ProjectConfig] = {}
    remaining = list(projects)
    while remaining:
        ready = next((key for key in remaining if deps[key] <= set(ordered)), None)
        if ready is None:
            logger.warning(
                "Projects depend on each other's repositories in a cycle "
                "(%s); processing them in config order, a second run may be "
                "needed",
                ", ".join(remaining),
            )
            ready = remaining[0]
        ordered[ready] = projects[ready]
        remaining.remove(ready)
    return ordered


class Engine:
    def __init__(
        self,
        config: Config,
        client: ArtifactoryClient,
        dry_run: bool = False,
        only_projects: list[str] | None = None,
    ):
        self.config = config
        self.client = client
        self.dry_run = dry_run
        self.only_projects = only_projects
        self.processors = [cls(client) for cls in SECTION_PROCESSORS]

    def run(self) -> RunResult:
        result = RunResult()
        self._check_connection()

        projects = self.config.projects
        if self.only_projects:
            unknown = set(self.only_projects) - set(projects)
            if unknown:
                raise ConfigError(f"Projects not in config: {', '.join(sorted(unknown))}")
            projects = {k: projects[k] for k in self.only_projects}

        # Only the projects in this run are indexed: with a --project filter,
        # a share or repo that a filtered-out project would create does not
        # exist, and the validation must not assume it does.
        dependencies: dict[str, set[str]] = {}
        for processor in self.processors:
            processor.index_config(
                {
                    key: project.sections[processor.section]
                    for key, project in projects.items()
                    if processor.section in project.sections
                }
            )
            for key, deps in processor.project_dependencies().items():
                dependencies.setdefault(key, set()).update(deps)
        projects = order_projects(projects, dependencies)

        # Phase 1: every project entity first, so that cross-project
        # references in the sections (a share to another project, a virtual
        # over another project's repositories) never fail because the other
        # project does not exist yet, whatever the config order.
        ready: set[str] = set()
        logger.info("* Ensuring %d project(s) exist", len(projects))
        for key, project in projects.items():
            try:
                if self._ensure_project(project, result):
                    ready.add(key)
                else:
                    logger.warning(
                        "Skipping sections of project %s because it could not be created",
                        key,
                    )
            except ArtiformError as exc:
                logger.error("Project %s failed: %s", key, exc)
                result.errors.append(f"project {key}: {exc}")

        # Phase 2: the sections, in dependency order. Progress counter
        # ("* (1/3) Processing project: x"), right-aligned so the
        # lines stay aligned for 10+ projects.
        total = len(projects)
        width = len(str(total))
        for number, (key, project) in enumerate(projects.items(), start=1):
            logger.info("* (%*d/%d) Processing project: %s", width, number, total, key)
            if key not in ready:
                logger.warning("  skipped: the project could not be created")
                continue
            try:
                self._process_sections(project, result)
            except ArtiformError as exc:
                logger.error("Project %s failed: %s", key, exc)
                result.errors.append(f"project {key}: {exc}")

        if self.config.enforce_projects:
            if self.only_projects:
                logger.warning("Skipping enforce_projects because a project filter is active")
            else:
                try:
                    self._enforce_projects(result)
                except ArtiformError as exc:
                    # Isolated like per-project errors: changes were already
                    # applied above, so the summary (with its deletions list)
                    # must still be logged and the run must exit 2, not 1.
                    logger.error("enforce_projects failed: %s", exc)
                    result.errors.append(f"enforce_projects: {exc}")

        self._log_summary(result)
        return result

    def _check_connection(self) -> None:
        version = self.client.version()
        logger.info(
            "Connected to Artifactory %s at %s%s",
            version,
            self.client.base_url,
            " (dry-run)" if self.dry_run else "",
        )

    # -- project entity ---------------------------------------------------------

    def _process_sections(self, project: ProjectConfig, result: RunResult) -> None:
        for processor in self.processors:
            section_cfg = project.sections.get(processor.section)
            if section_cfg is None:
                continue
            try:
                result.changes.extend(processor.process(project.key, section_cfg, self.dry_run))
            except ArtiformError as exc:
                logger.error(
                    "Section %s of project %s failed: %s",
                    processor.section,
                    project.key,
                    exc,
                )
                result.errors.append(f"{project.key}/{processor.section}: {exc}")

    def _ensure_project(self, project: ProjectConfig, result: RunResult) -> bool:
        """Returns False when the project does not exist and could not be
        created, so its sections must be skipped."""
        desired = dict(project.settings)
        desired["project_key"] = project.key
        desired.setdefault("display_name", project.key)

        current = self.client.get_project(project.key)
        if current is None:
            return self._record(
                result,
                project.key,
                "create",
                self.dry_run,
                lambda: self.client.create_project(desired),
            )
        if needs_update(current, desired):
            details = "; ".join(changed_fields(current, desired))
            self._record(
                result,
                project.key,
                "update",
                self.dry_run,
                # PUT is a full update, so apply desired on top of current
                # to avoid wiping server-side fields not managed in config.
                lambda: self.client.update_project(project.key, deep_merge(current, desired)),
                details=details,
            )
        else:
            logger.info("✅ project/%s: up to date", project.key)
        return True

    # -- enforce: delete projects not in config ---------------------------------

    def _enforce_projects(self, result: RunResult) -> None:
        existing = {p["project_key"] for p in self.client.list_projects()}
        stale = sorted(existing - set(self.config.projects))
        for key in stale:
            repos = self.client.list_repositories(project_key=key)
            # The listing also returns repos shared with the project; only
            # delete repos the stale project actually owns.
            owned = [
                r["key"]
                for r in repos
                if (config := self.client.get_repository(r["key"])) is not None and config.get("projectKey") == key
            ]
            for repo in sorted(owned):
                self._record(
                    result,
                    key,
                    "delete",
                    self.dry_run,
                    partial(self.client.delete_repository, repo),
                    entity=repo,
                    section="repositories",
                    details="project not in config (enforce_projects)",
                )
            self._record(
                result,
                key,
                "delete",
                self.dry_run,
                partial(self.client.delete_project, key),
                details="not in config (enforce_projects)",
            )

    def _record(
        self,
        result: RunResult,
        project_key: str,
        action: str,
        dry_run: bool,
        operation,
        entity: str | None = None,
        section: str = "project",
        details: str = "",
    ) -> bool:
        entity = entity or project_key
        label = f"{section}/{entity}"
        suffix = f" ({details})" if details else ""
        symbol = ACTION_SYMBOLS.get(action, "?")
        if dry_run:
            logger.info("DRY-RUN %s would %s %s%s", symbol, action, label, suffix)
            result.changes.append(Change(section, entity, action, details, project=project_key))
            return True
        try:
            operation()
        except ArtiformError as exc:
            logger.error("❌ Failed to %s %s: %s", action, label, exc)
            result.changes.append(Change(section, entity, action, str(exc), error=True, project=project_key))
            return False
        logger.info("%s %s %s%s", symbol, action.upper(), label, suffix)
        result.changes.append(Change(section, entity, action, details, project=project_key))
        return True

    def _log_summary(self, result: RunResult) -> None:
        applied = [c for c in result.changes if not c.error]
        failed = [c for c in result.changes if c.error]
        verb = "planned" if self.dry_run else "applied"
        counts = ", ".join(
            f"{n} {action}"
            for action in ("create", "update", "delete")
            if (n := sum(1 for c in applied if c.action == action))
        )
        logger.info(
            "Done: %d change(s) %s (%s), %d failure(s)",
            len(applied),
            verb,
            counts or "none",
            len(failed) + len(result.errors),
        )
        deletions = [c for c in applied if c.action == "delete"]
        if deletions:
            logger.warning(
                "⚠️ Deletions %s (%d):",
                "planned" if self.dry_run else "applied",
                len(deletions),
            )
            for change in deletions:
                suffix = f" ({change.details})" if change.details else ""
                logger.warning(
                    "  🗑️ %s/%s/%s%s",
                    change.project or "-",
                    change.section,
                    change.entity,
                    suffix,
                )
        for change in failed:
            logger.error("  ❌ failed: %s %s/%s: %s", change.action, change.section, change.entity, change.details)
        for error in result.errors:
            logger.error("  ❌ failed: %s", error)
