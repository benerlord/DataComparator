import pytest
from pydantic import ValidationError
from datacompare.config.models import BatchConfig, BatchTaskOverride


def _minimal_sub_task(name: str = "t1", **extra) -> dict:
    return {"name": name, **extra}


def test_batch_config_minimal_valid():
    cfg = BatchConfig(
        name="b",
        tasks=[BatchTaskOverride(**_minimal_sub_task())],
    )
    assert cfg.name == "b"
    assert cfg.on_error == "continue"  # default
    assert len(cfg.tasks) == 1


def test_batch_config_on_error_literal():
    BatchConfig(name="b", on_error="fail_fast",
                tasks=[BatchTaskOverride(**_minimal_sub_task())])
    with pytest.raises(ValidationError):
        BatchConfig(name="b", on_error="bogus",
                    tasks=[BatchTaskOverride(**_minimal_sub_task())])


def test_batch_config_tasks_min_length_one():
    with pytest.raises(ValidationError) as exc:
        BatchConfig(name="b", tasks=[])
    assert "at least 1" in str(exc.value).lower() or "min_length" in str(exc.value).lower()


def test_batch_task_names_must_be_unique():
    with pytest.raises(ValidationError) as exc:
        BatchConfig(name="b", tasks=[
            BatchTaskOverride(**_minimal_sub_task("dup")),
            BatchTaskOverride(**_minimal_sub_task("dup")),
        ])
    assert "unique" in str(exc.value).lower() or "duplicate" in str(exc.value).lower()


def test_batch_task_override_allows_extra_fields():
    """Pre-merge overrides may contain any structure; validated after merge."""
    t = BatchTaskOverride(
        name="t1",
        sources={"left": {"sheets": [{"name": "S1"}]}, "right": {"query": "SELECT 1"}},
        match={"keys": [{"left": "id", "right": "id"}]},
        compare={"fields": []},
    )
    assert t.name == "t1"
    # extra fields accessible as attributes or via model_extra
    assert t.model_extra is not None
    assert "sources" in t.model_extra


def test_batch_config_optional_defaults_blocks():
    """sources/match/compare/output/runtime are all optional at batch level."""
    cfg = BatchConfig(
        name="b",
        sources={"left": {"type": "excel", "path": "a"}, "right": {"type": "excel", "path": "b"}},
        tasks=[BatchTaskOverride(**_minimal_sub_task())],
    )
    assert cfg.sources == {"left": {"type": "excel", "path": "a"},
                            "right": {"type": "excel", "path": "b"}}
    assert cfg.match is None
    assert cfg.compare is None


def test_batch_config_extra_top_level_field_forbidden():
    """Top-level unknown key catches typos early."""
    with pytest.raises(ValidationError):
        BatchConfig(name="b", nonsense_key=1,
                    tasks=[BatchTaskOverride(**_minimal_sub_task())])
