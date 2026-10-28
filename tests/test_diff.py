from artiform.diff import changed_fields, needs_update


def test_extra_server_fields_are_ignored():
    current = {"a": 1, "server_only": "x"}
    assert not needs_update(current, {"a": 1})


def test_missing_key_triggers_update():
    assert needs_update({}, {"a": 1})


def test_changed_value_triggers_update():
    assert needs_update({"a": 1}, {"a": 2})


def test_nested_dict_comparison():
    current = {"admin": {"manage_members": True, "extra": 1}}
    assert not needs_update(current, {"admin": {"manage_members": True}})
    assert needs_update(current, {"admin": {"manage_members": False}})


def test_list_comparison_is_order_sensitive():
    assert needs_update({"envs": ["DEV", "PROD"]}, {"envs": ["PROD", "DEV"]})
    assert not needs_update({"envs": ["DEV"]}, {"envs": ["DEV"]})


def test_changed_fields_describes_differences():
    current = {"a": 1, "nested": {"x": 1}}
    desired = {"a": 2, "nested": {"x": 2}, "new": 3}
    out = changed_fields(current, desired)
    assert "a: 1 -> 2" in out
    assert "nested.x: 1 -> 2" in out
    assert "new: <unset> -> 3" in out
