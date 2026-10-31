"""Kusto access through approved, parameterised templates only."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import yaml

from . import mock_data, settings


class KustoError(Exception):
    pass


@lru_cache(maxsize=1)
def templates() -> dict:
    with open(settings.CONFIG_DIR / "kusto_templates.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["templates"]


def describe_templates() -> list[dict]:
    return [
        {"name": n, "description": t["description"], "params": list(t["params"].keys())}
        for n, t in templates().items()
    ]


def _coerce(name: str, spec: dict, value):
    if value is None or value == "":
        if "default" in spec:
            return spec["default"]
        raise KustoError(f"Missing parameter '{name}'.")
    kind = spec["type"]
    if kind == "int":
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise KustoError(f"Parameter '{name}' must be an integer.")
        if not spec.get("min", v) <= v <= spec.get("max", v):
            raise KustoError(f"Parameter '{name}' must be between {spec.get('min')} and {spec.get('max')}.")
        return v
    if kind == "datetime":
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise KustoError(f"Parameter '{name}' must be an ISO-8601 datetime.")
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    v = str(value)
    if "pattern" in spec and not re.fullmatch(spec["pattern"], v):
        raise KustoError(f"Parameter '{name}' has invalid characters or length.")
    return v


def bind_params(template_name: str, params: dict) -> tuple[str, dict]:
    t = templates().get(template_name)
    if not t:
        raise KustoError(f"Unknown template '{template_name}'. Allowed: {', '.join(templates())}")
    extra = set(params or {}) - set(t["params"])
    if extra:
        raise KustoError(f"Unknown parameter(s): {', '.join(sorted(extra))}")
    bound = {n: _coerce(n, spec, (params or {}).get(n)) for n, spec in t["params"].items()}
    return t["query"], bound


def run_template(template_name: str, params: dict) -> dict:
    query, bound = bind_params(template_name, params)
    if settings.MOCK:
        rows = mock_data.kusto(template_name, bound)
    else:
        rows = _execute(query, bound)
    latest = max((str(r.get("Timestamp") or r.get("LastSeen") or "") for r in rows), default=None)
    return {
        "source": "kusto",
        "template": template_name,
        "params": {k: str(v) for k, v in bound.items()},
        "row_count": len(rows),
        "latest_timestamp": latest or None,
        "rows": rows[:200],
    }


@lru_cache(maxsize=1)
def _client():
    from azure.identity import DefaultAzureCredential
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

    if not settings.KUSTO_CLUSTER or not settings.KUSTO_DATABASE:
        raise KustoError("KUSTO_CLUSTER and KUSTO_DATABASE must be set.")
    cred = DefaultAzureCredential()
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(settings.KUSTO_CLUSTER, cred)
    return KustoClient(kcsb)


def _execute(query: str, bound: dict) -> list[dict]:
    from azure.kusto.data import ClientRequestProperties

    props = ClientRequestProperties()
    props.set_option("servertimeout", timedelta(seconds=60))
    for name, value in bound.items():
        # Kusto parameter values are sent as literals of the declared type.
        if isinstance(value, datetime):
            props.set_parameter(name, f"datetime({value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')})")
        else:
            props.set_parameter(name, str(value))
    # Read-only by construction: a 'declare query_parameters' query is a query,
    # not a control command, and the identity should only have Viewer rights.
    resp = _client().execute(settings.KUSTO_DATABASE, query, props)
    table = resp.primary_results[0]
    cols = [c.column_name for c in table.columns]
    return [{c: (v.isoformat() if isinstance(v, datetime) else v) for c, v in zip(cols, row)} for row in table]
