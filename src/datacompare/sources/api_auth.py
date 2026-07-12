"""httpx.Client construction with auth strategies."""
from __future__ import annotations
import httpx
from datacompare.config.models import APIConnection, BearerAuth, CookieAuth, NoAuth
from datacompare.config.errors import ConfigError


def build_client(conn: APIConnection) -> httpx.Client:
    client = httpx.Client(base_url=conn.base_url, timeout=30)
    auth = conn.auth
    if isinstance(auth, NoAuth):
        return client
    if isinstance(auth, BearerAuth):
        client.headers["Authorization"] = f"Bearer {auth.token}"
        return client
    if isinstance(auth, CookieAuth):
        r = client.request(
            auth.login_method, auth.login_url, json=auth.login_body,
        )
        r.raise_for_status()
        for name in auth.cookie_names:
            if client.cookies.get(name) is None:
                raise ConfigError(f"cookie '{name}' not returned by login endpoint")
        return client
    raise ConfigError(f"unknown auth kind: {type(auth).__name__}")
