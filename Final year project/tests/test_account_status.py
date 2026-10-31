from tests.conftest import PASSWORD


def test_gui_account_lookup_finds_exact_normalized_username_only(client):
    path = "/api/auth/account-status"
    assert client.post(path, json={"username": "student"}).json() == {"exists": False}
    registered = client.post(
        "/api/auth/register", json={"username": "student", "password": PASSWORD}
    )
    assert registered.status_code == 201
    assert client.post(path, json={"username": "STUDENT"}).json() == {"exists": True}
    assert client.post(path, json={"username": "student2"}).json() == {"exists": False}
    assert client.post(path, json={"username": "student", "password": PASSWORD}).status_code == 422
    assert client.post(path, json={"username": "' OR 1=1--"}).status_code == 422


def test_account_lookup_keeps_origin_protection_and_rate_limits(client):
    path = "/api/auth/account-status"
    assert (
        client.post(
            path, json={"username": "student"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    for _ in range(10):
        assert client.post(path, json={"username": "student"}).status_code == 200
    assert client.post(path, json={"username": "student"}).status_code == 429


def test_account_existence_is_not_exposed_in_production(client, settings):
    # Exercise the route's deployment gate without creating production demo models.
    settings.app_env = "production"
    assert client.post("/api/auth/account-status", json={"username": "student"}).status_code == 404
