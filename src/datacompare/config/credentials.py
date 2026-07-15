"""Credential resolution helpers: keyring lookup and log masking."""
from __future__ import annotations
import re

# postgresql://user:PASSWORD@host/db  →  postgresql://user:***@host/db
# jdbc:zenith:@//user:PASSWORD@host/db  →  jdbc:zenith:@//user:***@host/db
_PWD_DSN_RE = re.compile(r"(:{1,2}@?//[^:/@]*:)([^@/]+)(@)")
# password=PASSWORD → password=***
_PWD_KW_RE = re.compile(r"(password=)([^\s&]+)")
# pwd=PASSWORD → pwd=*** (alternate JDBC driver convention)
_PWD_KW_PWD_RE = re.compile(r"(\bpwd=)([^\s&]+)")

_KEYRING_RE = re.compile(r"^keyring://([^/]+)/(.+)$")


def mask_password(text: str) -> str:
    """Redact passwords in DSN-style URLs and query parameters.

    Handles:
    - postgresql://u:secret@h/db  (DSN userinfo)
    - jdbc:xxx://u:secret@h/db    (JDBC userinfo)
    - host=x password=secret user=u   (keyword form)
    - jdbc:xxx://h/db?password=secret (query string)
    - jdbc:xxx://h/db?pwd=secret      (query string, alternate key)
    """
    text = _PWD_DSN_RE.sub(r"\1***\3", text)
    text = _PWD_KW_RE.sub(r"\1***", text)
    text = _PWD_KW_PWD_RE.sub(r"\1***", text)
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
