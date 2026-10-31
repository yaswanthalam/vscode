import json

import httpx
import pytest

import app.nvidia
import app.rag


@pytest.fixture(autouse=True)
def isolated_nvidia_cooldowns():
    app.nvidia._cooldowns.clear()
    yield
    app.nvidia._cooldowns.clear()


def test_external_provider_requires_consent_and_sends_only_question_and_sources(
    signed_in, settings, monkeypatch
):
    settings.azure_openai_endpoint = "https://fictional-resource.openai.azure.com"
    settings.azure_openai_api_key = "fictional-test-key"
    settings.azure_openai_deployment = "fictional-deployment"
    captured = []
    real_client = httpx.AsyncClient

    def handle(request):
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Discuss an individualized eating plan [1]."}}],
            },
        )

    monkeypatch.setattr(
        app.rag.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    body = {"question": "Explain kidney nutrition", "disease": "kidney"}
    offline = signed_in.post("/api/chat", json=body).json()
    assert offline["provider"] == "offline"
    assert not captured
    result = signed_in.post("/api/chat", json={**body, "external_consent": True}).json()
    assert result["provider"] == "azure_openai"
    assert len(captured) == 1
    payload = json.loads(captured[0].content)
    assert payload["model"] == "fictional-deployment"
    assert payload["messages"][1] == {"role": "user", "content": body["question"]}
    assert "student" not in captured[0].content.decode()
    assert "features" not in payload
    assert str(captured[0].url).endswith("/openai/v1/chat/completions")


def test_provider_failure_uses_reviewed_offline_sources(signed_in, settings, monkeypatch):
    settings.azure_openai_endpoint = "https://fictional-resource.openai.azure.com"
    settings.azure_openai_api_key = "fictional-test-key"
    settings.azure_openai_deployment = "fictional-deployment"
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        app.rag.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(503)),
            **kwargs,
        ),
    )
    result = signed_in.post(
        "/api/chat",
        json={
            "question": "Explain diabetes eating",
            "disease": "diabetes",
            "external_consent": True,
        },
    ).json()
    assert result["provider"] == "offline"
    assert result["sources"]
    assert "unavailable" in result["notice"]


def test_nvidia_requires_consent_and_takes_priority_without_exposing_key(
    signed_in, settings, monkeypatch
):
    settings.nvidia_api_key = "fictional-nvidia-test-key"
    settings.azure_openai_endpoint = "https://fictional-resource.openai.azure.com"
    settings.azure_openai_api_key = "fictional-azure-test-key"
    settings.azure_openai_deployment = "fictional-azure-deployment"
    real_client = httpx.AsyncClient
    captured = []

    def handle(request):
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Ask your clinician about kidney nutrition [1]."}}
                ],
            },
        )

    monkeypatch.setattr(
        app.rag.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    catalog = signed_in.get("/api/catalog").json()
    assert catalog["external_chat_available"] is True
    assert catalog["external_chat_provider"] == "nvidia"
    assert settings.nvidia_api_key not in json.dumps(catalog)
    question = {"question": "Explain kidney nutrition", "disease": "kidney"}
    assert signed_in.post("/api/chat", json=question).json()["provider"] == "offline"
    assert not captured
    result = signed_in.post("/api/chat", json={**question, "external_consent": True}).json()
    assert result["provider"] == "nvidia"
    assert result["sources"] and "AI-generated" in result["notice"]
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer fictional-nvidia-test-key"
    assert "api-key" not in request.headers
    payload = json.loads(request.content)
    assert payload["model"] == settings.nvidia_model
    assert payload["max_tokens"] == 550
    assert payload["stream"] is False
    assert "max_completion_tokens" not in payload
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["messages"][1] == {"role": "user", "content": question["question"]}
    assert "student" not in request.content.decode()
    assert settings.nvidia_api_key not in json.dumps(result)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "authorization"),
        (403, "authorization"),
        (404, "model unavailable"),
        (429, "rate limit"),
        (503, "unavailable"),
    ],
)
def test_nvidia_errors_fall_back_without_echoing_provider_payload(
    signed_in, settings, monkeypatch, status, expected
):
    settings.nvidia_api_key = "fictional-nvidia-test-key"
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        app.rag.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    status,
                    json={"error": settings.nvidia_api_key},
                )
            ),
            **kwargs,
        ),
    )
    result = signed_in.post(
        "/api/chat",
        json={
            "question": "Explain kidney nutrition",
            "disease": "kidney",
            "external_consent": True,
        },
    ).json()
    assert result["provider"] == "offline"
    assert result["sources"]
    assert expected in result["notice"].lower()
    assert settings.nvidia_api_key not in json.dumps(result)


def test_nvidia_urgency_abstention_and_custom_model_payload(signed_in, settings, monkeypatch):
    settings.nvidia_api_key = "fictional-nvidia-test-key"
    settings.nvidia_model = "fictional/custom-instruct"
    real_client = httpx.AsyncClient
    captured = []

    def handle(request):
        captured.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Reviewed context [1]."}}]}
        )

    monkeypatch.setattr(
        app.rag.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    for question, mode in [("I have chest pain now", "urgent"), ("Build a spaceship", "abstain")]:
        result = signed_in.post(
            "/api/chat",
            json={
                "question": question,
                "external_consent": True,
            },
        ).json()
        assert result["provider"] == "offline" and result["mode"] == mode
    assert not captured
    result = signed_in.post(
        "/api/chat",
        json={
            "question": "Explain diabetes eating",
            "disease": "diabetes",
            "external_consent": True,
        },
    ).json()
    assert result["provider"] == "nvidia"
    payload = json.loads(captured[0].content)
    assert payload["model"] == "fictional/custom-instruct"
    assert "chat_template_kwargs" not in payload


def nvidia_pool(settings, monkeypatch, handler):
    settings.nvidia_api_key = "fictional-nvidia-test-key"
    settings.nvidia_models = "fictional/primary,fictional/backup,fictional/third"
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        app.rag.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


def pool_question(client):
    return client.post(
        "/api/chat",
        json={
            "question": "Explain kidney nutrition",
            "disease": "kidney",
            "external_consent": True,
        },
    ).json()


def successful_completion():
    return httpx.Response(
        200,
        json={
            "choices": [
                {"finish_reason": "stop", "message": {"content": "Reviewed explanation [1]."}}
            ],
        },
    )


def test_model_rate_limit_switches_and_respects_retry_after(signed_in, settings, monkeypatch):
    captured = []

    def handle(request):
        model = json.loads(request.content)["model"]
        captured.append(model)
        if model == "fictional/primary":
            return httpx.Response(
                429,
                headers={"Retry-After": "120"},
                json={
                    "error": {"code": "rate_limit_exceeded", "scope": "model"},
                },
            )
        return successful_completion()

    nvidia_pool(settings, monkeypatch, handle)
    result = pool_question(signed_in)
    assert result["provider"] == "nvidia"
    assert result["model"] == "fictional/backup"
    assert result["attempted_models"] == ["fictional/primary", "fictional/backup"]
    assert result["failover"] is True
    assert "backup" in result["notice"]
    second = pool_question(signed_in)
    assert second["model"] == "fictional/backup"
    assert captured == ["fictional/primary", "fictional/backup", "fictional/backup"]


@pytest.mark.parametrize("failure", ["context", "missing", "server", "timeout", "length", "empty"])
def test_recoverable_model_failure_tries_next_model(signed_in, settings, monkeypatch, failure):
    captured = []

    def handle(request):
        model = json.loads(request.content)["model"]
        captured.append(model)
        if model != "fictional/primary":
            return successful_completion()
        if failure == "timeout":
            raise httpx.ReadTimeout("fictional timeout", request=request)
        if failure == "context":
            return httpx.Response(400, json={"error": {"code": "context_length_exceeded"}})
        if failure == "missing":
            return httpx.Response(404)
        if failure == "server":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if failure == "length" else "stop",
                        "message": {"content": "Truncated answer" if failure == "length" else ""},
                    }
                ]
            },
        )

    nvidia_pool(settings, monkeypatch, handle)
    result = pool_question(signed_in)
    assert result["provider"] == "nvidia" and result["model"] == "fictional/backup"
    assert captured == ["fictional/primary", "fictional/backup"]
    assert "Truncated answer" not in result["answer"]


def test_account_quota_does_not_rotate_models_or_repeat_during_cooldown(
    signed_in, settings, monkeypatch
):
    captured = []

    def handle(request):
        captured.append(json.loads(request.content)["model"])
        return httpx.Response(
            429,
            headers={"Retry-After": "120"},
            json={
                "error": {"code": "insufficient_quota", "scope": "account"},
            },
        )

    nvidia_pool(settings, monkeypatch, handle)
    first = pool_question(signed_in)
    second = pool_question(signed_in)
    assert first["provider"] == second["provider"] == "offline"
    assert first["attempted_models"] == ["fictional/primary"]
    assert second["attempted_models"] == []
    assert "account quota" in first["notice"].lower()
    assert captured == ["fictional/primary"]


@pytest.mark.parametrize("failure", ["filter", "refusal", "policy", "auth"])
def test_model_refusals_and_authorization_errors_do_not_trigger_failover(
    signed_in, settings, monkeypatch, failure
):
    captured = []

    def handle(request):
        captured.append(json.loads(request.content)["model"])
        if failure == "auth":
            return httpx.Response(401)
        if failure == "policy":
            return httpx.Response(400, json={"error": {"code": "content_policy_violation"}})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "content_filter" if failure == "filter" else "stop",
                        "message": {
                            "content": None,
                            "refusal": "Declined" if failure == "refusal" else None,
                        },
                    }
                ]
            },
        )

    nvidia_pool(settings, monkeypatch, handle)
    assert pool_question(signed_in)["provider"] == "offline"
    assert captured == ["fictional/primary"]


def test_pool_exhaustion_is_bounded_deduplicated_and_returns_offline(
    signed_in, settings, monkeypatch
):
    captured = []

    def handle(request):
        captured.append(json.loads(request.content)["model"])
        return httpx.Response(404)

    nvidia_pool(settings, monkeypatch, handle)
    settings.nvidia_models = " fictional/one,fictional/one,fictional/two,fictional/three,fictional/four,fictional/five,fictional/six"
    result = pool_question(signed_in)
    assert result["provider"] == "offline" and result["sources"]
    assert captured == [
        "fictional/one",
        "fictional/two",
        "fictional/three",
        "fictional/four",
        "fictional/five",
    ]
    assert result["attempted_models"] == captured
