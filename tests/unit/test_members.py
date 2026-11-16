import pytest

from artiform.exceptions import ConfigError
from artiform.processors.members import MembersProcessor


@pytest.fixture
def processor(client):
    return MembersProcessor(client)


@pytest.fixture(autouse=True)
def project(client):
    client.projects["team-x"] = {"project_key": "team-x"}


def test_assign_existing_group_with_roles(client, processor):
    client.groups["team-x-dev"] = {"name": "team-x-dev"}
    cfg = {"groups": {"team-x-dev": {"roles": ["Developer"]}}}
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.entity) for c in changes] == [("create", "groups:team-x-dev")]
    assert client.memberships[("team-x", "groups")] == {"team-x-dev": ["Developer"]}
    assert client.called("import_ldap_group") == []


def test_missing_group_is_imported_from_ldap(client, processor):
    cfg = {
        "groups": {
            "team-x-rm": {
                "roles": ["Release Manager"],
                "import_from_ldap": "corp-ldap",
            }
        }
    }
    changes = processor.process("team-x", cfg, dry_run=False)

    assert not any(c.error for c in changes)
    assert client.called("import_ldap_group") == [("import_ldap_group", "team-x-rm", "corp-ldap")]
    assert client.memberships[("team-x", "groups")] == {"team-x-rm": ["Release Manager"]}


def test_missing_group_without_ldap_import_is_an_error(client, processor):
    cfg = {"groups": {"ghost": {"roles": ["Developer"]}}}
    changes = processor.process("team-x", cfg, dry_run=False)
    assert len(changes) == 1
    assert changes[0].error
    assert "does not exist" in changes[0].details
    assert ("team-x", "groups") not in client.memberships


def test_role_change_updates_membership(client, processor):
    client.groups["team-x-dev"] = {"name": "team-x-dev"}
    client.memberships[("team-x", "groups")] = {"team-x-dev": ["Viewer"]}
    cfg = {"groups": {"team-x-dev": {"roles": ["Developer", "Contributor"]}}}
    changes = processor.process("team-x", cfg, dry_run=False)

    assert [(c.action, c.entity) for c in changes] == [("update", "groups:team-x-dev")]
    assert client.memberships[("team-x", "groups")] == {"team-x-dev": ["Contributor", "Developer"]}


def test_role_order_does_not_matter(client, processor):
    client.groups["team-x-dev"] = {"name": "team-x-dev"}
    client.memberships[("team-x", "groups")] = {"team-x-dev": ["Developer", "Contributor"]}
    cfg = {"groups": {"team-x-dev": {"roles": ["Contributor", "Developer"]}}}
    assert processor.process("team-x", cfg, dry_run=False) == []


def test_users_and_groups_are_managed_together(client, processor):
    client.groups["team-x-dev"] = {"name": "team-x-dev"}
    cfg = {
        "users": {"alice": {"roles": ["Project Admin"]}},
        "groups": {"team-x-dev": {"roles": ["Developer"]}},
    }
    changes = processor.process("team-x", cfg, dry_run=False)
    assert {c.entity for c in changes} == {"users:alice", "groups:team-x-dev"}
    assert client.memberships[("team-x", "users")] == {"alice": ["Project Admin"]}


def test_enforce_removes_unmanaged_members(client, processor):
    client.memberships[("team-x", "users")] = {
        "alice": ["Project Admin"],
        "bob": ["Viewer"],
    }
    client.memberships[("team-x", "groups")] = {"old-group": ["Developer"]}
    cfg = {"enforce": True, "users": {"alice": {"roles": ["Project Admin"]}}}
    changes = processor.process("team-x", cfg, dry_run=False)
    assert {(c.action, c.entity) for c in changes} == {
        ("delete", "users:bob"),
        ("delete", "groups:old-group"),
    }
    assert client.memberships[("team-x", "users")] == {"alice": ["Project Admin"]}
    assert client.memberships[("team-x", "groups")] == {}


def test_enforce_with_empty_members_is_rejected(client, processor):
    client.memberships[("team-x", "users")] = {"alice": ["Project Admin"]}
    with pytest.raises(ConfigError, match="delete everything"):
        processor.process("team-x", {"enforce": True}, dry_run=False)
    assert client.memberships[("team-x", "users")] == {"alice": ["Project Admin"]}


def test_uppercase_member_name_rejected(processor):
    with pytest.raises(ConfigError, match="lowercase"):
        processor.process("team-x", {"users": {"Alice": {"roles": ["Viewer"]}}}, dry_run=True)


def test_nonexistent_project_yields_empty_current_state(client, processor):
    del client.projects["team-x"]
    assert processor.current_entities("team-x", {}) == {}


def test_empty_roles_rejected(processor):
    with pytest.raises(ConfigError, match="non-empty 'roles'"):
        processor.process("team-x", {"users": {"alice": {"roles": []}}}, dry_run=True)


def test_unknown_member_field_rejected(processor):
    with pytest.raises(ConfigError, match="Unknown keys"):
        processor.process(
            "team-x",
            {"users": {"alice": {"roles": ["Viewer"], "rolez": []}}},
            dry_run=True,
        )
