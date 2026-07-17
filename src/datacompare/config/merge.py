"""Pure-function deep merge for batch YAML defaults + sub-task overrides.

Rules (see docs/superpowers/specs/2026-07-17-multi-task-yaml-design.md § deep merge):
- dict: recursive merge; override keys win
- list: override replaces defaults entirely (no concat)
- nested dict with 'type' key differing between defaults and override:
  override wins wholesale (defaults' other keys dropped)
- None in override explicitly overrides (does NOT mean "inherit")
"""
from __future__ import annotations

import copy
from typing import Any


def deep_merge(defaults: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict merging override on top of defaults. Inputs are not mutated."""
    result: dict[str, Any] = copy.deepcopy(defaults)
    for key, override_val in override.items():
        if key not in result:
            result[key] = copy.deepcopy(override_val)
            continue
        default_val = result[key]
        if isinstance(default_val, dict) and isinstance(override_val, dict):
            d_type = default_val.get("type")
            o_type = override_val.get("type")
            if d_type is not None and o_type is not None and d_type != o_type:
                result[key] = copy.deepcopy(override_val)
            else:
                result[key] = deep_merge(default_val, override_val)
        else:
            result[key] = copy.deepcopy(override_val)
    return result
