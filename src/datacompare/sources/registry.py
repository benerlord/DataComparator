"""Type-string → DataSource subclass registry (extension point)."""
from __future__ import annotations
from typing import Callable
from .base import DataSource

SOURCE_REGISTRY: dict[str, type[DataSource]] = {}


def register_source(type_name: str) -> Callable[[type[DataSource]], type[DataSource]]:
    def _decorator(cls: type[DataSource]) -> type[DataSource]:
        SOURCE_REGISTRY[type_name] = cls
        return cls
    return _decorator


def get_source_class(type_name: str) -> type[DataSource]:
    if type_name not in SOURCE_REGISTRY:
        raise KeyError(f"unknown source type: {type_name}")
    return SOURCE_REGISTRY[type_name]
