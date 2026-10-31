import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

import httpx
import pytest
from cryptography import x509
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app
from app.tls import create_local_certificate
from tests.conftest import HEADERS, PASSWORD


def test_plaintext_scheme_and_origin_rejected(settings):
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(_env_file=None, app_origin="http://127.0.0.1:8000").validate_deployment()
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as client:
        response = client.get("/health")
        assert response.status_code == 403
        assert response.text == "HTTPS is required"


def test_real_tls_and_secure_session(tmp_path, model_dir):
    paths = create_local_certificate(tmp_path / "certs")
    assert create_local_certificate(tmp_path / "certs") == paths
    names = (
        x509.load_pem_x509_certificate(paths["cert"].read_bytes())
        .extensions.get_extension_for_class(x509.SubjectAlternativeName)
        .value
    )
    assert names.get_values_for_type(x509.DNSName) == ["localhost"]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"https://127.0.0.1:{port}"
    env = {
        **os.environ,
        "APP_ENV": "test",
        "TRANSPORT_MODE": "direct_tls",
        "APP_ORIGIN": origin,
        "DATA_DIR": str(tmp_path / "data"),
        "MODEL_DIR": str(model_dir),
        "ALLOW_DEMO_MODELS": "true",
        "TLS_CERT_FILE": str(paths["cert"]),
        "TLS_KEY_FILE": str(paths["key"]),
        "AZURE_OPENAI_ENDPOINT": "",
        "AZURE_OPENAI_API_KEY": "",
        "AZURE_OPENAI_DEPLOYMENT": "",
        "NVIDIA_API_KEY": "",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "app.serve", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        context = ssl.create_default_context(cafile=str(paths["ca"]))
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail(process.stderr.read().decode())
            try:
                with urllib.request.urlopen(
                    origin + "/ready", context=context, timeout=1
                ) as response:
                    assert response.status == 200
                    break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        else:
            pytest.fail("HTTPS test server did not start")
        headers = {**HEADERS, "Origin": origin}
        with httpx.Client(base_url=origin, verify=context, headers=headers) as client:
            response = client.post(
                "/api/auth/register",
                json={
                    "username": "tls-student",
                    "password": PASSWORD,
                },
            )
            assert response.status_code == 201
            assert "secure" in response.headers["set-cookie"].lower()
            assert client.get("/api/auth/me").json()["username"] == "tls-student"
            assert client.post("/api/auth/logout").status_code == 204
            assert client.get("/api/auth/me").status_code == 401
        wrong_ca = create_local_certificate(tmp_path / "unrelated-certs")
        with httpx.Client(
            verify=ssl.create_default_context(cafile=str(wrong_ca["ca"]))
        ) as untrusted:
            with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
                untrusted.get(origin + "/health")
        with socket.create_connection(("127.0.0.1", port), timeout=2) as raw:
            raw.sendall(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
            try:
                data = raw.recv(4096)
            except ConnectionResetError:
                data = b""
            assert b"200 OK" not in data
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_incomplete_certificate_set_is_not_silently_overwritten(tmp_path):
    (tmp_path / "server-key.pem").write_text("existing key placeholder")
    with pytest.raises(ValueError, match="Incomplete"):
        create_local_certificate(tmp_path)
    assert (tmp_path / "server-key.pem").read_text() == "existing key placeholder"
