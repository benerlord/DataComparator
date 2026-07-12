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
