import os
from pathlib import Path
import pytest
from datacompare.config.loader import load_task, substitute
from datacompare.config.errors import ConfigError


def test_substitute_env_var(monkeypatch):
    monkeypatch.setenv("FOO", "bar")
    assert substitute("hello ${FOO}", params={}) == "hello bar"


def test_substitute_param():
    assert substitute("month={{param.month}}", params={"month": "2026-07"}) == "month=2026-07"


def test_substitute_today():
    result = substitute("{{today}}", params={})
    assert len(result) == 10  # YYYY-MM-DD
    assert result[4] == "-" and result[7] == "-"


def test_substitute_missing_env_raises(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    with pytest.raises(ConfigError, match="MISSING_VAR"):
        substitute("${MISSING_VAR}", params={})


def test_substitute_missing_param_raises():
    with pytest.raises(ConfigError, match="param.month"):
        substitute("{{param.month}}", params={})


def test_load_task_minimal(tmp_path, monkeypatch):
    monkeypatch.setenv("GAUSS_PWD", "secret")
    p = Path("tests/fixtures/config/minimal_task.yaml")
    task = load_task(p, params={"month": "2026-07"})
    assert task.name == "test"
    assert task.sources["left"].type == "excel"
    assert task.sources["right"].type == "gaussdb"


# ---------- Batch mode (T3) ---------------------------------------------------

from datacompare.config.loader import load_task_or_batch, merge_sub_task
from datacompare.config.models import TaskConfig, BatchConfig


_SINGLE_YAML = """
name: single_task
sources:
  left: {type: excel, path: a.xlsx}
  right: {type: excel, path: b.xlsx}
match:
  keys: [{left: id, right: id}]
compare:
  fields: [{left: v, right: v}]
output:
  dir: ./out
  formats: [json]
"""

_BATCH_YAML = """
name: batch_x
on_error: continue
sources:
  left: {type: excel, path: manage.xlsx}
  right: {type: excel, path: right.xlsx}
match:
  keys: [{left: id, right: id}]
compare:
  fields: [{left: v, right: v}]
output:
  dir: ./out
  formats: [json]
tasks:
  - name: sub1
    sources:
      left: {sheets: [{name: "S1"}]}
      right: {path: right1.xlsx}
  - name: sub2
    sources:
      left: {sheets: [{name: "S2"}]}
      right: {path: right2.xlsx}
"""


def test_load_returns_taskconfig_when_no_tasks_key(tmp_path):
    p = tmp_path / "single.yaml"
    p.write_text(_SINGLE_YAML)
    cfg = load_task_or_batch(p, {})
    assert isinstance(cfg, TaskConfig)
    assert cfg.name == "single_task"


def test_load_returns_batchconfig_when_tasks_key_present(tmp_path):
    p = tmp_path / "batch.yaml"
    p.write_text(_BATCH_YAML)
    cfg = load_task_or_batch(p, {})
    assert isinstance(cfg, BatchConfig)
    assert cfg.name == "batch_x"
    assert len(cfg.tasks) == 2


def test_load_batch_with_empty_tasks_list_raises(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("name: x\ntasks: []\n")
    with pytest.raises(ConfigError):
        load_task_or_batch(p, {})


def test_merge_sub_task_produces_full_task_dict():
    defaults = {
        "sources": {
            "left": {"type": "excel", "path": "manage.xlsx"},
            "right": {"type": "gaussdb", "connection": "c"},
        },
        "match": {"keys": [{"left": "id", "right": "id"}]},
        "compare": {"fields": [{"left": "v", "right": "v"}]},
        "output": {"dir": "./out", "formats": ["json"]},
    }
    sub = {
        "name": "s1",
        "sources": {
            "left": {"sheets": [{"name": "S1"}]},
            "right": {"query": "SELECT 1"},
        },
    }
    merged = merge_sub_task(defaults, sub)
    assert merged["name"] == "s1"
    assert merged["sources"]["left"]["path"] == "manage.xlsx"
    assert merged["sources"]["left"]["sheets"] == [{"name": "S1"}]
    assert merged["sources"]["right"]["connection"] == "c"
    assert merged["sources"]["right"]["query"] == "SELECT 1"


def test_load_batch_validates_each_sub_task_upfront(tmp_path):
    bad = """
name: bad_batch
sources:
  left: {type: excel, path: a.xlsx}
tasks:
  - name: incomplete
    sources:
      left: {sheets: [{name: S1}]}
    match:
      keys: [{left: id, right: id}]
    compare:
      fields: []
    output:
      dir: ./out
      formats: [json]
"""
    p = tmp_path / "bad.yaml"
    p.write_text(bad)
    with pytest.raises(ConfigError) as exc:
        load_task_or_batch(p, {})
    assert "incomplete" in str(exc.value) or "right" in str(exc.value)


def test_load_batch_reports_all_sub_task_errors(tmp_path):
    bad = """
name: bad_batch
sources:
  left: {type: excel, path: a.xlsx}
  right: {type: gaussdb, connection: c}
match:
  keys: [{left: id, right: id}]
compare:
  fields: []
output:
  dir: ./out
  formats: [json]
tasks:
  - name: sub_a
    sources: {right: {}}
  - name: sub_b
    sources: {right: {}}
"""
    p = tmp_path / "bad.yaml"
    p.write_text(bad)
    with pytest.raises(ConfigError) as exc:
        load_task_or_batch(p, {})
    msg = str(exc.value)
    assert "sub_a" in msg and "sub_b" in msg
