"""Credential resolution helpers: keyring lookup and log masking."""
from __future__ import annotations
import re

_PWD_DSN_RE = re.compile(r"(://[^:]+:)([^@]+)(@)")
_PWD_KW_RE = re.compile(r"(password=)([^\s]+)")
_KEYRING_RE = re.compile(r"^keyring://([^/]+)/(.+)$")


def mask_password(text: str) -> str:
    """Redact passwords in DSN-style URLs and 'password=xxx' patterns."""
    text = _PWD_DSN_RE.sub(r"\1***\3", text)
    text = _PWD_KW_RE.sub(r"\1***", text)
    return text


def resolve_keyring(value: str) -> str:
    """If value is 'keyring://service/user', look up in OS keyring; else passthrough."""
    match = _KEYRING_RE.match(value)
    if not match:
        return value
    import keyring
    service, user = match.group(1), match.group(2)
    result = keyring.get_password(service, user)
    if result is None:
        from .errors import ConfigError
        raise ConfigError(f"keyring lookup miss: {service}/{user}")
    return result
