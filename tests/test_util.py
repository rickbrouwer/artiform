from artiform.util import deep_merge, to_camel, to_snake


def test_to_camel_converts_nested_keys():
    payload = {
        "package_type": "docker",
        "search_criteria": {"last_downloaded_before_in_days": 30, "repos": ["a-b"]},
        "members": [{"group_name": "x"}],
    }
    assert to_camel(payload) == {
        "packageType": "docker",
        "searchCriteria": {"lastDownloadedBeforeInDays": 30, "repos": ["a-b"]},
        "members": [{"groupName": "x"}],
    }


def test_to_snake_converts_nested_keys():
    payload = {"packageType": "docker", "rclass": "local", "projectKey": "x"}
    assert to_snake(payload) == {
        "package_type": "docker",
        "rclass": "local",
        "project_key": "x",
    }


def test_camel_snake_roundtrip():
    original = {"created_before_in_days": 1, "cron_exp": "0 0 2 * * ?"}
    assert to_snake(to_camel(original)) == original


def test_deep_merge_merges_dicts_and_replaces_lists():
    base = {"a": 1, "nested": {"x": 1, "y": 2}, "list": [1, 2]}
    override = {"nested": {"y": 3}, "list": [9], "b": 2}
    assert deep_merge(base, override) == {
        "a": 1,
        "nested": {"x": 1, "y": 3},
        "list": [9],
        "b": 2,
    }


def test_deep_merge_does_not_mutate_inputs():
    base = {"nested": {"x": 1}}
    override = {"nested": {"y": 2}}
    deep_merge(base, override)
    assert base == {"nested": {"x": 1}}
    assert override == {"nested": {"y": 2}}
