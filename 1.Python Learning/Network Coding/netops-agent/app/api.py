"""Framework-independent request handlers (main.py wires them to HTTP)."""
from __future__ import annotations

from . import agent, ai, audit, device_tool, guardrails, settings


class Forbidden(Exception):
    pass


class BadRequest(Exception):
    pass


def authorise(user: str | None) -> str:
    user = (user or "").strip().lower()
    if not user:
        if settings.MOCK:
            return "demo-user"
        raise Forbidden("No signed-in user. Put this app behind Entra ID sign-in.")
    if settings.ALLOWED_USERS and user not in settings.ALLOWED_USERS:
        raise Forbidden(f"{user} is not allowed to use this tool.")
    return user


def info() -> dict:
    return {"mock": settings.MOCK, "devices": device_tool.list_devices()}


def validate(user: str, device: str, command: str, purpose: str = "") -> dict:
    dev = device_tool.inventory().get(device)
    if not dev:
        raise BadRequest(f"Unknown device '{device}'.")
    rules = guardrails.validate_command(command)
    if rules.allowed:
        review = ai.review_command(rules.command, dev["platform"], purpose)
    else:
        review = {"verdict": "skipped", "reason": "Blocked by rules; not sent to AI."}
    decision = "deny"
    if rules.allowed and review.get("verdict") in {"allow", "warn"}:
        decision = review["verdict"]
    result = {"device": device, "platform": dev["platform"], "command": rules.command,
              "rules": rules.to_dict(), "ai": review, "decision": decision}
    audit.record(user, "validate", device=device, command=rules.command, decision=decision,
                 rule_reasons=rules.reasons, ai_verdict=review.get("verdict"))
    return result


def run(user: str, device: str, command: str, purpose: str = "", acknowledge_warning: bool = False) -> dict:
    # Re-validate server-side; never trust a verdict the browser sends back.
    v = validate(user, device, command, purpose)
    if v["decision"] == "deny":
        return {"validation": v, "executed": False}
    if v["decision"] == "warn" and not acknowledge_warning:
        return {"validation": v, "executed": False, "needs_acknowledgement": True}
    try:
        out = device_tool.run_show(device, v["command"])
        audit.record(user, "run", device=device, command=v["command"], ok=True, elapsed_s=out["elapsed_s"])
        return {"validation": v, "executed": True, "result": out}
    except device_tool.DeviceError as exc:
        audit.record(user, "run", device=device, command=v["command"], ok=False, error=str(exc))
        return {"validation": v, "executed": False, "error": str(exc)}


def ask(user: str, question: str) -> dict:
    question = (question or "").strip()
    if not question:
        raise BadRequest("Question is empty.")
    if len(question) > 2000:
        raise BadRequest("Question is too long (2000 characters max).")
    return agent.ask(question, user)


def audit_tail(limit: int = 100) -> list[dict]:
    return audit.tail(min(max(limit, 1), 500))
