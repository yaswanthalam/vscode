import pytest
from fastapi.testclient import TestClient

from app.catalog import DISEASES
from app.config import Settings
from app.main import create_app
from app.ml import synthetic_data, train

HEADERS = {"X-Requested-With": "HealthLens", "Origin": "https://127.0.0.1:8000"}
PASSWORD = "Fictional-test-password-2026!"


@pytest.fixture(scope="session")
def model_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("models")
    for disease in DISEASES:
        train(disease, synthetic_data(disease, rows=160), directory)
    return directory


@pytest.fixture
def settings(tmp_path, model_dir):
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        model_dir=model_dir,
        app_env="test",
        azure_openai_endpoint="",
        azure_openai_api_key="",
        azure_openai_deployment="",
        nvidia_api_key="",
    )


@pytest.fixture
def client(settings):
    with TestClient(
        create_app(settings), headers=HEADERS, base_url="https://127.0.0.1:8000"
    ) as client:
        yield client


@pytest.fixture
def signed_in(client):
    response = client.post("/api/auth/register", json={"username": "student", "password": PASSWORD})
    assert response.status_code == 201
    return client
