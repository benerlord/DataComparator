"""YAML → TaskConfig with ${ENV} and {{param.x}} substitution."""
from __future__ import annotations
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from ruamel.yaml import YAML
from pydantic import ValidationError
from .models import TaskConfig, AnyConnection, BatchConfig
from .errors import ConfigError
from .merge import deep_merge

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


def merge_sub_task(defaults: dict, sub_task: dict) -> dict:
    """Produce a full TaskConfig dict by merging defaults with a sub-task's overrides.

    Strips 'name' from sub_task before merging (name only lives at sub-task level)
    then re-attaches after merge.
    """
    sub_copy = dict(sub_task)
    name = sub_copy.pop("name")
    clean_defaults = {k: v for k, v in defaults.items() if v is not None}
    merged = deep_merge(clean_defaults, sub_copy)
    merged["name"] = name
    return merged


def load_task_or_batch(path: Path, params: dict[str, str] | None = None) -> TaskConfig | BatchConfig:
    """Parse YAML; return BatchConfig if 'tasks:' key present, else TaskConfig.

    For batch mode, every sub-task is merged with defaults and validated as a
    TaskConfig at load time — errors from all sub-tasks are collected before
    raising a single aggregated ConfigError.
    """
    params = params or {}
    yaml = YAML(typ="safe")
    with open(path, encoding="utf-8") as f:
        raw = yaml.load(f)
    if raw is None:
        raise ConfigError(f"empty task file: {path}")
    substituted = _walk_substitute(raw, params)

    if "tasks" in substituted:
        return _load_batch(substituted)
    return _load_single(substituted)


def _check_canonical_uniqueness(task: TaskConfig) -> None:
    """Ensure key.canonical and field.canonical don't collide across the task.
    Fail-fast at load time with a clear ConfigError instead of surfacing as a
    pandas 'column label X is not unique' at merge time."""
    from datacompare.normalize.columns import key_canonical_name, field_canonical_name
    seen: dict[str, str] = {}
    for k in task.match.keys:
        canonical = key_canonical_name(k)
        if canonical in seen:
            raise ConfigError(
                f"canonical column name '{canonical}' is duplicate: "
                f"already used by {seen[canonical]}, now also by key "
                f"(left={k.left!r}, right={k.right!r})",
                path="match.keys",
                suggestion="add 'alias' to one of the conflicting keys",
            )
        seen[canonical] = f"key (left={k.left!r}, right={k.right!r})"
    for f in task.compare.fields:
        canonical = field_canonical_name(f)
        if canonical in seen:
            raise ConfigError(
                f"canonical column name '{canonical}' is duplicate: "
                f"already used by {seen[canonical]}, now also by field "
                f"(left={f.left!r}, right={f.right!r})",
                path="compare.fields",
                suggestion="add 'alias' to the conflicting key, or rename the field",
            )
        seen[canonical] = f"field (left={f.left!r}, right={f.right!r})"


def _load_single(substituted: dict) -> TaskConfig:
    try:
        cfg = TaskConfig.model_validate(substituted)
    except ValidationError as e:
        errors = "\n".join(f"  · {err['loc']}: {err['msg']}" for err in e.errors())
        raise ConfigError(f"task config validation failed:\n{errors}") from e
    _check_canonical_uniqueness(cfg)
    return cfg


def _load_batch(substituted: dict) -> BatchConfig:
    try:
        batch = BatchConfig.model_validate(substituted)
    except ValidationError as e:
        errors = "\n".join(f"  · {err['loc']}: {err['msg']}" for err in e.errors())
        raise ConfigError(f"batch config validation failed:\n{errors}") from e

    defaults_dict = {
        k: v for k, v in {
            "sources": batch.sources,
            "match": batch.match,
            "compare": batch.compare,
            "output": batch.output,
            "runtime": batch.runtime,
        }.items() if v is not None
    }
    per_sub_errors: list[str] = []
    for sub in batch.tasks:
        sub_dict = {"name": sub.name, **(sub.model_extra or {})}
        merged = merge_sub_task(defaults_dict, sub_dict)
        try:
            sub_cfg = TaskConfig.model_validate(merged)
            _check_canonical_uniqueness(sub_cfg)
        except ValidationError as e:
            errs = "; ".join(f"{err['loc']}: {err['msg']}" for err in e.errors())
            per_sub_errors.append(f"  · [{sub.name}] {errs}")
        except ConfigError as e:
            per_sub_errors.append(f"  · [{sub.name}] {e}")
    if per_sub_errors:
        raise ConfigError(
            "batch sub-task validation failed:\n" + "\n".join(per_sub_errors)
        )
    return batch


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
