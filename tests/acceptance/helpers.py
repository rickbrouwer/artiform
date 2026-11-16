"""Helpers shared by the acceptance tests (kept out of conftest.py so the test
modules can import them without importing the conftest module)."""

from __future__ import annotations

import os

from artiform.client import ArtifactoryClient
from artiform.config import Config, parse_config
from artiform.engine import Engine, RunResult

URL = os.environ.get("ARTIFACTORY_URL", "")
TOKEN = os.environ.get("ARTIFACTORY_TOKEN", "")


def make_config(project_key: str, sections: dict | None = None, settings: dict | None = None) -> Config:
    """A one-project Config for the Engine, as parse_config would build it
    from YAML (defaults applied, generators expanded)."""
    raw = {
        "config_version": 1,
        "artifactory": {"url": URL, "token": TOKEN},
        "projects": {project_key: {**(settings or {}), **(sections or {})}},
    }
    return parse_config(raw)


def run(client: ArtifactoryClient, config: Config, dry_run: bool = False) -> RunResult:
    return Engine(config, client, dry_run=dry_run).run()


def changes(result: RunResult) -> set[tuple[str, str]]:
    """The (action, entity) pairs of the changes that were applied or planned
    without error; a failed change is not a change."""
    return {(c.action, c.entity) for c in result.changes if not c.error}
