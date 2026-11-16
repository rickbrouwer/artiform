import pytest

from artiform.config import load_config, parse_config
from artiform.exceptions import ConfigError


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("ARTIFACTORY_URL", "https://artifactory.example.com")
    monkeypatch.setenv("ARTIFACTORY_TOKEN", "my-access-token")


def minimal(**overrides):
    raw = {"config_version": 1, "projects": {"team-x": {}}}
    raw.update(overrides)
    return raw


def test_minimal_config_parses():
    config = parse_config(minimal())
    assert config.artifactory.url == "https://artifactory.example.com"
    assert config.artifactory.token == "my-access-token"
    assert "team-x" in config.projects
    assert not config.enforce_projects


def test_wrong_config_version_rejected():
    with pytest.raises(ConfigError, match="config_version"):
        parse_config(minimal(config_version=2))


def test_unknown_top_level_key_rejected():
    with pytest.raises(ConfigError, match="Unknown keys at top level"):
        parse_config(minimal(projectz={}))


def test_invalid_project_key_rejected():
    with pytest.raises(ConfigError, match="Invalid project key"):
        parse_config(minimal(projects={"Team X": {}}))


def test_enforce_projects_without_projects_rejected():
    with pytest.raises(ConfigError, match="delete every project"):
        parse_config(minimal(projects={}, enforce_projects=True))


def test_missing_token_rejected(monkeypatch):
    monkeypatch.delenv("ARTIFACTORY_TOKEN")
    with pytest.raises(ConfigError, match="Token missing"):
        parse_config(minimal())


def test_token_from_config_file(monkeypatch):
    monkeypatch.delenv("ARTIFACTORY_TOKEN")
    config = parse_config(minimal(artifactory={"token": "from-file"}))
    assert config.artifactory.token == "from-file"


def test_username_password_keys_rejected():
    with pytest.raises(ConfigError, match="Unknown keys at artifactory"):
        parse_config(minimal(artifactory={"username": "admin", "password": "x"}))


def test_defaults_merged_into_repositories():
    raw = minimal(
        defaults={"repository": {"environments": ["DEV"], "xray_index": True}},
        projects={
            "team-x": {
                "repositories": {
                    "enforce": True,
                    "team-x-a": {"type": "local", "package_type": "docker"},
                    "team-x-b": {
                        "type": "local",
                        "package_type": "generic",
                        "environments": ["PROD"],
                    },
                }
            }
        },
    )
    project = parse_config(raw).projects["team-x"]
    repos = project.sections["repositories"]
    assert repos["enforce"] is True
    assert repos["team-x-a"]["environments"] == ["DEV"]
    assert repos["team-x-a"]["xray_index"] is True
    assert repos["team-x-b"]["environments"] == ["PROD"]


def test_defaults_merged_into_project_settings():
    raw = minimal(
        defaults={"project": {"admin_privileges": {"manage_members": True}}},
        projects={"team-x": {"display_name": "Team X"}},
    )
    settings = parse_config(raw).projects["team-x"].settings
    assert settings["admin_privileges"] == {"manage_members": True}
    assert settings["display_name"] == "Team X"


def test_generate_expands_package_type_maturity_matrix():
    raw = minimal(
        projects={
            "team-x": {
                "repositories": {
                    "enforce": True,
                    "generate": {
                        "package_types": ["maven", "npm", "helmoci", "docker"],
                        "maturities": ["dev", "prod"],
                    },
                }
            }
        }
    )
    repos = parse_config(raw).projects["team-x"].sections["repositories"]
    generated = {k for k in repos if k != "enforce"}
    assert generated == {
        f"team-x-{tech}-{maturity}-local"
        for tech in ("maven", "npm", "helmoci", "docker")
        for maturity in ("dev", "prod")
    }
    assert repos["team-x-maven-dev-local"] == {
        "type": "local",
        "package_type": "maven",
        "environments": ["DEV"],
    }
    assert repos["team-x-docker-prod-local"]["environments"] == ["PROD"]
    assert repos["enforce"] is True


def test_generate_explicit_entry_overrides_generated_spec():
    raw = minimal(
        defaults={"repository": {"xray_index": False}},
        projects={
            "team-x": {
                "repositories": {
                    "generate": {
                        "package_types": ["maven"],
                        "maturities": ["prod"],
                    },
                    "team-x-maven-prod-local": {"xray_index": True},
                    "team-x-npm-remote": {
                        "type": "remote",
                        "package_type": "npm",
                        "url": "https://registry.npmjs.org",
                    },
                }
            }
        },
    )
    repos = parse_config(raw).projects["team-x"].sections["repositories"]
    assert repos["team-x-maven-prod-local"] == {
        "type": "local",
        "package_type": "maven",
        "environments": ["PROD"],
        "xray_index": True,
    }
    assert repos["team-x-npm-remote"]["type"] == "remote"


def test_generate_requires_nonempty_lowercase_lists():
    for bad in (
        {},
        {"package_types": [], "maturities": ["dev"]},
        {"package_types": ["maven"], "maturities": ["DEV"]},
        {"package_types": "maven", "maturities": ["dev"]},
    ):
        raw = minimal(projects={"team-x": {"repositories": {"generate": bad}}})
        with pytest.raises(ConfigError):
            parse_config(raw)


def test_generate_unknown_key_rejected():
    raw = minimal(
        projects={
            "team-x": {
                "repositories": {
                    "generate": {
                        "package_types": ["maven"],
                        "maturities": ["dev"],
                        "localities": ["local"],
                    }
                }
            }
        }
    )
    with pytest.raises(ConfigError, match="repositories.generate"):
        parse_config(raw)


CLEANUP_GENERATE = {
    "package_types": ["maven", "npm", "helmoci", "docker"],
    "rules": {
        "dev-prerelease-14d": {
            "maturity": "dev",
            "description": "prerelease cleanup",
            "search_criteria": {
                "included_package_versions": ["*-*"],
                "created_before_in_days": 14,
                "last_downloaded_before_in_days": 14,
            },
        },
        "dev-all-90d": {
            "maturity": "dev",
            "search_criteria": {
                "created_before_in_days": 90,
                "last_downloaded_before_in_days": 90,
            },
        },
        "prod-365d": {
            "maturity": "prod",
            "search_criteria": {
                "created_before_in_days": 365,
                "last_downloaded_before_in_days": 365,
            },
        },
    },
}


def test_cleanup_generate_expands_per_package_type_and_rule():
    raw = minimal(projects={"team-x": {"cleanup_policies": {"enforce": True, "generate": CLEANUP_GENERATE}}})
    policies = parse_config(raw).projects["team-x"].sections["cleanup_policies"]
    generated = {k for k in policies if k != "enforce"}
    assert generated == {
        f"{tech}-{rule}"
        for tech in ("maven", "npm", "helmoci", "docker")
        for rule in ("dev-prerelease-14d", "dev-all-90d", "prod-365d")
    }
    assert policies["maven-dev-prerelease-14d"] == {
        "description": "prerelease cleanup",
        "search_criteria": {
            "package_types": ["maven"],
            "repos": ["team-x-maven-dev-local"],
            "included_packages": ["**"],
            "included_package_versions": ["*-*"],
            "created_before_in_days": 14,
            "last_downloaded_before_in_days": 14,
        },
    }
    assert policies["docker-prod-365d"]["search_criteria"]["repos"] == ["team-x-docker-prod-local"]
    assert policies["enforce"] is True


def test_cleanup_generate_applies_entity_defaults():
    raw = minimal(
        defaults={"cleanup_policy": {"cron_exp": "0 0 2 * * ?"}},
        projects={"team-x": {"cleanup_policies": {"generate": CLEANUP_GENERATE}}},
    )
    policies = parse_config(raw).projects["team-x"].sections["cleanup_policies"]
    assert policies["npm-dev-all-90d"]["cron_exp"] == "0 0 2 * * ?"


def test_cleanup_generate_explicit_entry_overrides_generated_spec():
    raw = minimal(
        projects={
            "team-x": {
                "cleanup_policies": {
                    "generate": CLEANUP_GENERATE,
                    "docker-dev-all-90d": {
                        "search_criteria": {
                            "excluded_package_versions": ["latest"],
                        }
                    },
                }
            }
        }
    )
    policies = parse_config(raw).projects["team-x"].sections["cleanup_policies"]
    criteria = policies["docker-dev-all-90d"]["search_criteria"]
    assert criteria["excluded_package_versions"] == ["latest"]
    assert criteria["created_before_in_days"] == 90
    assert criteria["repos"] == ["team-x-docker-dev-local"]


def test_generate_colliding_composed_keys_rejected():
    raw = minimal(
        projects={
            "team-x": {
                "repositories": {
                    "generate": {
                        # (a, b-c) and (a-b, c) both compose team-x-a-b-c-local
                        "package_types": ["a", "a-b"],
                        "maturities": ["b-c", "c"],
                    }
                }
            }
        }
    )
    with pytest.raises(ConfigError, match="twice"):
        parse_config(raw)

    raw = minimal(
        projects={
            "team-x": {
                "cleanup_policies": {
                    "generate": {
                        "package_types": ["a", "a-b"],
                        "rules": {
                            "b-r": {"maturity": "dev"},
                            "r": {"maturity": "dev"},
                        },
                    }
                }
            }
        }
    )
    with pytest.raises(ConfigError, match="twice"):
        parse_config(raw)


def test_cleanup_generate_override_via_prefixed_key():
    raw = minimal(
        projects={
            "team-x": {
                "cleanup_policies": {
                    "generate": {
                        "package_types": ["maven"],
                        "rules": {"dev-14d": {"maturity": "dev"}},
                    },
                    # README documents overriding by the final prefixed key.
                    "team-x-maven-dev-14d": {"cron_exp": "0 0 1 * * ?"},
                }
            }
        }
    )
    policies = parse_config(raw).projects["team-x"].sections["cleanup_policies"]
    assert "team-x-maven-dev-14d" not in policies
    assert policies["maven-dev-14d"]["cron_exp"] == "0 0 1 * * ?"
    assert policies["maven-dev-14d"]["search_criteria"]["repos"] == ["team-x-maven-dev-local"]


def test_cleanup_generate_rule_without_maturity_rejected():
    raw = minimal(
        projects={
            "team-x": {
                "cleanup_policies": {
                    "generate": {
                        "package_types": ["maven"],
                        "rules": {"bad-rule": {"search_criteria": {}}},
                    }
                }
            }
        }
    )
    with pytest.raises(ConfigError, match="needs 'maturity"):
        parse_config(raw)


def test_cleanup_generate_invalid_shapes_rejected():
    for generate in (
        {"package_types": ["maven"]},
        {"package_types": ["maven"], "rules": {}},
        {"package_types": [], "rules": {"r": {"maturity": "dev"}}},
        {"package_types": ["maven"], "rules": {"r": {"maturity": "dev"}}, "extra": 1},
    ):
        raw = minimal(projects={"team-x": {"cleanup_policies": {"generate": generate}}})
        with pytest.raises(ConfigError):
            parse_config(raw)


def test_unknown_members_key_rejected():
    raw = minimal(projects={"team-x": {"members": {"grps": {}}}})
    with pytest.raises(ConfigError, match="Unknown keys in team-x.members"):
        parse_config(raw)


def test_members_kind_as_list_rejected():
    raw = minimal(projects={"team-x": {"members": {"users": ["alice", "bob"]}}})
    with pytest.raises(ConfigError, match="must be a mapping of name to settings"):
        parse_config(raw)


def test_unknown_project_key_rejected():
    raw = minimal(projects={"team-x": {"repositorys": {}}})
    with pytest.raises(ConfigError, match="project 'team-x'"):
        parse_config(raw)


# -- environment variable substitution ($VAR / ${VAR}) ------------------------


def write_config(tmp_path, body):
    path = tmp_path / "artiform.yml"
    path.write_text("config_version: 1\n" + body)
    return path


def repo_spec(tmp_path, fields):
    path = write_config(
        tmp_path,
        "projects:\n"
        "  team-x:\n"
        "    repositories:\n"
        "      team-x-docker-remote:\n"
        "        type: remote\n"
        "        package_type: docker\n" + "".join(f"        {line}\n" for line in fields),
    )
    config = load_config(path)
    return config.projects["team-x"].sections["repositories"]["team-x-docker-remote"]


def test_env_vars_substituted_in_values(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKER_REMOTE_USERNAME", "pull-user")
    monkeypatch.setenv("DOCKER_REMOTE_PASSWORD", "s3cret")
    spec = repo_spec(
        tmp_path,
        [
            "username: $DOCKER_REMOTE_USERNAME",
            "password: ${DOCKER_REMOTE_PASSWORD}",
            'description: "costs $$5"',
        ],
    )
    assert spec["username"] == "pull-user"
    assert spec["password"] == "s3cret"
    assert spec["description"] == "costs $5"


def test_env_vars_substituted_inside_lists(tmp_path, monkeypatch):
    monkeypatch.setenv("EXTRA_ENV", "PROD")
    spec = repo_spec(tmp_path, ["environments: [DEV, $EXTRA_ENV]"])
    assert spec["environments"] == ["DEV", "PROD"]


def test_unset_env_var_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("NOPE_NOT_SET", raising=False)
    path = write_config(
        tmp_path,
        "projects:\n  team-x:\n    description: $NOPE_NOT_SET\n",
    )
    with pytest.raises(ConfigError, match="NOPE_NOT_SET"):
        load_config(path)


def test_non_variable_dollar_signs_left_alone(tmp_path):
    # A lone dollar or $<digit> is not a variable reference.
    spec = repo_spec(tmp_path, ['notes: "price $ 5 or $5"'])
    assert spec["notes"] == "price $ 5 or $5"


def test_empty_env_var_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPTY_SECRET", "")
    path = write_config(tmp_path, "projects:\n  team-x:\n    description: $EMPTY_SECRET\n")
    with pytest.raises(ConfigError, match="not set or empty"):
        load_config(path)


def test_malformed_env_var_reference_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKER_REMOTE_PASSWORD", "s3cret")
    for value in ("${DOCKER_REMOTE_PASSWORD", "${}", "${1X}"):
        path = write_config(tmp_path, f'projects:\n  team-x:\n    description: "{value}"\n')
        with pytest.raises(ConfigError, match="Malformed"):
            load_config(path)


def test_non_boolean_enforce_projects_rejected(monkeypatch):
    # Env var substitution yields strings; bool("false") would be True.
    with pytest.raises(ConfigError, match="enforce_projects must be true or false"):
        parse_config(minimal(enforce_projects="false"))
