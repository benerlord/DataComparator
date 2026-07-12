"""YAML → TaskConfig with ${ENV} and {{param.x}} substitution."""
from __future__ import annotations
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from ruamel.yaml import YAML
from pydantic import ValidationError
from .models import TaskConfig, AnyConnection
from .errors import ConfigError

_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
_PARAM_RE = re.compile(r"\{\{param\.([a-zA-Z_][a-zA-Z0-9_]*)\}\}")
_BUILTIN_RE = re.compile(r"\{\{(today|now)\}\}")


def substitute(value: str, params: dict[str, str]) -> str:
    """Apply ${ENV}, {{param.x}}, {{today}}/{{now}} substitutions in order."""
    def _env(match: re.Match) -> str:
        key = match.group(1)
        v = os.environ.get(key)
        if v is None:
            raise ConfigError(f"environment variable ${{{key}}} is not set")
        return v

    def _param(match: re.Match) -> str:
        key = match.group(1)
        if key not in params:
            raise ConfigError(f"{{{{param.{key}}}}} not provided", path=f"param.{key}")
        return params[key]

    def _builtin(match: re.Match) -> str:
        name = match.group(1)
        now = datetime.now()
        return now.strftime("%Y-%m-%d") if name == "today" else now.isoformat()

    value = _ENV_RE.sub(_env, value)
    value = _PARAM_RE.sub(_param, value)
    value = _BUILTIN_RE.sub(_builtin, value)
    return value


def _walk_substitute(node: Any, params: dict[str, str]) -> Any:
    if isinstance(node, str):
        return substitute(node, params)
    if isinstance(node, dict):
        return {k: _walk_substitute(v, params) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk_substitute(v, params) for v in node]
    return node


def load_task(path: Path, params: dict[str, str] | None = None) -> TaskConfig:
    """Parse YAML, substitute placeholders, validate into TaskConfig."""
    params = params or {}
    yaml = YAML(typ="safe")
    with open(path, encoding="utf-8") as f:
        raw = yaml.load(f)
    if raw is None:
        raise ConfigError(f"empty task file: {path}")
    substituted = _walk_substitute(raw, params)
    try:
        return TaskConfig.model_validate(substituted)
    except ValidationError as e:
        errors = "\n".join(f"  · {err['loc']}: {err['msg']}" for err in e.errors())
        raise ConfigError(f"task config validation failed:\n{errors}") from e


def load_connections(path: Path) -> dict[str, AnyConnection]:
    """Parse connections YAML, substitute env vars, validate each entry."""
    yaml = YAML(typ="safe")
    with open(path, encoding="utf-8") as f:
        raw = yaml.load(f) or {}
    result: dict[str, AnyConnection] = {}
    for name, entry in raw.items():
        substituted = _walk_substitute(entry, params={})
        try:
            from pydantic import TypeAdapter
            adapter = TypeAdapter(AnyConnection)
            result[name] = adapter.validate_python(substituted)
        except ValidationError as e:
            raise ConfigError(f"connection '{name}' invalid: {e}") from e
    return result
