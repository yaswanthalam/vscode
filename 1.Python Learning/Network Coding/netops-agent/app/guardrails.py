"""Layer 1: deterministic command validation.

This is the HARD gate. A command that fails here is never sent to a device
and never even shown to the AI as runnable. The AI review (ai.py) can only
make a decision stricter, never looser.

Layer 0, outside this code, is the device itself: the service account must be
a read-only TACACS/RADIUS role, so the device refuses anything else anyway.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from .settings import CONFIG_DIR

# Characters that could chain, substitute or redirect commands.
_FORBIDDEN_CHARS = re.compile(r"[;&`$<>\\\r\n\t\x00-\x1f\"']")

# Lines that may carry secrets in show output (running-config etc.).
_SECRET_LINE = re.compile(
    r"(?im)^(\s*.*?\b(secret|password|passwd|key|key-string|community|pre-shared-key|encrypted-password|authentication-key)\b\s+).+$"
)


@dataclass
class Verdict:
    allowed: bool
    command: str  # normalised command
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "command": self.command, "reasons": self.reasons}


@lru_cache(maxsize=1)
def _policy() -> dict:
    with open(CONFIG_DIR / "allowed_commands.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return {
        "allow": [re.compile(p, re.I) for p in raw["common"]],
        "pipes": [re.compile(p, re.I) for p in raw["allowed_pipes"]],
        "max_pipes": int(raw.get("max_pipes", 2)),
        "max_length": int(raw.get("max_length", 200)),
        "denied": [re.compile(rf"(?<![\w-]){re.escape(w)}(?![\w-])", re.I) for w in raw["denied_words"]],
    }


def normalise(command: str) -> str:
    cmd = " ".join((command or "").strip().split())
    # Expand the common abbreviation so the allowlist only needs 'show'.
    cmd = re.sub(r"^(sh|sho)(?=\s)", "show", cmd, flags=re.I)
    return cmd


def validate_command(command: str) -> Verdict:
    p = _policy()
    cmd = normalise(command)
    reasons: list[str] = []

    if not cmd:
        return Verdict(False, cmd, ["Empty command."])
    if len(cmd) > p["max_length"]:
        reasons.append(f"Command is longer than {p['max_length']} characters.")
    if _FORBIDDEN_CHARS.search(command or ""):
        reasons.append("Contains a forbidden character (; & ` $ < > \\ quotes or control characters).")
    if not re.match(r"^show\s", cmd, re.I):
        reasons.append("Only 'show' commands are permitted.")
    parts = [s.strip() for s in cmd.split("|")]
    base, pipes = parts[0], parts[1:]

    # Blocked words apply to the command and each pipe keyword. The text after
    # 'include'/'match' is only a search string (restricted to plain characters
    # by allowed_pipes), so 'show logging | include reload' stays allowed.
    checked = " ".join([base] + [p_.split(" ", 1)[0] for p_ in pipes])
    for rx in p["denied"]:
        m = rx.search(checked)
        if m:
            reasons.append(f"Contains the blocked word '{m.group(0)}'.")
    if len(pipes) > p["max_pipes"]:
        reasons.append(f"More than {p['max_pipes']} pipe modifiers.")
    for pipe in pipes:
        if not any(rx.match(pipe) for rx in p["pipes"]):
            reasons.append(f"Pipe modifier '| {pipe}' is not on the allowed list.")
    if not any(rx.match(base) for rx in p["allow"]):
        reasons.append(f"'{base}' is not on the approved command list.")

    return Verdict(not reasons, cmd, reasons)


def redact_output(text: str) -> str:
    """Mask secrets that some show commands print (hashed or not)."""
    return _SECRET_LINE.sub(lambda m: f"{m.group(1)}<redacted>", text or "")
