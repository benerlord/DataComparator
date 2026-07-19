"""Sentinel value for regex-fullmatch failure on compare fields.

Soft-fail counterpart to KeyRegexMismatchError: field regex mismatch on any
single row returns a RegexError instance instead of aborting the task, so the
row surfaces as a REGEX_ERROR diff and other rows keep running.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RegexError:
    original: str
    pattern: str
