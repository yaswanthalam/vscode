"""Read-only device access. Every command passes guardrails first."""
from __future__ import annotations

import threading
import time
from functools import lru_cache

import yaml

from . import guardrails, mock_data, settings


class DeviceError(Exception):
    pass


_global_slots = threading.BoundedSemaphore(settings.MAX_PARALLEL_DEVICE_SESSIONS)
_device_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@lru_cache(maxsize=1)
def inventory() -> dict[str, dict]:
    with open(settings.CONFIG_DIR / "inventory.yaml", encoding="utf-8") as f:
        return {d["name"]: d for d in yaml.safe_load(f)["devices"]}


def list_devices() -> list[dict]:
    return [{"name": d["name"], "platform": d["platform"]} for d in inventory().values()]


@lru_cache(maxsize=1)
def _credentials() -> tuple[str, str]:
    import os

    if settings.KEYVAULT_URL:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        kv = SecretClient(settings.KEYVAULT_URL, DefaultAzureCredential())
        return (
            kv.get_secret(settings.KEYVAULT_USERNAME_SECRET).value,
            kv.get_secret(settings.KEYVAULT_PASSWORD_SECRET).value,
        )
    user, pwd = os.getenv("DEVICE_USERNAME"), os.getenv("DEVICE_PASSWORD")
    if not user or not pwd:
        raise DeviceError("No device credentials configured (set KEYVAULT_URL, or DEVICE_USERNAME/PASSWORD for lab).")
    return user, pwd


def _lock_for(device: str) -> threading.Lock:
    with _locks_guard:
        return _device_locks.setdefault(device, threading.Lock())


def run_show(device: str, command: str) -> dict:
    dev = inventory().get(device)
    if not dev:
        raise DeviceError(f"Device '{device}' is not in the approved inventory.")

    verdict = guardrails.validate_command(command)
    if not verdict.allowed:
        raise DeviceError("Blocked by guardrails: " + " ".join(verdict.reasons))
    cmd = verdict.command

    # One session per device at a time, and a global cap, so the tool can
    # never hammer the control plane.
    if not _global_slots.acquire(timeout=30):
        raise DeviceError("Too many device sessions in progress; try again shortly.")
    try:
        with _lock_for(device):
            started = time.time()
            if settings.MOCK:
                output = mock_data.device(device, dev["platform"], cmd)
            else:
                output = _ssh(dev, cmd)
            elapsed = round(time.time() - started, 2)
    finally:
        _global_slots.release()

    return {
        "source": "device",
        "device": device,
        "platform": dev["platform"],
        "command": cmd,
        "elapsed_s": elapsed,
        "output": guardrails.redact_output(output)[:20000],
    }


def _ssh(dev: dict, cmd: str) -> str:
    from netmiko import ConnectHandler

    user, pwd = _credentials()
    params = {
        "device_type": dev["platform"],
        "host": dev["host"],
        "username": user,
        "password": pwd,
        "conn_timeout": 15,
        "auth_timeout": 20,
        "fast_cli": False,
    }
    try:
        with ConnectHandler(**params) as conn:
            # No enable / config mode is ever entered.
            return conn.send_command(cmd, read_timeout=settings.DEVICE_COMMAND_TIMEOUT)
    except Exception as exc:  # never echo credentials back
        raise DeviceError(f"SSH to {dev['name']} failed: {type(exc).__name__}") from None
