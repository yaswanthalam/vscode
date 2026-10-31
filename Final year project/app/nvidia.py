import asyncio
import hashlib
import math
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
_cooldowns = {}
_NON_REASONING_MODELS = {
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
}


class NvidiaUnavailable(Exception):
    def __init__(self, reason, attempted_models):
        super().__init__(reason)
        self.reason = reason
        self.attempted_models = list(attempted_models)


def _retry_after(response):
    value = response.headers.get("retry-after", "")
    try:
        seconds = float(value)
        return max(1, seconds) if math.isfinite(seconds) else 60
    except ValueError:
        try:
            until = parsedate_to_datetime(value)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            return max(1, (until - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 60


def _error_reason(response):
    # Inspect bounded error metadata only; never expose the provider payload or credentials.
    try:
        payload = response.json()
        error = payload.get("error", payload)
        if isinstance(error, dict):
            code = str(error.get("code", error.get("type", ""))).lower()[:200]
            message = str(error.get("message", error.get("detail", ""))).lower()[:2000]
            scope = str(error.get("scope", payload.get("scope", ""))).lower()
        else:
            code, scope, message = "", "", str(error).lower()[:2000]
    except (ValueError, AttributeError, TypeError):
        code, scope, message = "", "", ""
    if response.status_code in {401, 403}:
        return "authorization"
    if code in {"content_filter", "content_policy_violation", "safety_violation"}:
        return "filtered"
    if response.status_code == 429:
        if (
            scope in {"account", "organization", "global"}
            or code
            in {
                "insufficient_quota",
                "account_quota_exceeded",
                "credits_exhausted",
                "billing_hard_limit_reached",
            }
            or any(word in message for word in ("account", "organization"))
            and any(word in message for word in ("quota", "rate limit", "credits"))
        ):
            return "account_quota"
        return "model_rate_limit"
    if response.status_code == 404:
        return "model_unavailable"
    if response.status_code in {400, 413, 422} and (
        code in {"context_length_exceeded", "token_limit_exceeded", "max_tokens_exceeded"}
        or any(
            term in message
            for term in (
                "context length",
                "context window",
                "token limit",
                "too many tokens",
                "maximum tokens",
            )
        )
    ):
        return "token_limit"
    if response.status_code in {500, 502, 503, 504}:
        return "unavailable"
    return "request_rejected"


async def complete(messages, settings):
    key = settings.nvidia_api_key.strip()
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    now = time.monotonic()
    for identity, until in list(_cooldowns.items()):
        if until <= now:
            _cooldowns.pop(identity, None)
    if _cooldowns.get((fingerprint, "*"), 0) > now:
        raise NvidiaUnavailable("account_quota", [])
    attempted = []
    reason = "model_rate_limit"
    deadline = now + 90
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        for model in settings.nvidia_model_candidates:
            if _cooldowns.get((fingerprint, model), 0) > time.monotonic():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reason = "unavailable"
                break
            attempted.append(model)
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": 550,
                "temperature": 0.2,
                "stream": False,
            }
            if model in _NON_REASONING_MODELS:
                payload["chat_template_kwargs"] = {"enable_thinking": False}
            try:
                async with asyncio.timeout(min(30, remaining)):
                    response = await client.post(
                        ENDPOINT,
                        headers={"Authorization": "Bearer " + key},
                        json=payload,
                    )
                if response.is_error:
                    reason = _error_reason(response)
                    if reason in {"account_quota", "model_rate_limit"}:
                        identity = (fingerprint, "*" if reason == "account_quota" else model)
                        _cooldowns[identity] = time.monotonic() + _retry_after(response)
                    if reason in {"authorization", "account_quota", "filtered", "request_rejected"}:
                        raise NvidiaUnavailable(reason, attempted)
                    continue
                response.raise_for_status()
                choice = response.json()["choices"][0]
                if choice.get("finish_reason") == "content_filter" or choice["message"].get(
                    "refusal"
                ):
                    raise NvidiaUnavailable("filtered", attempted)
                if choice.get("finish_reason") == "length":
                    reason = "token_limit"
                    continue
                generated = choice["message"]["content"]
                if not isinstance(generated, str) or not generated.strip():
                    raise ValueError("Empty response")
                return {
                    "text": generated[:7000],
                    "model": model,
                    "attempted_models": attempted,
                    "failover": model != settings.nvidia_model_candidates[0],
                }
            except (httpx.HTTPError, TimeoutError, KeyError, IndexError, ValueError, TypeError):
                reason = "unavailable"
    raise NvidiaUnavailable(reason, attempted)
