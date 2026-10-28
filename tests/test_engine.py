import pytest

from artiform.config import ArtifactorySettings, Config, ProjectConfig
from artiform.engine import Engine
from artiform.exceptions import ApiError, ConfigError


def make_config(projects: dict[str, ProjectConfig], enforce_projects=False) -> Config:
    return Config(
        artifactory=ArtifactorySettings(url="https://fake.example.com", token="my-token"),
        projects=projects,
        enforce_projects=enforce_projects,
    )


def project(key, settings=None, sections=None) -> ProjectConfig:
    return ProjectConfig(key=key, settings=settings or {}, sections=sections or {})


def test_creates_missing_project(client):
    config = make_config({"team-x": project("team-x", {"description": "x"})})
    result = Engine(config, client).run()

    assert not result.failed
    ((_, payload),) = client.called("create_project")
    assert payload == {
        "project_key": "team-x",
        "display_name": "team-x",
        "description": "x",
    }


def test_updates_project_preserving_server_fields(client):
    client.projects["team-x"] = {
        "project_key": "team-x",
        "display_name": "Old name",
        "server_field": "keep-me",
    }
    config = make_config({"team-x": project("team-x", {"display_name": "New name"})})
    result = Engine(config, client).run()

    assert not result.failed
    ((_, _, payload),) = client.called("update_project")
    assert payload["display_name"] == "New name"
    assert payload["server_field"] == "keep-me"


def test_updates_changed_admin_privileges(client):
    client.projects["team-x"] = {
        "project_key": "team-x",
        "display_name": "team-x",
        "admin_privileges": {
            "manage_members": True,
            "manage_resources": True,
            "index_resources": True,
        },
    }
    config = make_config(
        {
            "team-x": project(
                "team-x",
                {"admin_privileges": {"manage_resources": False}},
            )
        }
    )
    result = Engine(config, client).run()

    assert not result.failed
    (change,) = result.changes
    assert change.action == "update"
    assert "admin_privileges.manage_resources" in change.details
    ((_, _, payload),) = client.called("update_project")
    # Only the configured privilege changes; the others are preserved.
    assert payload["admin_privileges"] == {
        "manage_members": True,
        "manage_resources": False,
        "index_resources": True,
    }


def test_admin_privileges_matching_server_are_not_updated(client):
    client.projects["team-x"] = {
        "project_key": "team-x",
        "display_name": "team-x",
        "admin_privileges": {
            "manage_members": True,
            "manage_resources": False,
            "index_resources": True,
        },
    }
    config = make_config(
        {
            "team-x": project(
                "team-x",
                {"admin_privileges": {"manage_members": True, "index_resources": True}},
            )
        }
    )
    result = Engine(config, client).run()

    assert result.changes == []
    assert client.called("update_project") == []


def test_up_to_date_project_is_untouched(client):
    client.projects["team-x"] = {
        "project_key": "team-x",
        "display_name": "team-x",
        "server_field": "x",
    }
    config = make_config({"team-x": project("team-x")})
    result = Engine(config, client).run()
    assert result.changes == []


def test_sections_are_processed(client):
    config = make_config(
        {
            "team-x": project(
                "team-x",
                sections={"repositories": {"team-x-docker": {"type": "local", "package_type": "docker"}}},
            )
        }
    )
    result = Engine(config, client).run()
    assert not result.failed
    assert "team-x-docker" in client.repos
    assert client.repos["team-x-docker"]["projectKey"] == "team-x"


def test_enforce_projects_deletes_stale_project_and_its_repos(client):
    client.projects["stale"] = {"project_key": "stale", "display_name": "stale"}
    client.repos["stale-docker"] = {
        "key": "stale-docker",
        "rclass": "local",
        "packageType": "docker",
        "projectKey": "stale",
    }
    config = make_config({"team-x": project("team-x")}, enforce_projects=True)
    result = Engine(config, client).run()

    assert not result.failed
    assert "stale" not in client.projects
    assert "stale-docker" not in client.repos
    # Repo must be deleted before the project.
    names = [c[0] for c in client.calls]
    assert names.index("delete_repository") < names.index("delete_project")


def test_enforce_projects_spares_repos_shared_into_stale_project(client):
    client.projects["stale"] = {"project_key": "stale", "display_name": "stale"}
    client.repos["stale-docker"] = {
        "key": "stale-docker",
        "rclass": "local",
        "packageType": "docker",
        "projectKey": "stale",
    }
    # Owned by team-x, only shared with the stale project.
    client.repos["team-x-npm-remote"] = {
        "key": "team-x-npm-remote",
        "rclass": "remote",
        "packageType": "npm",
        "projectKey": "team-x",
    }
    client.repo_shares["team-x-npm-remote"] = {
        "projects": {"stale"},
        "all": False,
        "read_only": True,
    }
    config = make_config({"team-x": project("team-x")}, enforce_projects=True)
    result = Engine(config, client).run()

    assert not result.failed
    assert "stale" not in client.projects
    assert "stale-docker" not in client.repos
    assert "team-x-npm-remote" in client.repos


def test_enforce_projects_skipped_with_project_filter(client):
    client.projects["stale"] = {"project_key": "stale", "display_name": "stale"}
    config = make_config({"team-x": project("team-x")}, enforce_projects=True)
    Engine(config, client, only_projects=["team-x"]).run()
    assert "stale" in client.projects


def test_unknown_project_filter_rejected(client):
    config = make_config({"team-x": project("team-x")})
    with pytest.raises(ConfigError, match="not in config"):
        Engine(config, client, only_projects=["nope"]).run()


def test_dry_run_plans_but_does_not_apply(client):
    config = make_config(
        {
            "team-x": project(
                "team-x",
                sections={
                    "repositories": {"team-x-docker": {"type": "local", "package_type": "docker"}},
                    "members": {
                        "groups": {
                            "team-x-dev": {
                                "roles": ["Developer"],
                                "import_from_ldap": "corp",
                            }
                        }
                    },
                },
            )
        },
        enforce_projects=True,
    )
    result = Engine(config, client, dry_run=True).run()

    assert not result.failed
    assert client.calls == []
    assert {(c.action, c.entity) for c in result.changes} == {
        ("create", "team-x"),
        ("create", "team-x-docker"),
        ("create", "groups:team-x-dev"),
    }


def test_failed_project_create_skips_its_sections(client):
    client.fail_create_project = True
    config = make_config(
        {
            "team-x": project(
                "team-x",
                sections={"repositories": {"team-x-docker": {"type": "local", "package_type": "docker"}}},
            )
        }
    )
    result = Engine(config, client).run()

    assert result.failed
    assert client.called("create_repository") == []
    assert client.repos == {}


def test_section_error_does_not_stop_other_projects(client):
    config = make_config(
        {
            "team-a": project(
                "team-a",
                sections={
                    # Missing type triggers a ConfigError inside the section.
                    "repositories": {"team-a-bad": {"package_type": "docker"}}
                },
            ),
            "team-b": project("team-b"),
        }
    )
    result = Engine(config, client).run()

    assert result.failed
    assert any("team-a/repositories" in e for e in result.errors)
    assert "team-b" in client.projects


def test_enforce_projects_api_error_is_isolated(client):
    client.projects["team-x"] = {"project_key": "team-x", "display_name": "team-x"}

    def boom(*args, **kwargs):
        raise ApiError(500, "backend unavailable")

    client.list_repositories = boom
    client.projects["stale"] = {"project_key": "stale", "display_name": "stale"}
    config = make_config({"team-x": project("team-x")}, enforce_projects=True)
    result = Engine(config, client).run()

    # The run fails (exit 2), but the error is recorded instead of escaping,
    # so the summary (with its deletions list) is still logged.
    assert result.failed
    assert any("enforce_projects" in e for e in result.errors)


def test_projects_are_announced_with_progress_counter(client, caplog):
    import logging

    caplog.set_level(logging.INFO)
    config = make_config({f"team-{i}": project(f"team-{i}") for i in range(1, 12)})
    Engine(config, client).run()

    headers = [r.getMessage() for r in caplog.records if "Processing project" in r.getMessage()]
    assert len(headers) == 11
    assert headers[0] == "* ( 1/11) Processing project: team-1"
    assert headers[-1] == "* (11/11) Processing project: team-11"


def test_progress_counter_counts_only_filtered_projects(client, caplog):
    import logging

    caplog.set_level(logging.INFO)
    config = make_config({"a": project("a"), "b": project("b"), "c": project("c")})
    Engine(config, client, only_projects=["b"]).run()

    headers = [r.getMessage() for r in caplog.records if "Processing project" in r.getMessage()]
    assert headers == ["* (1/1) Processing project: b"]


# -- cross-project ordering -----------------------------------------------------


def shared_over_team_x(share_target="shared"):
    """A platform project 'shared' with a virtual over team-x's repo, which
    team-x shares with it. Listed with 'shared' FIRST, like a common.yml
    that sorts before the team files."""
    return {
        "shared": project(
            "shared",
            sections={
                "repositories": {
                    "shared-docker-virtual": {
                        "type": "virtual",
                        "package_type": "docker",
                        "repositories": ["team-x-docker-local"],
                    }
                }
            },
        ),
        "team-x": project(
            "team-x",
            sections={
                "repositories": {
                    "team-x-docker-local": {
                        "type": "local",
                        "package_type": "docker",
                        "share_with": {"projects": [share_target]},
                    }
                }
            },
        ),
    }


def test_shared_project_listed_first_converges_in_one_run_on_empty_instance(client):
    result = Engine(make_config(shared_over_team_x()), client).run()

    assert not result.failed, [c.details for c in result.changes if c.error]
    # Both projects exist before any section runs, so team-x's share to
    # 'shared' succeeds, and team-x's repositories run before shared's.
    calls = [c[0] for c in client.calls if c[0] in ("create_project", "create_repository")]
    assert calls == ["create_project", "create_project", "create_repository", "create_repository"]
    repo_creates = [c[1] for c in client.called("create_repository")]
    assert repo_creates == ["team-x-docker-local", "shared-docker-virtual"]
    assert client.repos["shared-docker-virtual"]["projectKey"] == "shared"


def test_dry_run_of_shared_project_listed_first_reports_no_errors_on_empty_instance(client):
    result = Engine(make_config(shared_over_team_x()), client, dry_run=True).run()
    assert not result.failed, [c.details for c in result.changes if c.error]
    assert client.repos == {}
    assert client.projects == {}


def test_dry_run_reports_virtual_over_repo_whose_share_misses_the_project(client):
    result = Engine(make_config(shared_over_team_x(share_target="team-y")), client, dry_run=True).run()
    assert result.failed
    (error,) = [c for c in result.changes if c.error]
    assert error.entity == "shared-docker-virtual"
    assert "share_with does not include project 'shared'" in error.details


def test_order_projects_moves_a_project_only_as_far_back_as_needed():
    from artiform.engine import order_projects

    projects = {k: project(k) for k in ["shared", "team-x", "team-a"]}
    ordered = list(order_projects(projects, {"shared": {"team-x"}}))
    assert ordered == ["team-x", "shared", "team-a"]


def test_order_projects_keeps_config_order_without_dependencies():
    from artiform.engine import order_projects

    projects = {k: project(k) for k in ["c-common", "team-y", "team-x"]}
    assert list(order_projects(projects, {})) == ["c-common", "team-y", "team-x"]


def test_order_projects_ignores_dependencies_outside_the_run():
    from artiform.engine import order_projects

    projects = {k: project(k) for k in ["shared", "team-x"]}
    deps = {"shared": {"team-x", "team-not-in-run"}, "team-x": {"team-x"}}
    assert list(order_projects(projects, deps)) == ["team-x", "shared"]


def test_order_projects_falls_back_to_config_order_on_cycle(caplog):
    from artiform.engine import order_projects

    projects = {k: project(k) for k in ["team-b", "team-a", "team-c"]}
    deps = {"team-b": {"team-a"}, "team-a": {"team-b"}}
    with caplog.at_level("WARNING", logger="artiform"):
        ordered = list(order_projects(projects, deps))
    # team-c has no dependencies and goes first; the cycle keeps config order.
    assert ordered == ["team-c", "team-b", "team-a"]
    assert "cycle" in caplog.text


def test_engine_orders_projects_by_virtual_members_across_projects(client):
    projects = shared_over_team_x()
    projects["team-a"] = project("team-a")
    result = Engine(make_config(projects), client, dry_run=True).run()
    assert not result.failed
    assert [c.entity for c in result.changes if c.section == "project"] == [
        "team-x",
        "shared",
        "team-a",
    ]


def test_project_filter_does_not_trust_shares_of_filtered_out_projects(client):
    # Only 'shared' runs: team-x's share_with will not be applied in this run,
    # so dry-run must report what apply would hit on an empty instance.
    config = make_config(shared_over_team_x())
    result = Engine(config, client, dry_run=True, only_projects=["shared"]).run()
    assert result.failed
    (error,) = [c for c in result.changes if c.error]
    assert error.entity == "shared-docker-virtual"
    assert "does not exist and is not defined in the config" in error.details


def test_duplicate_repository_key_across_projects_aborts_before_any_change(client):
    projects = {
        # Both keys pass the '<project>-' prefix check for this repo key.
        "team": project(
            "team",
            sections={"repositories": {"team-x-docker-local": {"type": "local", "package_type": "docker"}}},
        ),
        "team-x": project(
            "team-x",
            sections={"repositories": {"team-x-docker-local": {"type": "local", "package_type": "docker"}}},
        ),
    }
    with pytest.raises(ConfigError, match="defined in both project 'team' and 'team-x'"):
        Engine(make_config(projects), client).run()
    assert client.projects == {}


def test_project_filter_keeps_dependency_order(client):
    config = make_config(shared_over_team_x())
    result = Engine(config, client, only_projects=["shared", "team-x"]).run()
    assert not result.failed
    assert [c[1] for c in client.called("create_repository")] == [
        "team-x-docker-local",
        "shared-docker-virtual",
    ]


def test_generated_locals_and_explicit_virtual_converge_in_one_run(client, monkeypatch):
    from artiform.config import parse_config

    monkeypatch.setenv("ARTIFACTORY_URL", "https://artifactory.example.com")
    monkeypatch.setenv("ARTIFACTORY_TOKEN", "my-access-token")
    config = parse_config(
        {
            "config_version": 1,
            "projects": {
                "team-x": {
                    "repositories": {
                        "team-x-docker-virtual": {
                            "type": "virtual",
                            "package_type": "docker",
                            "repositories": [
                                "team-x-docker-dev-local",
                                "team-x-docker-prod-local",
                            ],
                        },
                        "generate": {
                            "package_types": ["docker"],
                            "maturities": ["dev", "prod"],
                        },
                    }
                }
            },
        }
    )
    result = Engine(config, client).run()
    assert not result.failed, [c.details for c in result.changes if c.error]
    assert [c[1] for c in client.called("create_repository")] == [
        "team-x-docker-dev-local",
        "team-x-docker-prod-local",
        "team-x-docker-virtual",
    ]
