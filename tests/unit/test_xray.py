import copy

import pytest

from artiform.exceptions import ApiError, ConfigError, NotFoundError
from artiform.processors.repositories import RepositoriesProcessor


@pytest.fixture
def processor(client):
    return RepositoriesProcessor(client)


def local_spec(**extra):
    return {"type": "local", "package_type": "docker", **extra}


def existing_local(client, xray_index=True, xray_config=None):
    client.repos["team-x-docker-dev-local"] = {
        "key": "team-x-docker-dev-local",
        "rclass": "local",
        "packageType": "docker",
        "environments": ["DEV"],
        "projectKey": "team-x",
        "xrayIndex": xray_index,
    }
    if xray_config is not None:
        client.xray_configs["team-x-docker-dev-local"] = {"repo_name": "team-x-docker-dev-local", **xray_config}


PATTERNS_CFG = {
    "patterns": [
        {"include": "core/**", "exclude": "core/external/**", "retention_in_days": 45},
        {"include": "tools/**", "retention_in_days": 10, "index_new_artifacts": False},
    ],
    "all_other_artifacts": {"retention_in_days": 90},
}

PATTERNS_API = {
    "repo_paths_config": {
        "patterns": [
            {"include": "core/**", "exclude": "core/external/**", "index_new_artifacts": True, "retention_in_days": 45},
            {"include": "tools/**", "exclude": "", "index_new_artifacts": False, "retention_in_days": 10},
        ],
        "all_other_artifacts": {"index_new_artifacts": True, "retention_in_days": 90},
    }
}


def test_create_sets_xray_index_and_pushes_xray_config(client, processor):
    cfg = {"team-x-docker-dev-local": local_spec(xray=PATTERNS_CFG)}
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.error) for c in changes] == [("create", False)]
    ((_, _, payload),) = client.called("create_repository")
    # 'xray' is reserved and must not reach the repository API; indexing is
    # switched on so Xray accepts the configuration.
    assert "xray" not in payload and payload["xrayIndex"] is True
    assert client.called("set_xray_repo_config") == [("set_xray_repo_config", "team-x-docker-dev-local", PATTERNS_API)]


def test_repo_level_retention_goes_to_repo_config(client, processor):
    existing_local(client)
    cfg = {"team-x-docker-dev-local": local_spec(xray={"retention_in_days": 30, "vuln_contextual_analysis": True})}
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.error) for c in changes] == [("update", False)]
    assert client.called("set_xray_repo_config") == [
        (
            "set_xray_repo_config",
            "team-x-docker-dev-local",
            {"repo_config": {"retention_in_days": 30, "vuln_contextual_analysis": True}},
        )
    ]


def test_matching_xray_config_is_untouched(client, processor):
    existing_local(client, xray_config={"repo_config": {"retention_in_days": 90}, **PATTERNS_API})
    cfg = {"team-x-docker-dev-local": local_spec(xray=PATTERNS_CFG)}
    assert processor.process("team-x", cfg, dry_run=False) == []


def test_server_only_pattern_fields_do_not_cause_drift(client, processor):
    # Lists are compared whole, so an extra field the server adds to a
    # pattern object (or a null exclude) must be normalized away.
    patterns = [dict(p, id="abc") for p in PATTERNS_API["repo_paths_config"]["patterns"]]
    patterns[1]["exclude"] = None
    existing_local(
        client,
        xray_config={
            "repo_paths_config": {
                "patterns": patterns,
                "all_other_artifacts": {"index_new_artifacts": True, "retention_in_days": 90, "id": "x"},
            }
        },
    )
    cfg = {"team-x-docker-dev-local": local_spec(xray=PATTERNS_CFG)}
    assert processor.process("team-x", cfg, dry_run=False) == []


def test_changed_pattern_retention_triggers_update(client, processor):
    existing_local(client, xray_config=PATTERNS_API)
    cfg = {"team-x-docker-dev-local": local_spec(xray=copy.deepcopy(PATTERNS_CFG))}
    cfg["team-x-docker-dev-local"]["xray"]["patterns"][0]["retention_in_days"] = 60
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.error) for c in changes] == [("update", False)]
    assert "xray.patterns" in changes[0].details
    ((_, _, payload),) = client.called("set_xray_repo_config")
    assert payload["repo_paths_config"]["patterns"][0]["retention_in_days"] == 60


def test_repository_field_change_does_not_resend_xray_config(client, processor):
    existing_local(client, xray_config=PATTERNS_API)
    cfg = {"team-x-docker-dev-local": local_spec(description="new", xray=PATTERNS_CFG)}
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.error) for c in changes] == [("update", False)]
    assert client.called("update_repository")
    assert client.called("set_xray_repo_config") == []


def test_repo_unknown_to_xray_gets_configured(client, processor):
    # The repo exists in Artifactory but Xray has no configuration for it
    # (e.g. indexing was off until now): GET answers 404.
    existing_local(client, xray_index=False)
    cfg = {"team-x-docker-dev-local": local_spec(xray={"retention_in_days": 30})}
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.error) for c in changes] == [("update", False)]
    assert client.repos["team-x-docker-dev-local"]["xrayIndex"] is True
    assert client.xray_configs["team-x-docker-dev-local"]["repo_config"] == {"retention_in_days": 30}


def test_dry_run_plans_xray_change_without_applying(client, processor):
    existing_local(client)
    cfg = {"team-x-docker-dev-local": local_spec(xray=PATTERNS_CFG)}
    changes = processor.process("team-x", cfg, dry_run=True)

    assert [(c.action, c.entity) for c in changes] == [("update", "team-x-docker-dev-local")]
    assert "xray.patterns: [] -> [{'include': 'core/**'" in changes[0].details
    assert client.called("set_xray_repo_config") == []


def test_absent_xray_key_leaves_xray_config_untouched(client, processor):
    existing_local(client, xray_config=PATTERNS_API)
    cfg = {"team-x-docker-dev-local": local_spec()}
    assert processor.process("team-x", cfg, dry_run=False) == []
    assert client.called("get_xray_repo_config") == []


def other_local(client, description="old"):
    client.repos["team-x-generic-local"] = {
        "key": "team-x-generic-local",
        "rclass": "local",
        "packageType": "generic",
        "environments": ["DEV"],
        "projectKey": "team-x",
        "description": description,
    }


def test_unreadable_xray_config_fails_only_that_repo(client, processor):
    existing_local(client)
    other_local(client)
    client.xray_config_errors["team-x-docker-dev-local"] = ApiError(403, "GET .../repos_config/x: 403 forbidden")
    cfg = {
        "team-x-docker-dev-local": local_spec(xray={"retention_in_days": 30}),
        "team-x-generic-local": {"type": "local", "package_type": "generic", "description": "new"},
    }
    for dry_run in (True, False):
        client.calls.clear()
        changes = processor.process("team-x", cfg, dry_run=dry_run)
        assert [(c.entity, c.action, c.error) for c in changes] == [
            ("team-x-docker-dev-local", "update", True),
            ("team-x-generic-local", "update", False),
        ]
        assert "cannot read its Xray configuration" in changes[0].details
        assert "403 forbidden" in changes[0].details
        assert client.called("set_xray_repo_config") == []


@pytest.mark.parametrize("error", [NotFoundError("GET /xray/api/v1/system/version: 404"), ApiError(403, "no license")])
def test_missing_xray_is_reported_before_anything_is_changed(client, processor, error):
    # Without Xray the repos_config GET answers the same 404 as "not configured
    # yet"; the version probe tells them apart, so the dry-run already shows
    # the problem and the apply never half-applies the repository.
    existing_local(client)
    other_local(client)
    client.xray_api_error = error
    cfg = {
        "team-x-docker-dev-local": local_spec(xray={"retention_in_days": 30}),
        "team-x-npm-dev-local": {"type": "local", "package_type": "npm", "xray": {"retention_in_days": 30}},
        "team-x-generic-local": {"type": "local", "package_type": "generic", "description": "new"},
    }
    for dry_run in (True, False):
        client.calls.clear()
        changes = processor.process("team-x", cfg, dry_run=dry_run)
        assert [(c.entity, c.action, c.error) for c in changes] == [
            ("team-x-docker-dev-local", "update", True),
            ("team-x-npm-dev-local", "create", True),
            ("team-x-generic-local", "update", False),
        ]
        assert all("Xray is not available" in c.details for c in changes[:2])
        assert client.called("get_xray_repo_config") == []
        assert client.called("set_xray_repo_config") == []
        assert client.called("create_repository") == []
    assert client.repos["team-x-generic-local"]["description"] == "new"


def test_xray_is_probed_once_per_run_and_only_when_configured(client, processor):
    existing_local(client)
    processor.process("team-x", {"team-x-docker-dev-local": local_spec()}, dry_run=True)
    assert client.called("xray_version") == []
    cfg = {"team-x-docker-dev-local": local_spec(xray={"retention_in_days": 30})}
    processor.process("team-x", cfg, dry_run=True)
    processor.process("team-y", {"team-y-docker-local": local_spec(xray={"retention_in_days": 30})}, dry_run=True)
    assert client.called("xray_version") == [("xray_version",)]


def test_stale_server_patterns_are_drift_for_repo_wide_retention(client, processor):
    # Xray ignores the repo-wide retention while patterns exist, so leftover
    # patterns must be reported on every run instead of "up to date".
    existing_local(client, xray_config={"repo_config": {"retention_in_days": 365}, **PATTERNS_API})
    cfg = {"team-x-docker-dev-local": local_spec(xray={"retention_in_days": 365})}
    changes = processor.process("team-x", cfg, dry_run=True)

    assert [(c.action, c.error) for c in changes] == [("update", False)]
    assert "xray.patterns: [{'include': 'core/**'" in changes[0].details
    assert changes[0].details.endswith("-> []")


def test_unmanaged_repo_config_fields_survive_a_put(client, processor):
    # The PUT replaces the whole Xray configuration, so settings made in the
    # UI but absent from the config must be carried over.
    existing_local(
        client,
        xray_config={
            "repo_config": {
                "retention_in_days": 10,
                "vuln_contextual_analysis": True,
                "exposures": {"scanners_category": {"secrets_scan": True}},
            },
            **PATTERNS_API,
        },
    )
    cfg = {"team-x-docker-dev-local": local_spec(xray=copy.deepcopy(PATTERNS_CFG))}
    cfg["team-x-docker-dev-local"]["xray"]["patterns"][1]["retention_in_days"] = 20
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.error) for c in changes] == [("update", False)]
    ((_, _, payload),) = client.called("set_xray_repo_config")
    assert payload["repo_config"] == {
        "retention_in_days": 10,
        "vuln_contextual_analysis": True,
        "exposures": {"scanners_category": {"secrets_scan": True}},
    }
    assert payload["repo_paths_config"]["patterns"][1]["retention_in_days"] == 20


def test_xray_only_change_does_not_rewrite_the_repository(client, processor):
    existing_local(client, xray_config={"repo_config": {"retention_in_days": 10}})
    cfg = {"team-x-docker-dev-local": local_spec(xray={"retention_in_days": 30})}
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.error) for c in changes] == [("update", False)]
    assert client.called("update_repository") == []
    assert client.called("set_xray_repo_config") == [
        ("set_xray_repo_config", "team-x-docker-dev-local", {"repo_config": {"retention_in_days": 30}})
    ]


def test_omitted_false_boolean_in_response_does_not_drift(client, processor):
    # A JSON encoder dropping empty values would omit index_new_artifacts:
    # false; it must read as false, not as a missing field.
    cfg = copy.deepcopy(PATTERNS_CFG)
    cfg["all_other_artifacts"]["index_new_artifacts"] = False
    existing_local(
        client,
        xray_config={
            "repo_paths_config": {
                "patterns": [
                    {
                        "include": "core/**",
                        "exclude": "core/external/**",
                        "index_new_artifacts": True,
                        "retention_in_days": 45,
                    },
                    {"include": "tools/**", "retention_in_days": 10},
                ],
                "all_other_artifacts": {"retention_in_days": 90},
            }
        },
    )
    assert processor.process("team-x", {"team-x-docker-dev-local": local_spec(xray=cfg)}, dry_run=True) == []


def test_non_json_xray_response_fails_only_that_repo(client, processor):
    # A proxy answering 200 text/html makes the client return the body text.
    existing_local(client)
    client.xray_configs["team-x-docker-dev-local"] = "<html>login</html>"
    cfg = {"team-x-docker-dev-local": local_spec(xray={"retention_in_days": 30})}
    changes = processor.process("team-x", cfg, dry_run=True)

    assert [(c.action, c.error) for c in changes] == [("update", True)]
    assert "expected JSON" in changes[0].details


def test_xray_index_false_with_xray_config_rejected(processor):
    cfg = {"team-x-docker-dev-local": local_spec(xray_index=False, xray={"retention_in_days": 30})}
    with pytest.raises(ConfigError, match="requires xray_index: true"):
        processor.process("team-x", cfg, dry_run=True)


def test_xray_on_virtual_repository_rejected(processor):
    cfg = {
        "team-x-docker-virtual": {
            "type": "virtual",
            "package_type": "docker",
            "repositories": [],
            "xray": {"retention_in_days": 30},
        }
    }
    with pytest.raises(ConfigError, match="only local, remote and federated"):
        processor.process("team-x", cfg, dry_run=True)


@pytest.mark.parametrize(
    ("xray_cfg", "match"),
    [
        ({}, "non-empty mapping"),
        ("30", "non-empty mapping"),
        ({"retention_in_days": 0}, "positive number of days"),
        ({"retention_in_days": "30"}, "positive number of days"),
        ({"retention_in_days": True}, "positive number of days"),
        ({"retention_in_days": 30, **PATTERNS_CFG}, "mutually exclusive"),
        ({"patterns": []}, "non-empty list"),
        ({"patterns": [{"include": "a/**", "retention_in_days": 1}]}, "all_other_artifacts is required"),
        ({"all_other_artifacts": {"retention_in_days": 1}}, "only applies together with 'patterns'"),
        ({"patterns": ["a/**"], "all_other_artifacts": {"retention_in_days": 1}}, r"patterns\[0\] must be a mapping"),
        (
            {"patterns": [{"retention_in_days": 1}], "all_other_artifacts": {"retention_in_days": 1}},
            r"patterns\[0\].include must be a non-empty",
        ),
        (
            {"patterns": [{"include": "a/**"}], "all_other_artifacts": {"retention_in_days": 1}},
            r"patterns\[0\].retention_in_days is required",
        ),
        (
            {"patterns": [{"include": "a/**", "retention_in_days": 1, "scan": True}], "all_other_artifacts": {}},
            r"Unknown keys in .*patterns\[0\]: scan",
        ),
        (
            {
                "patterns": [{"include": "a/**", "retention_in_days": 1, "index_new_artifacts": "yes"}],
                "all_other_artifacts": {"retention_in_days": 1},
            },
            "index_new_artifacts must be a boolean",
        ),
        (
            {"patterns": [{"include": "a/**", "retention_in_days": 1}], "all_other_artifacts": {}},
            "all_other_artifacts.retention_in_days is required",
        ),
        (
            {"patterns": [{"include": "a/**", "retention_in_days": 1}], "all_other_artifacts": {"days": 1}},
            "Unknown keys in .*all_other_artifacts: days",
        ),
    ],
)
def test_xray_validation_errors(processor, xray_cfg, match):
    cfg = {"team-x-docker-dev-local": local_spec(xray=xray_cfg)}
    with pytest.raises(ConfigError, match=match):
        processor.process("team-x", cfg, dry_run=True)
