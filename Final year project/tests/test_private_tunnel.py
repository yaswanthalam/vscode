import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import PASSWORD

ORIGIN = "https://fictional-student-8000.usw2.devtunnels.ms"
FORWARDED = {
    "X-Forwarded-Proto": "https",
    "X-Forwarded-Host": ORIGIN.removeprefix("https://"),
    "Origin": ORIGIN,
    "X-Requested-With": "HealthLens",
}


def tunnel_settings(settings):
    settings.transport_mode = "private_tunnel"
    settings.app_origin = ORIGIN
    return settings


def test_private_tunnel_https_session_and_exact_origin(settings):
    app = create_app(tunnel_settings(settings))
    with TestClient(
        app,
        base_url=ORIGIN,
        headers=FORWARDED,
        client=("127.0.0.1", 50000),
    ) as client:
        assert client.get("/health").status_code == 200
        response = client.post(
            "/api/auth/register",
            json={
                "username": "tunnel-student",
                "password": PASSWORD,
            },
        )
        assert response.status_code == 201
        assert "secure" in response.headers["set-cookie"].lower()
        assert client.get("/api/auth/me").json()["username"] == "tunnel-student"
        assert (
            client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code
            == 403
        )
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/auth/me").status_code == 401


def test_loopback_proxy_hop_preserves_external_https_cookie(settings):
    with TestClient(
        create_app(tunnel_settings(settings)),
        base_url="http://127.0.0.1:8000",
        headers=FORWARDED,
        client=("127.0.0.1", 50000),
    ) as proxy:
        response = proxy.post(
            "/api/auth/register",
            json={
                "username": "proxy-student",
                "password": PASSWORD,
            },
        )
        assert response.status_code == 201
        token = proxy.cookies.get("healthlens_session")
        # A TLS-terminating proxy forwards the Cookie already sent by the HTTPS browser.
        me = proxy.get("/api/auth/me", headers={"Cookie": f"healthlens_session={token}"})
        assert me.json()["username"] == "proxy-student"
        assert "secure" in response.headers["set-cookie"].lower()


def test_tunnel_rewritten_origin_allows_same_origin_browser_registration(settings):
    with TestClient(
        create_app(tunnel_settings(settings)),
        base_url="http://127.0.0.1:8000",
        headers={
            **FORWARDED,
            "Origin": "http://localhost:8000",
            "Sec-Fetch-Site": "same-origin",
        },
        client=("127.0.0.1", 50000),
    ) as proxy:
        response = proxy.post(
            "/api/auth/register",
            json={
                "username": "rewritten-origin",
                "password": PASSWORD,
            },
        )
        assert response.status_code == 201
        assert "secure" in response.headers["set-cookie"].lower()
        token = proxy.cookies.get("healthlens_session")
        assert (
            proxy.post(
                "/api/auth/logout",
                headers={
                    "Cookie": f"healthlens_session={token}",
                },
            ).status_code
            == 204
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": ""},
        {"X-Requested-With": ""},
        {"Origin": "http://localhost:9000"},
        {"Origin": "http://localhost:invalid"},
        {"Origin": "http://localhost:8000.evil.example"},
        {"Origin": "https://evil.example"},
        {"Origin": "http://user@localhost:8000"},
        {"Origin": "http://localhost:8000/path"},
    ],
)
def test_rewritten_origin_does_not_allow_cross_site_or_unmarked_requests(settings, changes):
    with TestClient(
        create_app(tunnel_settings(settings)),
        base_url="http://127.0.0.1:8000",
        headers={
            **FORWARDED,
            "Origin": "http://localhost:8000",
            "Sec-Fetch-Site": "same-origin",
            **changes,
        },
        client=("127.0.0.1", 50000),
    ) as proxy:
        response = proxy.post(
            "/api/auth/register",
            json={
                "username": "should-not-register",
                "password": PASSWORD,
            },
        )
        assert response.status_code == 403
        assert "origin/CSRF" in response.json()["detail"]


@pytest.mark.parametrize(
    "changes",
    [
        {"X-Forwarded-Proto": "http"},
        {"X-Forwarded-Proto": "https,http"},
        {"X-Forwarded-Host": "another-tunnel.devtunnels.ms"},
        {"X-Forwarded-Host": "evil.example"},
    ],
)
def test_private_tunnel_rejects_bad_forwarding_headers(settings, changes):
    with TestClient(
        create_app(tunnel_settings(settings)),
        base_url=ORIGIN,
        headers={**FORWARDED, **changes},
        client=("127.0.0.1", 50000),
    ) as client:
        assert client.get("/health").status_code == 403


def test_private_tunnel_rejects_non_loopback_and_direct_local_http(settings):
    app = create_app(tunnel_settings(settings))
    with TestClient(
        app, base_url=ORIGIN, headers=FORWARDED, client=("192.0.2.10", 50000)
    ) as remote:
        assert remote.get("/health").status_code == 403
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as direct:
        assert direct.get("/health").status_code == 403
        assert direct.get("/api/assessments").status_code == 403


def test_direct_tls_does_not_accept_forwarded_https(settings):
    with TestClient(
        create_app(settings),
        base_url="http://127.0.0.1:8000",
        headers=FORWARDED,
        client=("127.0.0.1", 50000),
    ) as client:
        assert client.get("/health").status_code == 403


def test_private_tunnel_configuration_guards(settings):
    settings = tunnel_settings(settings)
    settings.validate_deployment()
    settings.app_origin = "https://evil.example"
    with pytest.raises(ValueError, match="exact HTTPS"):
        settings.validate_deployment()
    settings.app_origin = ORIGIN
    settings.app_env = "production"
    settings.allow_demo_models = False
    with pytest.raises(ValueError, match="local development"):
        settings.validate_deployment()
