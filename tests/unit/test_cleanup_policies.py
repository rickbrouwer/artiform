import pytest

from artiform.exceptions import ConfigError
from artiform.processors.cleanup_policies import CleanupPoliciesProcessor


@pytest.fixture
def processor(client):
    return CleanupPoliciesProcessor(client)


CFG = {
    "docker-30d": {
        "description": "clean old docker images",
        "cron_exp": "0 0 2 * * ?",
        "search_criteria": {
            "package_types": ["docker"],
            "repos": ["team-x-docker-local"],
            "included_packages": ["**"],
            "last_downloaded_before_in_days": 30,
        },
    }
}


def test_create_prefixes_key_and_enables_after_creation(client, processor):
    changes = processor.process("team-x", CFG, dry_run=False)

    assert [(c.action, c.entity) for c in changes] == [("create", "team-x-docker-30d")]
    ((_, key, payload),) = client.called("create_cleanup_policy")
    assert key == "team-x-docker-30d"
    assert payload["key"] == "team-x-docker-30d"
    assert payload["projectKey"] == "team-x"
    assert payload["enabled"] is False
    assert payload["searchCriteria"]["lastDownloadedBeforeInDays"] == 30
    # Absent includedProjects causes a server-side NPE on create.
    assert payload["searchCriteria"]["includedProjects"] == []
    assert client.called("set_cleanup_policy_enabled") == [("set_cleanup_policy_enabled", "team-x-docker-30d", True)]


def test_already_prefixed_key_is_not_double_prefixed(client, processor):
    cfg = {"team-x-docker-30d": CFG["docker-30d"]}
    processor.process("team-x", cfg, dry_run=False)
    ((_, key, _),) = client.called("create_cleanup_policy")
    assert key == "team-x-docker-30d"


def test_explicitly_disabled_policy_is_not_enabled(client, processor):
    cfg = {"docker-30d": {**CFG["docker-30d"], "enabled": False}}
    processor.process("team-x", cfg, dry_run=False)
    assert client.called("set_cleanup_policy_enabled") == []


def test_up_to_date_policy_is_untouched(client, processor):
    processor.process("team-x", CFG, dry_run=False)
    client.calls.clear()
    assert processor.process("team-x", CFG, dry_run=False) == []


def test_adding_cron_updates_existing_policy_instead_of_creating(client, processor):
    # Regression: the GET response omits projectKey; existing policies must
    # still be recognized as this project's, or a re-run 409s on create.
    processor.process("team-x", CFG, dry_run=False)
    client.calls.clear()

    cfg = {"docker-30d": {**CFG["docker-30d"], "cron_exp": "0 0 1 * * ?"}}
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.entity, c.error) for c in changes] == [("update", "team-x-docker-30d", False)]
    assert client.called("create_cleanup_policy") == []
    ((_, _, payload),) = client.called("update_cleanup_policy")
    assert payload["cronExp"] == "0 0 1 * * ?"


def test_update_changes_policy_and_toggles_enablement(client, processor):
    processor.process("team-x", CFG, dry_run=False)
    client.calls.clear()

    cfg = {"docker-30d": {**CFG["docker-30d"], "enabled": False}}
    cfg["docker-30d"]["search_criteria"] = {
        **CFG["docker-30d"]["search_criteria"],
        "last_downloaded_before_in_days": 60,
    }
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.entity) for c in changes] == [("update", "team-x-docker-30d")]
    ((_, _, payload),) = client.called("update_cleanup_policy")
    assert payload["searchCriteria"]["lastDownloadedBeforeInDays"] == 60
    # The PUT carries the current enablement unchanged; the toggle to the
    # desired state goes through the dedicated enablement endpoint.
    assert payload["enabled"] is True
    assert client.called("set_cleanup_policy_enabled") == [("set_cleanup_policy_enabled", "team-x-docker-30d", False)]


def test_update_drops_server_side_month_placeholders(client, processor):
    # Regression: the GET response carries month-variant placeholders; a PUT
    # with both day and month conditions is rejected by the API.
    client.policies["team-x-docker-30d"] = {
        "key": "team-x-docker-30d",
        "projectKey": "team-x",
        "enabled": True,
        "searchCriteria": {
            "packageTypes": ["docker"],
            "repos": ["team-x-docker-local"],
            "includedPackages": ["**"],
            "includedProjects": [],
            "lastDownloadedBeforeInDays": 30,
            "createdBeforeInMonths": None,
            "lastDownloadedBeforeInMonths": 0,
            "keepLastNVersions": None,
        },
    }
    cfg = {"docker-30d": {**CFG["docker-30d"], "cron_exp": "0 0 1 * * ?"}}
    changes = processor.process("team-x", cfg, dry_run=False)

    assert not any(c.error for c in changes)
    ((_, _, payload),) = client.called("update_cleanup_policy")
    criteria = payload["searchCriteria"]
    assert "createdBeforeInMonths" not in criteria
    assert "lastDownloadedBeforeInMonths" not in criteria
    assert "keepLastNVersions" not in criteria
    assert criteria["lastDownloadedBeforeInDays"] == 30
    assert payload["cronExp"] == "0 0 1 * * ?"


def test_update_drops_zero_placeholder_in_unmanaged_family(client, processor):
    # The config manages only created_before_in_days; the server state has a
    # UI-set lastDownloadedBeforeInDays plus a 0-valued month placeholder in
    # that same, unmanaged family. The PUT may not carry both variants.
    client.policies["team-x-docker-30d"] = {
        "key": "team-x-docker-30d",
        "projectKey": "team-x",
        "enabled": True,
        "searchCriteria": {
            "packageTypes": ["docker"],
            "repos": ["team-x-docker-local"],
            "includedPackages": ["**"],
            "includedProjects": [],
            "createdBeforeInDays": 14,
            "lastDownloadedBeforeInDays": 30,
            "lastDownloadedBeforeInMonths": 0,
        },
    }
    cfg = {
        "docker-30d": {
            "cron_exp": "0 0 1 * * ?",
            "search_criteria": {
                "package_types": ["docker"],
                "repos": ["team-x-docker-local"],
                "included_packages": ["**"],
                "created_before_in_days": 14,
            },
        }
    }
    changes = processor.process("team-x", cfg, dry_run=False)

    assert not any(c.error for c in changes)
    ((_, _, payload),) = client.called("update_cleanup_policy")
    criteria = payload["searchCriteria"]
    assert criteria["lastDownloadedBeforeInDays"] == 30
    assert "lastDownloadedBeforeInMonths" not in criteria


def test_enforce_deletes_unmanaged_policies(client, processor):
    client.policies["team-x-old"] = {
        "key": "team-x-old",
        "projectKey": "team-x",
        "enabled": True,
    }
    changes = processor.process("team-x", {"enforce": True, **CFG}, dry_run=False)
    deletes = [(c.action, c.entity) for c in changes if c.action == "delete"]
    assert deletes == [("delete", "team-x-old")]
    assert "team-x-old" not in client.policies


def test_enforce_ignores_global_system_policies(client, processor):
    client.policies["system_repo_cleanup_policy"] = {
        "key": "system_repo_cleanup_policy",
        "enabled": True,
    }
    processor.process("team-x", {"enforce": True, **CFG}, dry_run=False)
    assert "system_repo_cleanup_policy" in client.policies


def test_enforce_ignores_global_policy_with_coincidental_prefix(client, processor):
    # A global policy whose name happens to start with the project prefix but
    # whose listing declares it global (empty projectKey) must not be adopted.
    client.policies["team-x-archive"] = {
        "key": "team-x-archive",
        "projectKey": "",
        "enabled": True,
    }
    processor.process("team-x", {"enforce": True, **CFG}, dry_run=False)
    assert "team-x-archive" in client.policies


def test_null_included_projects_does_not_diff_forever(client, processor):
    processor.process("team-x", CFG, dry_run=False)
    # Simulate the server echoing the null placeholder instead of [].
    client.policies["team-x-docker-30d"]["searchCriteria"]["includedProjects"] = None
    client.calls.clear()
    assert processor.process("team-x", CFG, dry_run=False) == []


def test_policies_of_other_projects_are_not_touched(client, processor):
    client.policies["other-old"] = {
        "key": "other-old",
        "projectKey": "other",
        "enabled": True,
    }
    processor.process("team-x", {"enforce": True, **CFG}, dry_run=False)
    assert "other-old" in client.policies


def test_duplicate_policy_key_after_prefixing_rejected(processor):
    cfg = {
        "docker-30d": CFG["docker-30d"],
        "team-x-docker-30d": CFG["docker-30d"],
    }
    with pytest.raises(ConfigError, match="collide"):
        processor.process("team-x", cfg, dry_run=True)


def test_update_preserves_server_side_fields(client, processor):
    processor.process("team-x", CFG, dry_run=False)
    # Simulate a field added via the UI that the config does not manage.
    client.policies["team-x-docker-30d"]["searchCriteria"]["excludedPackages"] = ["keep"]
    client.calls.clear()

    cfg = {"docker-30d": dict(CFG["docker-30d"])}
    cfg["docker-30d"]["search_criteria"] = {
        **CFG["docker-30d"]["search_criteria"],
        "last_downloaded_before_in_days": 60,
    }
    processor.process("team-x", cfg, dry_run=False)

    ((_, _, payload),) = client.called("update_cleanup_policy")
    assert payload["searchCriteria"]["lastDownloadedBeforeInDays"] == 60
    assert payload["searchCriteria"]["excludedPackages"] == ["keep"]


def test_missing_cleanup_api_reports_license_hint(client, processor):
    client.cleanup_api_available = False
    changes = processor.process("team-x", CFG, dry_run=False)
    assert len(changes) == 1
    assert changes[0].error
    assert "Enterprise" in changes[0].details
