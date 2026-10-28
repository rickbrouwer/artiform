"""The shipped example configs are presented as the complete reference, so a
typo in them must fail the test suite, not the first user who copies them."""

from pathlib import Path

import pytest

from artiform.config import load_config
from artiform.engine import Engine

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("ARTIFACTORY_URL", "https://artifactory.example.com")
    monkeypatch.setenv("ARTIFACTORY_TOKEN", "my-access-token")
    monkeypatch.setenv("DOCKER_REMOTE_USERNAME", "pull-user")
    monkeypatch.setenv("DOCKER_REMOTE_PASSWORD", "s3cret")


@pytest.fixture
def multi_team_config():
    return load_config(EXAMPLES / "multi-team/artiform.yml")


def repositories(config):
    for project in config.projects.values():
        for key, spec in project.sections.get("repositories", {}).items():
            if key != "enforce":
                yield project.key, key, spec


@pytest.mark.parametrize("example", ["artiform.yml", "multi-team/artiform.yml"])
def test_shipped_example_passes_a_dry_run(example, client):
    config = load_config(EXAMPLES / example)
    result = Engine(config, client, dry_run=True).run()
    assert not result.failed, result.errors


def test_multi_team_share_targets_are_defined_projects(multi_team_config):
    for project_key, repo_key, spec in repositories(multi_team_config):
        share = spec.get("share_with") or {}
        for target in share.get("projects") or []:
            assert target in multi_team_config.projects, (
                f"{project_key}/{repo_key} is shared with {target!r}, which has no project file"
            )


def test_multi_team_virtual_members_are_defined_and_visible(multi_team_config):
    all_repos = {repo_key: (project_key, spec) for project_key, repo_key, spec in repositories(multi_team_config)}
    for project_key, repo_key, spec in repositories(multi_team_config):
        if spec.get("type") != "virtual":
            continue
        for member in spec.get("repositories") or []:
            assert member in all_repos, f"{repo_key} includes undefined repo {member}"
            owner, member_spec = all_repos[member]
            if owner == project_key:
                continue
            share = member_spec.get("share_with") or {}
            assert share.get("all") or project_key in (share.get("projects") or []), (
                f"{repo_key} includes {member}, which is not shared with {project_key!r}"
            )
