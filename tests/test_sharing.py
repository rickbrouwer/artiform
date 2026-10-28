import pytest

from artiform.exceptions import ConfigError
from artiform.processors.repositories import RepositoriesProcessor


@pytest.fixture
def processor(client):
    return RepositoriesProcessor(client)


def remote_spec(**extra):
    return {
        "type": "remote",
        "package_type": "npm",
        "url": "https://registry.npmjs.org",
        **extra,
    }


def existing_remote(client, shares=None):
    client.repos["platform-npm-remote"] = {
        "key": "platform-npm-remote",
        "rclass": "remote",
        "packageType": "npm",
        "url": "https://registry.npmjs.org",
        "environments": ["DEV"],
        "projectKey": "platform",
    }
    if shares is not None:
        client.repo_shares["platform-npm-remote"] = shares


def test_shares_applied_on_create(client, processor):
    cfg = {"platform-npm-remote": remote_spec(share_with={"projects": ["team-x", "team-y"]})}
    changes = processor.process("platform", cfg, dry_run=False)

    assert not any(c.error for c in changes)
    # share_with is a reserved key and must not reach the repository API.
    ((_, _, payload),) = client.called("create_repository")
    assert "shareWith" not in payload and "share_with" not in payload
    assert client.called("share_repository") == [
        ("share_repository", "platform-npm-remote", "team-x", True),
        ("share_repository", "platform-npm-remote", "team-y", True),
    ]


def test_share_added_and_removed_authoritatively(client, processor):
    existing_remote(client, {"projects": {"team-x", "team-old"}, "all": False, "read_only": True})
    cfg = {"platform-npm-remote": remote_spec(share_with={"projects": ["team-x", "team-new"]})}
    changes = processor.process("platform", cfg, dry_run=False)

    assert [(c.action, c.error) for c in changes] == [("update", False)]
    assert client.called("unshare_repository") == [("unshare_repository", "platform-npm-remote", "team-old")]
    assert client.called("share_repository") == [("share_repository", "platform-npm-remote", "team-new", True)]


def test_unchanged_shares_are_untouched(client, processor):
    existing_remote(client, {"projects": {"team-x"}, "all": False, "read_only": True})
    cfg = {"platform-npm-remote": remote_spec(share_with={"projects": ["team-x"]})}
    assert processor.process("platform", cfg, dry_run=False) == []


def test_read_only_change_recreates_shares(client, processor):
    existing_remote(client, {"projects": {"team-x"}, "all": False, "read_only": True})
    cfg = {"platform-npm-remote": remote_spec(share_with={"projects": ["team-x"], "read_only": False})}
    changes = processor.process("platform", cfg, dry_run=False)

    assert not any(c.error for c in changes)
    # The API has no share update; toggling read_only is unshare + share.
    assert client.called("unshare_repository") == [("unshare_repository", "platform-npm-remote", "team-x")]
    assert client.called("share_repository") == [("share_repository", "platform-npm-remote", "team-x", False)]


def test_share_with_all_projects(client, processor):
    existing_remote(client, {"projects": {"team-x"}, "all": False, "read_only": True})
    cfg = {"platform-npm-remote": remote_spec(share_with={"all": True})}
    changes = processor.process("platform", cfg, dry_run=False)

    assert not any(c.error for c in changes)
    assert client.called("unshare_repository") == [("unshare_repository", "platform-npm-remote", "team-x")]
    assert client.called("share_repository_with_all") == [("share_repository_with_all", "platform-npm-remote", True)]


def test_empty_share_with_clears_all_shares(client, processor):
    existing_remote(client, {"projects": {"team-x"}, "all": True, "read_only": True})
    cfg = {"platform-npm-remote": remote_spec(share_with={})}
    changes = processor.process("platform", cfg, dry_run=False)

    assert not any(c.error for c in changes)
    assert client.called("unshare_repository") == [("unshare_repository", "platform-npm-remote", "team-x")]
    assert client.called("unshare_repository_with_all") == [("unshare_repository_with_all", "platform-npm-remote")]


def test_absent_share_with_leaves_sharing_untouched(client, processor):
    existing_remote(client, {"projects": {"team-x"}, "all": False, "read_only": True})
    cfg = {"platform-npm-remote": remote_spec()}
    assert processor.process("platform", cfg, dry_run=False) == []
    assert client.repo_shares["platform-npm-remote"]["projects"] == {"team-x"}


def test_dry_run_plans_share_change_without_applying(client, processor):
    existing_remote(client)
    cfg = {"platform-npm-remote": remote_spec(share_with={"projects": ["team-x"]})}
    changes = processor.process("platform", cfg, dry_run=True)

    assert [(c.action, c.entity) for c in changes] == [("update", "platform-npm-remote")]
    assert "share_with" in changes[0].details
    assert client.called("share_repository") == []


def test_enforce_in_consuming_project_does_not_delete_shared_repo(client, processor):
    # Regression: the project listing includes repos shared with the project;
    # team-x's enforce must not delete team-y's shared remote.
    existing_remote(client, {"projects": {"team-x"}, "all": False, "read_only": True})
    client.repos["platform-npm-remote"]["projectKey"] = "team-y"
    client.repos["team-x-generic-local"] = {
        "key": "team-x-generic-local",
        "rclass": "local",
        "packageType": "generic",
        "environments": ["DEV"],
        "projectKey": "team-x",
    }
    cfg = {
        "enforce": True,
        "team-x-generic-local": {"type": "local", "package_type": "generic"},
    }
    changes = processor.process("team-x", cfg, dry_run=False)

    assert changes == []
    assert "platform-npm-remote" in client.repos


def test_share_validation_errors(client, processor):
    for share_cfg, match in (
        ({"projects": ["team-x"], "all": True}, "mutually exclusive"),
        ({"projects": ["platform"]}, "own project"),
        ({"projectz": ["team-x"]}, "Unknown keys"),
        ({"projects": "team-x"}, "list of project keys"),
    ):
        with pytest.raises(ConfigError, match=match):
            processor.process(
                "platform",
                {"platform-npm-remote": remote_spec(share_with=share_cfg)},
                dry_run=True,
            )


def test_share_on_virtual_repository_rejected(client, processor):
    cfg = {
        "platform-npm-virtual": {
            "type": "virtual",
            "package_type": "npm",
            "repositories": [],
            "share_with": {"projects": ["team-x"]},
        }
    }
    with pytest.raises(ConfigError, match="only local and remote"):
        processor.process("platform", cfg, dry_run=True)
