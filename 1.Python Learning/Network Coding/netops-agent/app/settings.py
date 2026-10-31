"""Central settings, read from environment variables (see .env.example)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


MOCK = _bool("NETOPS_MOCK", True)

AOAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AOAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AOAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")
AOAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")

KUSTO_CLUSTER = os.getenv("KUSTO_CLUSTER", "")
KUSTO_DATABASE = os.getenv("KUSTO_DATABASE", "")

KEYVAULT_URL = os.getenv("KEYVAULT_URL", "")
KEYVAULT_USERNAME_SECRET = os.getenv("KEYVAULT_USERNAME_SECRET", "netops-ro-username")
KEYVAULT_PASSWORD_SECRET = os.getenv("KEYVAULT_PASSWORD_SECRET", "netops-ro-password")

DEVICE_COMMAND_TIMEOUT = int(os.getenv("DEVICE_COMMAND_TIMEOUT", "60"))
MAX_PARALLEL_DEVICE_SESSIONS = int(os.getenv("MAX_PARALLEL_DEVICE_SESSIONS", "4"))
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "6"))
ALLOWED_USERS = {u.strip().lower() for u in os.getenv("ALLOWED_USERS", "").split(",") if u.strip()}
AUDIT_LOG = Path(os.getenv("AUDIT_LOG", str(BASE_DIR / "audit.jsonl")))
