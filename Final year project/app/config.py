from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_env: str = "development"
    app_origin: str = "https://127.0.0.1:8000"
    transport_mode: str = "direct_tls"
    tls_cert_file: Path = ROOT / ".certs" / "server.pem"
    tls_key_file: Path = ROOT / ".certs" / "server-key.pem"
    data_dir: Path = ROOT / "data"
    model_dir: Path = ROOT / "models"
    allow_demo_models: bool = True
    session_hours: int = 8
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    nvidia_api_key: str = ""
    nvidia_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    nvidia_models: str = ""

    @property
    def nvidia_model_candidates(self):
        models = (
            self.nvidia_models.split(",")
            if self.nvidia_models.strip()
            else [
                self.nvidia_model,
                "nvidia/nemotron-3.5-lightning-30b-a3b",
                "nvidia/nemotron-3.5-super-vl-120b-a12b",
            ]
        )
        return list(dict.fromkeys(model.strip() for model in models if model.strip()))[:5]

    @property
    def external_chat_provider(self):
        if self.nvidia_api_key.strip():
            return "nvidia" if self.nvidia_model_candidates else None
        if all(
            [
                self.azure_openai_endpoint,
                self.azure_openai_api_key,
                self.azure_openai_deployment,
            ]
        ):
            return "azure_openai"
        return None

    @property
    def production(self):
        return self.app_env == "production"

    def validate_deployment(self):
        if self.app_env not in {"development", "production", "test"}:
            raise ValueError("APP_ENV must be development, test, or production")
        origin = urlparse(self.app_origin)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
        ):
            raise ValueError("APP_ORIGIN must be an HTTPS origin without a path")
        if self.production and self.allow_demo_models:
            raise ValueError("Production requires ALLOW_DEMO_MODELS=false")
        if self.transport_mode not in {"direct_tls", "private_tunnel"}:
            raise ValueError("Invalid TRANSPORT_MODE")
        if self.transport_mode == "private_tunnel":
            if self.production:
                raise ValueError("Private tunnels are for local development only")
            if not origin.hostname.endswith(".devtunnels.ms") or origin.port not in {None, 443}:
                raise ValueError(
                    "Private tunnel mode requires the exact HTTPS devtunnels.ms address"
                )
        if not 1 <= self.session_hours <= 24:
            raise ValueError("SESSION_HOURS must be between 1 and 24")
        if self.azure_openai_endpoint:
            endpoint = urlparse(self.azure_openai_endpoint)
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or not endpoint.hostname.endswith(".openai.azure.com")
                or endpoint.username
                or endpoint.password
                or endpoint.port not in {None, 443}
                or endpoint.path not in {"", "/"}
                or endpoint.query
                or endpoint.fragment
            ):
                raise ValueError("Use an HTTPS Azure OpenAI resource origin")
