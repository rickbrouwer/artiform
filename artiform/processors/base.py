import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import partial
from typing import ClassVar

from artiform.client import ArtifactoryClient
from artiform.diff import changed_fields, needs_update
from artiform.exceptions import ArtiformError, ConfigError

logger = logging.getLogger("artiform")


ACTION_SYMBOLS = {"create": "➕", "update": "✏️", "delete": "🗑️"}


@dataclass
class Change:
    section: str
    entity: str
    action: str
    details: str = ""
    error: bool = False
    project: str = ""


class SectionProcessor(ABC):
    """Reconciles one config section of a project against Artifactory.

    Subclasses provide the desired and current state as dicts keyed by a
    natural identifier; create/update/delete and the enforce-driven removal
    of unmanaged entities all derive from those two views.
    """

    section: ClassVar[str]

    def __init__(self, client: ArtifactoryClient):
        self.client = client

    @abstractmethod
    def desired_entities(self, project_key: str, cfg: dict) -> dict[str, dict]:
        """Desired state from config, keyed by natural identifier."""

    @abstractmethod
    def current_entities(self, project_key: str, desired: dict[str, dict]) -> dict[str, dict]:
        """Current state from Artifactory, normalized for comparison.

        desired lets a processor look up configured entities that exist
        outside the project (e.g. an unassigned repository to adopt) and
        fetch extra state only for entities that manage it (e.g. shares)."""

    @abstractmethod
    def create_entity(self, project_key: str, name: str, desired: dict) -> None: ...

    @abstractmethod
    def update_entity(self, project_key: str, name: str, desired: dict, current: dict) -> None: ...

    @abstractmethod
    def delete_entity(self, project_key: str, name: str) -> None: ...

    def index_config(self, sections: dict[str, dict]) -> None:
        """Called once per run with this processor's section config of every
        project in the run (project key -> section config), before any
        project is processed. Lets a processor validate references to
        entities of other projects that this run will create later, and
        derive project_dependencies. May raise ConfigError for conflicts
        between projects; that aborts the run before anything is changed."""

    def project_dependencies(self) -> dict[str, set[str]]:
        """Project key -> keys of the projects whose section must be processed
        first, as learned by index_config. The engine orders projects by the
        union over all processors."""
        return {}

    def validate_entity(
        self,
        project_key: str,
        name: str,
        desired: dict,
        desired_all: dict[str, dict],
        current_all: dict[str, dict],
    ) -> None:
        """Raise ArtiformError for a desired entity the API would reject on
        create or update. Runs in both dry-run and apply mode, so dry-run
        surfaces the problem before anything is changed."""

    def validate_update(self, project_key: str, name: str, desired: dict, current: dict) -> None:
        """Raise ArtiformError for changes the API cannot apply. Runs in
        both dry-run and apply mode, so dry-run surfaces them too."""

    def entity_needs_update(self, current: dict, desired: dict) -> bool:
        return needs_update(current, desired)

    def describe_update(self, current: dict, desired: dict) -> str:
        return "; ".join(changed_fields(current, desired))

    def process(self, project_key: str, section_cfg: dict, dry_run: bool) -> list[Change]:
        enforce = section_cfg.get("enforce", False)
        # Strict on purpose: env var substitution always produces strings, and
        # bool("false") is True, which would silently enable mass deletion.
        if not isinstance(enforce, bool):
            raise ConfigError(f"{project_key}.{self.section}.enforce must be true or false, got {enforce!r}")
        cfg = {k: v for k, v in section_cfg.items() if k != "enforce"}
        desired = self.desired_entities(project_key, cfg)
        if enforce and not desired:
            raise ConfigError(
                f"{project_key}.{self.section} has 'enforce: true' but no entities; "
                "this would delete everything in the section. Remove 'enforce' "
                "or list the entities explicitly."
            )
        current = self.current_entities(project_key, desired)
        changes: list[Change] = []

        for name, want in desired.items():
            have = current.get(name)
            action = "create" if have is None else "update"
            try:
                if have is None:
                    self.validate_entity(project_key, name, want, desired, current)
                    self._apply(
                        changes,
                        project_key,
                        name,
                        "create",
                        dry_run,
                        partial(self.create_entity, project_key, name, want),
                    )
                    continue
                self.validate_update(project_key, name, want, have)
                if self.entity_needs_update(have, want):
                    # Only a change that is about to be sent is validated: an
                    # up-to-date entity is never touched, so it must not turn
                    # into a permanently failed run.
                    self.validate_entity(project_key, name, want, desired, current)
                    self._apply(
                        changes,
                        project_key,
                        name,
                        "update",
                        dry_run,
                        partial(self.update_entity, project_key, name, want, have),
                        details=self.describe_update(have, want),
                    )
                else:
                    logger.debug("%s/%s/%s is up to date", project_key, self.section, name)
            except ArtiformError as exc:
                logger.error(
                    "❌ Invalid change for %s/%s/%s: %s",
                    project_key,
                    self.section,
                    name,
                    exc,
                )
                changes.append(
                    Change(
                        self.section,
                        name,
                        action,
                        str(exc),
                        error=True,
                        project=project_key,
                    )
                )

        if enforce:
            for name in sorted(set(current) - set(desired)):
                self._apply(
                    changes,
                    project_key,
                    name,
                    "delete",
                    dry_run,
                    partial(self.delete_entity, project_key, name),
                    details="not in config (enforce)",
                )
        if not changes:
            logger.info(
                "✅ %s/%s: up to date (%d managed, no changes)",
                project_key,
                self.section,
                len(desired),
            )
        return changes

    def _apply(
        self,
        changes: list[Change],
        project_key: str,
        name: str,
        action: str,
        dry_run: bool,
        operation,
        details: str = "",
    ) -> None:
        label = f"{project_key}/{self.section}/{name}"
        suffix = f" ({details})" if details else ""
        symbol = ACTION_SYMBOLS.get(action, "?")
        if dry_run:
            logger.info("DRY-RUN %s would %s %s%s", symbol, action, label, suffix)
            changes.append(Change(self.section, name, action, details, project=project_key))
            return
        try:
            operation()
        except ArtiformError as exc:
            logger.error("❌ Failed to %s %s: %s", action, label, exc)
            changes.append(Change(self.section, name, action, str(exc), error=True, project=project_key))
            return
        logger.info("%s %s %s%s", symbol, action.upper(), label, suffix)
        changes.append(Change(self.section, name, action, details, project=project_key))
