import io

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app.catalog import DISEASES
from app.db import connect
from app.main import create_app
from app.security import digest
from tests.conftest import HEADERS, PASSWORD

FEATURES = {
    "diabetes": {"age": 45, "glucose": 110, "bmi": 26.4, "systolic_bp": 120},
    "heart": {
        "age": 52,
        "systolic_bp": 130,
        "cholesterol": 210,
        "max_heart_rate": 150,
        "exercise_angina": 0,
    },
    "kidney": {
        "age": 48,
        "systolic_bp": 125,
        "creatinine": 1,
        "blood_urea": 28,
        "hemoglobin": 13.2,
    },
}


def test_authenticated_workflow_all_modules(signed_in):
    client = signed_in
    assert client.get("/ready").status_code == 200
    assert set(client.get("/api/catalog").json()["models"]) == set(DISEASES)
    for disease, features in FEATURES.items():
        response = client.post(
            "/api/assessments",
            json={
                "disease": disease,
                "features": features,
                "confirmed": True,
            },
        )
        assert response.status_code == 201, response.text
        item = response.json()
        assert item["result"]["model_source"] == "synthetic"
        assert item["result"]["clinically_validated"] is False
        assert 0 <= item["result"]["model_score"] <= 1
        assert item["guidance"]
        pdf = client.get(f"/api/assessments/{item['id']}/report")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
        assert client.get(f"/api/assessments/{item['id']}").json()["result"]["features"] == features
    assert len(client.get("/api/assessments").json()) == 3


def test_ownership_logout_and_account_deletion(signed_in, settings):
    first = signed_in
    created = first.post(
        "/api/assessments",
        json={
            "disease": "diabetes",
            "features": FEATURES["diabetes"],
            "confirmed": True,
        },
    ).json()
    with TestClient(
        create_app(settings), headers=HEADERS, base_url="https://127.0.0.1:8000"
    ) as other:
        other.post("/api/auth/register", json={"username": "other", "password": PASSWORD})
        path = "/api/assessments/" + created["id"]
        assert other.get(path).status_code == 404
        assert other.get(path + "/report").status_code == 404
        assert other.delete(path).status_code == 404
    assert (
        first.request(
            "DELETE",
            "/api/account",
            json={
                "username": "student",
                "password": "incorrect-password",
            },
        ).status_code
        == 401
    )
    token = first.cookies.get("healthlens_session")
    response = first.request(
        "DELETE",
        "/api/account",
        json={
            "username": "student",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 204
    assert first.get("/api/auth/me").status_code == 401
    with connect(settings) as db:
        assert db.execute("SELECT count(*) FROM assessments").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT count(*) FROM sessions WHERE token_hash=?", (digest(token),)
            ).fetchone()[0]
            == 0
        )


def test_csrf_validation_and_session_revocation(client):
    body = {"username": "testuser", "password": PASSWORD}
    assert (
        client.post(
            "/api/auth/register", json=body, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    with TestClient(client.app, base_url="https://127.0.0.1:8000") as unmarked:
        assert unmarked.post("/api/auth/register", json=body).status_code == 403
    assert client.get("/api/assessments").status_code == 401
    registered = client.post("/api/auth/register", json=body)
    assert "httponly" in registered.headers["set-cookie"].lower()
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json=body).status_code == 200
    assert client.get("/api/auth/me").json()["username"] == "testuser"


def test_input_validation(signed_in):
    base = {"disease": "diabetes", "features": FEATURES["diabetes"], "confirmed": True}
    for body in [
        {**base, "confirmed": False},
        {**base, "features": {**FEATURES["diabetes"], "glucose": -1}},
        {**base, "features": {**FEATURES["diabetes"], "extra": 1}},
        {**base, "features": {**FEATURES["diabetes"], "glucose": True}},
        {**base, "features": {**FEATURES["diabetes"], "glucose": "110"}},
        {**base, "disease": "unknown"},
    ]:
        assert signed_in.post("/api/assessments", json=body).status_code == 422


def test_report_import_and_rejections(signed_in):
    path = "/api/uploads/extract?disease=diabetes"
    text = b"age: 45\nglucose: 110\nbmi: 26.4\nsystolic_bp: 120"
    result = signed_in.post(path, files={"file": ("sample.txt", text)}).json()
    assert result["features"] == FEATURES["diabetes"]
    assert result["missing"] == []
    assert signed_in.post(path, files={"file": ("sample.csv", b"age,glucose\n45,110")}).json()[
        "missing"
    ] == ["bmi", "systolic_bp"]
    for filename, content in [
        ("bad.exe", b"bad"),
        ("duplicate.txt", b"glucose: 100\nglucose: 200"),
        ("bad.pdf", b"not PDF"),
        ("scan.txt", b"No canonical measurements"),
        ("many.csv", b"age,glucose\n45,110\n50,100"),
        ("units.txt", b"glucose: 110 mmol/L"),
    ]:
        assert signed_in.post(path, files={"file": (filename, content)}).status_code == 422
    pdf = io.BytesIO()
    drawing = canvas.Canvas(pdf)
    for index, line in enumerate(text.decode().splitlines()):
        drawing.drawString(40, 750 - 20 * index, line)
    drawing.save()
    extracted = signed_in.post(path, files={"file": ("sample.pdf", pdf.getvalue())})
    assert extracted.status_code == 200
    assert extracted.json()["features"] == FEATURES["diabetes"]
    oversized = signed_in.post(path, files={"file": ("large.txt", b"x" * (2 * 1024 * 1024 + 1))})
    assert oversized.status_code == 413


def test_chat_retrieval_abstention_urgency_and_fallback(signed_in):
    relevant = signed_in.post(
        "/api/chat", json={"question": "What about kidney nutrition?", "disease": "kidney"}
    ).json()
    assert relevant["sources"]
    assert relevant["provider"] == "offline"
    assert all(s["url"].startswith("https://") for s in relevant["sources"])
    assert (
        signed_in.post("/api/chat", json={"question": "Build a spaceship"}).json()["mode"]
        == "abstain"
    )
    urgent = signed_in.post("/api/chat", json={"question": "I have chest pain now"}).json()
    assert urgent["mode"] == "urgent" and "911" in urgent["answer"]
    fallback = signed_in.post(
        "/api/chat",
        json={
            "question": "Explain diabetes eating",
            "disease": "diabetes",
            "external_consent": True,
        },
    ).json()
    assert fallback["provider"] == "offline" and fallback["notice"]


def test_rate_limit(client):
    for _ in range(10):
        response = client.post(
            "/api/auth/login", json={"username": "missing", "password": PASSWORD}
        )
        assert response.status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"username": "missing", "password": PASSWORD}
        ).status_code
        == 429
    )


def test_chunked_request_body_limit(client):
    chunks = (b"x" * (1024 * 1024) for _ in range(3))
    response = client.post(
        "/api/auth/login",
        content=chunks,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
