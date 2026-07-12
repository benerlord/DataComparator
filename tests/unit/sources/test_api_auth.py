import httpx
import respx
from datacompare.sources.api_auth import build_client
from datacompare.config.models import APIConnection, BearerAuth, CookieAuth, NoAuth


def test_no_auth_client_no_headers():
    conn = APIConnection(base_url="http://api.test", auth=NoAuth())
    client = build_client(conn)
    assert "Authorization" not in client.headers


def test_bearer_auth_sets_header():
    conn = APIConnection(base_url="http://api.test", auth=BearerAuth(token="my_token"))
    client = build_client(conn)
    assert client.headers["Authorization"] == "Bearer my_token"


@respx.mock
def test_cookie_auth_logs_in_and_sets_cookies():
    respx.post("http://api.test/login").mock(
        return_value=httpx.Response(
            200,
            headers=[("set-cookie", "SESSIONID=abc; Path=/"),
                     ("set-cookie", "XSRF-TOKEN=xyz; Path=/")],
        )
    )
    conn = APIConnection(
        base_url="http://api.test",
        auth=CookieAuth(
            login_url="/login",
            login_body={"u": "user", "p": "pwd"},
            cookie_names=["SESSIONID", "XSRF-TOKEN"],
        ),
    )
    client = build_client(conn)
    assert client.cookies.get("SESSIONID") == "abc"
    assert client.cookies.get("XSRF-TOKEN") == "xyz"
