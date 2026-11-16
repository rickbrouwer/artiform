import pytest

from artiform.exceptions import ConfigError
from artiform.processors.repositories import RepositoriesProcessor


@pytest.fixture
def processor(client):
    return RepositoriesProcessor(client)


def test_create_repository_with_camelcase_payload(client, processor):
    cfg = {"team-x-docker": {"type": "local", "package_type": "docker"}}
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.entity) for c in changes] == [("create", "team-x-docker")]
    ((_, key, payload),) = client.called("create_repository")
    assert key == "team-x-docker"
    assert payload == {
        "rclass": "local",
        "packageType": "docker",
        "environments": ["DEV"],
        "projectKey": "team-x",
    }


def test_up_to_date_repository_is_untouched(client, processor):
    client.repos["team-x-docker"] = {
        "key": "team-x-docker",
        "rclass": "local",
        "packageType": "docker",
        "environments": ["DEV"],
        "projectKey": "team-x",
        "serverGenerated": "ignored",
    }
    cfg = {"team-x-docker": {"type": "local", "package_type": "docker"}}
    changes = processor.process("team-x", cfg, dry_run=False)
    assert changes == []


def test_changed_field_triggers_update(client, processor):
    client.repos["team-x-docker"] = {
        "key": "team-x-docker",
        "rclass": "local",
        "packageType": "docker",
        "environments": ["DEV"],
        "projectKey": "team-x",
        "description": "old",
    }
    cfg = {
        "team-x-docker": {
            "type": "local",
            "package_type": "docker",
            "description": "new",
        }
    }
    changes = processor.process("team-x", cfg, dry_run=False)
    assert [(c.action, c.entity) for c in changes] == [("update", "team-x-docker")]
    ((_, _, payload),) = client.called("update_repository")
    assert payload["description"] == "new"
    assert "projectKey" not in payload
    assert client.called("attach_repository") == []


def test_existing_unassigned_repository_is_adopted_via_attach(client, processor):
    # The repo exists but is not assigned to the project, so the project
    # listing does not return it; a plain create would fail with 400.
    client.repos["team-x-docker"] = {
        "key": "team-x-docker",
        "rclass": "local",
        "packageType": "docker",
        "environments": ["DEV"],
    }
    cfg = {"team-x-docker": {"type": "local", "package_type": "docker"}}
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.entity, c.error) for c in changes] == [("update", "team-x-docker", False)]
    assert client.called("create_repository") == []
    assert client.called("attach_repository") == [("attach_repository", "team-x-docker", "team-x", True)]
    assert client.repos["team-x-docker"]["projectKey"] == "team-x"


def test_immutable_field_change_is_an_error(client, processor):
    client.repos["team-x-docker"] = {
        "key": "team-x-docker",
        "rclass": "local",
        "packageType": "docker",
        "environments": ["DEV"],
        "projectKey": "team-x",
    }
    cfg = {"team-x-docker": {"type": "local", "package_type": "npm"}}
    changes = processor.process("team-x", cfg, dry_run=False)
    assert len(changes) == 1
    assert changes[0].error
    assert "immutable" in changes[0].details
    assert client.repos["team-x-docker"]["packageType"] == "docker"


def test_immutable_change_also_fails_in_dry_run(client, processor):
    client.repos["team-x-docker"] = {
        "key": "team-x-docker",
        "rclass": "local",
        "packageType": "docker",
        "environments": ["DEV"],
        "projectKey": "team-x",
    }
    cfg = {"team-x-docker": {"type": "remote", "package_type": "docker", "url": "https://x"}}
    changes = processor.process("team-x", cfg, dry_run=True)
    assert len(changes) == 1
    assert changes[0].error
    assert "rclass is immutable" in changes[0].details


def test_field_omitted_from_config_is_not_flagged_as_immutable_change(client, processor):
    # package_type is not set in the config; the server value must not be
    # compared against None.
    client.repos["team-x-docker"] = {
        "key": "team-x-docker",
        "rclass": "local",
        "packageType": "docker",
        "environments": ["DEV"],
        "projectKey": "team-x",
        "description": "old",
    }
    cfg = {"team-x-docker": {"type": "local", "description": "new"}}
    changes = processor.process("team-x", cfg, dry_run=False)
    assert [(c.action, c.error) for c in changes] == [("update", False)]
    assert client.repos["team-x-docker"]["description"] == "new"


def test_enforce_deletes_unmanaged_repositories(client, processor):
    client.repos["team-x-old"] = {
        "key": "team-x-old",
        "rclass": "local",
        "packageType": "generic",
        "environments": ["DEV"],
        "projectKey": "team-x",
    }
    cfg = {
        "enforce": True,
        "team-x-docker": {"type": "local", "package_type": "docker"},
    }
    changes = processor.process("team-x", cfg, dry_run=False)
    deletes = [(c.action, c.entity) for c in changes if c.action == "delete"]
    assert deletes == [("delete", "team-x-old")]
    assert "team-x-old" not in client.repos


def test_enforce_with_empty_section_is_rejected(client, processor):
    client.repos["team-x-old"] = {
        "key": "team-x-old",
        "rclass": "local",
        "packageType": "generic",
        "environments": ["DEV"],
        "projectKey": "team-x",
    }
    with pytest.raises(ConfigError, match="delete everything"):
        processor.process("team-x", {"enforce": True}, dry_run=False)
    assert "team-x-old" in client.repos


def test_no_delete_without_enforce(client, processor):
    client.repos["team-x-old"] = {
        "key": "team-x-old",
        "rclass": "local",
        "packageType": "generic",
        "environments": ["DEV"],
        "projectKey": "team-x",
    }
    changes = processor.process("team-x", {}, dry_run=False)
    assert changes == []
    assert "team-x-old" in client.repos


def test_dry_run_makes_no_changes(client, processor):
    cfg = {"team-x-docker": {"type": "local", "package_type": "docker"}}
    changes = processor.process("team-x", cfg, dry_run=True)
    assert [(c.action, c.entity) for c in changes] == [("create", "team-x-docker")]
    assert client.repos == {}
    assert client.calls == []


def test_repo_key_without_project_prefix_rejected(processor):
    with pytest.raises(ConfigError, match="must start with 'team-x-'"):
        processor.process(
            "team-x",
            {"docker-local": {"type": "local", "package_type": "docker"}},
            dry_run=True,
        )


def test_missing_type_rejected(processor):
    with pytest.raises(ConfigError, match="needs 'type"):
        processor.process("team-x", {"team-x-docker": {"package_type": "docker"}}, dry_run=True)


def remote_with_credentials(client):
    client.repos["team-x-docker-remote"] = {
        "key": "team-x-docker-remote",
        "rclass": "remote",
        "packageType": "docker",
        "url": "https://registry-1.docker.io",
        "environments": ["DEV"],
        "projectKey": "team-x",
        "username": "pull-user",
        "password": "s3cret",
    }
    return {
        "team-x-docker-remote": {
            "type": "remote",
            "package_type": "docker",
            "url": "https://registry-1.docker.io",
            "username": "pull-user",
            "password": "s3cret",
        }
    }


def test_write_only_password_does_not_cause_drift(client, processor):
    # The API returns the password encrypted, never the configured plaintext;
    # comparing it would trigger an update on every run.
    cfg = remote_with_credentials(client)
    assert client.get_repository("team-x-docker-remote")["password"] != "s3cret"
    assert processor.process("team-x", cfg, dry_run=False) == []


def test_password_is_sent_on_update_but_kept_out_of_details(client, processor):
    cfg = remote_with_credentials(client)
    client.repos["team-x-docker-remote"]["username"] = "old-user"
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.error) for c in changes] == [("update", False)]
    assert "s3cret" not in changes[0].details
    ((_, _, payload),) = client.called("update_repository")
    assert payload["password"] == "s3cret"


def test_password_is_sent_on_create(client, processor):
    cfg = {
        "team-x-docker-remote": {
            "type": "remote",
            "package_type": "docker",
            "url": "https://registry-1.docker.io",
            "username": "pull-user",
            "password": "s3cret",
        }
    }
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.error) for c in changes] == [("create", False)]
    ((_, _, payload),) = client.called("create_repository")
    assert payload["password"] == "s3cret"


def test_non_boolean_enforce_rejected(client, processor):
    cfg = {
        "enforce": "false",
        "team-x-docker": {"type": "local", "package_type": "docker"},
    }
    with pytest.raises(ConfigError, match="enforce must be true or false"):
        processor.process("team-x", cfg, dry_run=True)


def test_adding_first_password_is_detected_and_masked(client, processor):
    cfg = remote_with_credentials(client)
    del client.repos["team-x-docker-remote"]["password"]
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.error) for c in changes] == [("update", False)]
    assert "s3cret" not in changes[0].details
    assert "password: <unset> -> ****" in changes[0].details
    ((_, _, payload),) = client.called("update_repository")
    assert payload["password"] == "s3cret"


def test_virtual_gets_no_environments_default(client, processor):
    # Virtuals have no environments field; a default would cause a phantom
    # diff on every run (GET never echoes it back).
    cfg = {
        "team-x-maven": {
            "type": "virtual",
            "package_type": "maven",
            "repositories": [],
        }
    }
    changes = processor.process("team-x", cfg, dry_run=False)

    assert not any(c.error for c in changes)
    ((_, _, payload),) = client.called("create_repository")
    assert "environments" not in payload


def test_virtual_member_must_be_assigned_or_shared(client, processor):
    client.repos["other-docker-local"] = {
        "key": "other-docker-local",
        "rclass": "local",
        "packageType": "docker",
        "projectKey": "other",
    }
    cfg = {
        "team-x-docker": {
            "type": "virtual",
            "package_type": "docker",
            "repositories": ["other-docker-local"],
        }
    }
    changes = processor.process("team-x", cfg, dry_run=False)
    assert [(c.action, c.error) for c in changes] == [("create", True)]
    assert "not shared with project 'team-x'" in changes[0].details
    assert client.called("create_repository") == []

    # Once the member is shared with the project, the create succeeds.
    client.repo_shares["other-docker-local"] = {
        "projects": {"team-x"},
        "all": False,
        "read_only": True,
    }
    changes = processor.process("team-x", cfg, dry_run=False)
    assert [(c.action, c.error) for c in changes] == [("create", False)]


# -- ordering: virtuals after their members -------------------------------------


def local(package_type="docker"):
    return {"type": "local", "package_type": package_type}


def virtual(*members, package_type="docker"):
    return {
        "type": "virtual",
        "package_type": package_type,
        "repositories": list(members),
    }


def test_virtual_is_created_after_its_members_regardless_of_config_order(client, processor):
    # The virtual is listed first (as it also is when its members come from
    # 'generate', which appends the generated repos after the explicit ones).
    # Creating it first fails on the server; one run must converge anyway.
    cfg = {
        "team-x-docker-virtual": virtual("team-x-docker-dev-local", "team-x-docker-prod-local"),
        "team-x-docker-dev-local": local(),
        "team-x-docker-prod-local": local(),
    }
    changes = processor.process("team-x", cfg, dry_run=False)

    assert not any(c.error for c in changes)
    assert [c[1] for c in client.called("create_repository")] == [
        "team-x-docker-dev-local",
        "team-x-docker-prod-local",
        "team-x-docker-virtual",
    ]


def test_virtual_including_a_virtual_is_created_after_it(client, processor):
    cfg = {
        "team-x-all-virtual": virtual("team-x-docker-virtual", "team-x-docker-local"),
        "team-x-docker-virtual": virtual("team-x-docker-local"),
        "team-x-docker-local": local(),
    }
    changes = processor.process("team-x", cfg, dry_run=False)

    assert not any(c.error for c in changes)
    assert [c[1] for c in client.called("create_repository")] == [
        "team-x-docker-local",
        "team-x-docker-virtual",
        "team-x-all-virtual",
    ]


def test_virtuals_including_each_other_are_rejected(processor):
    cfg = {
        "team-x-a-virtual": virtual("team-x-b-virtual"),
        "team-x-b-virtual": virtual("team-x-a-virtual"),
    }
    with pytest.raises(ConfigError, match="cycle: team-x-a-virtual -> team-x-b-virtual -> team-x-a-virtual"):
        processor.process("team-x", cfg, dry_run=True)


def test_virtual_repositories_must_be_a_list(processor):
    cfg = {"team-x-docker-virtual": {"type": "virtual", "repositories": "team-x-docker-local"}}
    with pytest.raises(ConfigError, match="must be a list"):
        processor.process("team-x", cfg, dry_run=True)


# -- validation of virtual members, also in dry-run -----------------------------


def test_dry_run_reports_virtual_member_that_does_not_exist(client, processor):
    cfg = {"team-x-docker-virtual": virtual("team-x-docker-local")}
    changes = processor.process("team-x", cfg, dry_run=True)

    assert [(c.action, c.error) for c in changes] == [("create", True)]
    assert "'team-x-docker-local', which does not exist" in changes[0].details
    assert client.called("create_repository") == []


def test_dry_run_reports_virtual_member_of_other_project_that_is_not_shared(client, processor):
    client.repos["other-docker-local"] = {
        "key": "other-docker-local",
        "rclass": "local",
        "packageType": "docker",
        "projectKey": "other",
    }
    cfg = {"team-x-docker-virtual": virtual("other-docker-local")}
    changes = processor.process("team-x", cfg, dry_run=True)

    assert [(c.action, c.error) for c in changes] == [("create", True)]
    assert "belongs to project 'other' and is not shared with project 'team-x'" in changes[0].details


def test_virtual_member_shared_on_the_server_is_accepted(client, processor):
    client.repos["other-docker-local"] = {
        "key": "other-docker-local",
        "rclass": "local",
        "packageType": "docker",
        "projectKey": "other",
    }
    client.repo_shares["other-docker-local"] = {
        "projects": {"team-x"},
        "all": False,
        "read_only": True,
    }
    cfg = {"team-x-docker-virtual": virtual("other-docker-local")}
    changes = processor.process("team-x", cfg, dry_run=True)
    assert [(c.action, c.error) for c in changes] == [("create", False)]


def test_virtual_member_shared_with_all_on_the_server_is_accepted(client, processor):
    client.repos["other-docker-remote"] = {
        "key": "other-docker-remote",
        "rclass": "remote",
        "packageType": "docker",
        "projectKey": "other",
    }
    client.repo_shares["other-docker-remote"] = {
        "projects": set(),
        "all": True,
        "read_only": False,
    }
    cfg = {"team-x-docker-virtual": virtual("other-docker-remote")}
    changes = processor.process("team-x", cfg, dry_run=True)
    assert [(c.action, c.error) for c in changes] == [("create", False)]


def test_existing_virtual_with_unassigned_member_is_reported_on_update(client, processor):
    # The member still exists but was moved to another project: the next
    # update of the virtual would fail on the server, so it is reported.
    client.repos["team-x-docker-virtual"] = {
        "key": "team-x-docker-virtual",
        "rclass": "virtual",
        "packageType": "docker",
        "projectKey": "team-x",
        "repositories": ["team-x-docker-local"],
    }
    client.repos["team-x-docker-local"] = {
        "key": "team-x-docker-local",
        "rclass": "local",
        "packageType": "docker",
        "projectKey": "other",
    }
    cfg = {
        "team-x-docker-virtual": {**virtual("team-x-docker-local"), "description": "new"},
    }
    changes = processor.process("team-x", cfg, dry_run=True)
    assert [(c.action, c.error) for c in changes] == [("update", True)]
    assert "belongs to project 'other'" in changes[0].details


def test_virtual_including_itself_is_rejected(processor):
    cfg = {"team-x-docker-virtual": virtual("team-x-docker-virtual")}
    with pytest.raises(ConfigError, match="includes itself"):
        processor.process("team-x", cfg, dry_run=True)


def test_member_configured_in_other_project_with_share_passes_dry_run_on_empty_server(client, processor):
    # First run on an empty instance: the team repo and its share to
    # 'shared' do not exist yet, but the config says this run creates them.
    processor.index_config(
        {
            "team-x": {
                "team-x-docker-local": {
                    **local(),
                    "share_with": {"projects": ["shared"]},
                }
            },
            "shared": {"shared-docker-virtual": virtual("team-x-docker-local")},
        }
    )
    cfg = {"shared-docker-virtual": virtual("team-x-docker-local")}
    changes = processor.process("shared", cfg, dry_run=True)
    assert [(c.action, c.error) for c in changes] == [("create", False)]
    # Explained by the config, so the server is not asked.
    assert client.called("get_repository_project_status") == []


def test_member_configured_in_other_project_without_share_is_reported(client, processor):
    # The other project's share_with is authoritative: a share that exists
    # on the server but not in its config would be removed by that project.
    client.repos["team-x-docker-local"] = {
        "key": "team-x-docker-local",
        "rclass": "local",
        "packageType": "docker",
        "projectKey": "team-x",
    }
    client.repo_shares["team-x-docker-local"] = {
        "projects": {"shared"},
        "all": False,
        "read_only": True,
    }
    processor.index_config(
        {
            "team-x": {
                "team-x-docker-local": {
                    **local(),
                    "share_with": {"projects": ["team-y"]},
                }
            },
        }
    )
    cfg = {"shared-docker-virtual": virtual("team-x-docker-local")}
    changes = processor.process("shared", cfg, dry_run=True)
    assert [(c.action, c.error) for c in changes] == [("create", True)]
    assert "share_with does not include project 'shared'" in changes[0].details


def test_index_config_skips_invalid_sections(client, processor):
    # A broken team file must not hide the index for the other projects;
    # the error is reported when that project itself is processed.
    processor.index_config(
        {
            "broken": {"wrong-prefix": local()},
            "team-x": {
                "team-x-docker-local": {**local(), "share_with": {"all": True}},
            },
        }
    )
    cfg = {"shared-docker-virtual": virtual("team-x-docker-local")}
    changes = processor.process("shared", cfg, dry_run=True)
    assert [(c.action, c.error) for c in changes] == [("create", False)]


def test_up_to_date_virtual_with_drifted_member_is_not_a_failed_change(client, processor):
    # The member was moved to another project out of band, but the virtual
    # itself matches its config: ArtiForm would not send an update, so the
    # run must not fail permanently on a change it never makes.
    client.repos["team-x-docker-virtual"] = {
        "key": "team-x-docker-virtual",
        "rclass": "virtual",
        "packageType": "docker",
        "projectKey": "team-x",
        "repositories": ["team-x-docker-local"],
    }
    client.repos["team-x-docker-local"] = {
        "key": "team-x-docker-local",
        "rclass": "local",
        "packageType": "docker",
        "projectKey": "other",
    }
    cfg = {"team-x-docker-virtual": virtual("team-x-docker-local")}
    changes = processor.process("team-x", cfg, dry_run=True)
    assert changes == []


def test_member_reclaimed_by_other_project_config_without_share_is_reported(client, processor):
    # Currently assigned to 'shared', but team-x's config owns it and does
    # not share it: team-x attaches it first (dependency order), after which
    # shared's virtual would be rejected. Dry-run must say so.
    client.repos["team-x-docker-local"] = {
        "key": "team-x-docker-local",
        "rclass": "local",
        "packageType": "docker",
        "projectKey": "shared",
    }
    processor.index_config(
        {
            "team-x": {"team-x-docker-local": local()},
            "shared": {"shared-docker-virtual": virtual("team-x-docker-local")},
        }
    )
    cfg = {"shared-docker-virtual": virtual("team-x-docker-local")}
    changes = processor.process("shared", cfg, dry_run=True)
    assert [(c.action, c.error) for c in changes] == [("create", True)]
    assert "belongs to project 'team-x' and is not shared with project 'shared'" in changes[0].details


def test_member_defined_in_other_project_without_share_names_the_owner(client, processor):
    processor.index_config(
        {
            "team-x": {"team-x-docker-local": local()},
            "shared": {"shared-docker-virtual": virtual("team-x-docker-local")},
        }
    )
    cfg = {"shared-docker-virtual": virtual("team-x-docker-local")}
    changes = processor.process("shared", cfg, dry_run=True)
    assert [(c.action, c.error) for c in changes] == [("create", True)]
    assert "project 'team-x' creates it but its config does not share it with project 'shared'" in changes[0].details


def test_member_defined_in_other_project_without_share_but_shared_on_server_is_accepted(client, processor):
    # No share_with in the owner's config means its shares are left alone,
    # so an existing share on the server counts.
    client.repos["team-x-docker-local"] = {
        "key": "team-x-docker-local",
        "rclass": "local",
        "packageType": "docker",
        "projectKey": "team-x",
    }
    client.repo_shares["team-x-docker-local"] = {
        "projects": {"shared"},
        "all": False,
        "read_only": True,
    }
    processor.index_config({"team-x": {"team-x-docker-local": local()}})
    cfg = {"shared-docker-virtual": virtual("team-x-docker-local")}
    changes = processor.process("shared", cfg, dry_run=True)
    assert [(c.action, c.error) for c in changes] == [("create", False)]


def test_project_dependencies_follow_virtual_members(processor):
    processor.index_config(
        {
            "team-x": {"team-x-docker-local": {**local(), "share_with": {"all": True}}},
            "team-y": {"team-y-docker-local": local()},
            "shared": {
                "shared-docker-virtual": virtual("team-x-docker-local", "team-y-docker-local"),
                "shared-npm-remote": {"type": "remote", "package_type": "npm", "url": "https://x"},
            },
        }
    )
    assert processor.project_dependencies() == {
        "team-x": set(),
        "team-y": set(),
        "shared": {"team-x", "team-y"},
    }


def test_duplicate_repository_key_across_projects_is_rejected(processor):
    with pytest.raises(ConfigError, match="defined in both project"):
        processor.index_config(
            {
                "team": {"team-x-docker-local": local()},
                "team-x": {"team-x-docker-local": local()},
            }
        )
