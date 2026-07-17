from datacompare.config.merge import deep_merge


def test_deep_merge_flat_dict():
    result = deep_merge({"a": 1, "b": 2}, {"b": 20, "c": 3})
    assert result == {"a": 1, "b": 20, "c": 3}


def test_deep_merge_nested_dict():
    d = {"a": 1, "b": {"c": 2, "d": 3}}
    o = {"b": {"d": 40, "e": 5}}
    assert deep_merge(d, o) == {"a": 1, "b": {"c": 2, "d": 40, "e": 5}}


def test_deep_merge_list_replaces_not_extends():
    d = {"formats": ["html", "json"]}
    o = {"formats": ["csv"]}
    assert deep_merge(d, o) == {"formats": ["csv"]}


def test_deep_merge_empty_list_replaces():
    d = {"formats": ["html"]}
    o = {"formats": []}
    assert deep_merge(d, o) == {"formats": []}


def test_deep_merge_none_in_override_clears_defaults():
    d = {"a": 1, "b": "keep"}
    o = {"b": None}
    assert deep_merge(d, o) == {"a": 1, "b": None}


def test_deep_merge_missing_key_inherits_from_defaults():
    d = {"a": 1, "b": 2}
    o = {"a": 10}
    assert deep_merge(d, o) == {"a": 10, "b": 2}


def test_deep_merge_type_change_in_nested_dict_replaces_whole_dict():
    """right.type=gaussdb defaults dropped when override switches to right.type=api."""
    d = {"right": {"type": "gaussdb", "connection": "prod", "timeout": 30}}
    o = {"right": {"type": "api", "url": "/v1/vms"}}
    assert deep_merge(d, o) == {"right": {"type": "api", "url": "/v1/vms"}}


def test_deep_merge_same_type_deep_merges_normally():
    d = {"right": {"type": "gaussdb", "connection": "prod", "timeout": 30}}
    o = {"right": {"type": "gaussdb", "query": "SELECT 1"}}
    assert deep_merge(d, o) == {
        "right": {"type": "gaussdb", "connection": "prod", "timeout": 30, "query": "SELECT 1"}
    }


def test_deep_merge_type_change_ignored_when_only_one_side_has_type():
    """If defaults has type but override doesn't specify type, deep-merge normally."""
    d = {"right": {"type": "gaussdb", "connection": "prod"}}
    o = {"right": {"query": "SELECT 1"}}
    assert deep_merge(d, o) == {
        "right": {"type": "gaussdb", "connection": "prod", "query": "SELECT 1"}
    }


def test_deep_merge_does_not_mutate_inputs():
    d = {"a": {"b": 1}}
    o = {"a": {"c": 2}}
    deep_merge(d, o)
    assert d == {"a": {"b": 1}}
    assert o == {"a": {"c": 2}}
