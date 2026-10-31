import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock, patch

from ai_providers import (
    AgentError, FailoverAI, MAX_RESPONSE, NoRedirect, OpenRouter,
    api_failure, provider_status,
)
from app import ROOT, load_inventory
from gemini_agent import Agent
from storage import Store

SETTINGS = {
    "GEMINI_API_KEY": "dummy-google-secret",
    "ALLOW_GOOGLE_DEVICE_DATA": "true",
    "OPENROUTER_API_KEY": "dummy-router-secret",
    "ALLOW_OPENROUTER_DEVICE_DATA": "true",
    "AI_PROVIDER_ORDER": "gemini,openrouter",
}
PLAN = json.dumps({"steps": [{"device": "R1", "command_id": "version"}]})


def stub(label, effects):
    client = Mock()
    client.label = label
    client.model = "test/model"
    client.last_model = "test/model"
    client.call.side_effect = effects
    return client


class RoutingTests(unittest.TestCase):
    def setUp(self):
        context = patch.dict(os.environ, SETTINGS, clear=True)
        context.start()
        self.addCleanup(context.stop)

    def test_primary_success_never_initializes_fallback(self):
        google = stub("Gemini", [PLAN, "answer"])
        with patch("ai_providers.Gemini", return_value=google), patch("ai_providers.OpenRouter") as fallback:
            ai = FailoverAI()
            self.assertEqual(ai.plan("version", ["R1"])["steps"][0]["command_id"], "version")
            self.assertEqual(ai.answer("version", []), "answer")
            fallback.assert_not_called()
            self.assertEqual([x["provider"] for x in ai.trace], ["gemini", "gemini"])
            ai.close()
            google.close.assert_called_once()

    def test_transient_fallback_is_sticky_for_interpretation(self):
        google = stub("Gemini", [api_failure("Gemini", 503)])
        router = stub("OpenRouter", [PLAN, "fallback answer"])
        with patch("ai_providers.Gemini", return_value=google), patch("ai_providers.OpenRouter", return_value=router):
            ai = FailoverAI()
            ai.plan("version", ["R1"])
            self.assertEqual(ai.answer("version", []), "fallback answer")
            self.assertEqual(google.call.call_count, 1)
            self.assertEqual(router.call.call_count, 2)
            self.assertEqual([x["status"] for x in ai.trace], ["failed", "ok", "ok"])

    def test_answer_can_fallback_without_rerunning_plan(self):
        google = stub("Gemini", [api_failure("Gemini", 503), "recovered answer"])
        router = stub("OpenRouter", [PLAN, api_failure("OpenRouter", 429)])
        with patch("ai_providers.Gemini", return_value=google), patch("ai_providers.OpenRouter", return_value=router):
            ai = FailoverAI()
            ai.plan("version", ["R1"])
            self.assertEqual(ai.answer("version", []), "recovered answer")
            self.assertEqual([x["provider"] for x in ai.trace],
                             ["gemini", "openrouter", "openrouter", "gemini"])
            self.assertEqual([x["stage"] for x in ai.trace],
                             ["planning", "planning", "interpretation", "interpretation"])

    def test_missing_keys_and_consent_are_never_contacted(self):
        for change in [{"GEMINI_API_KEY": ""}, {"ALLOW_GOOGLE_DEVICE_DATA": "false"}]:
            with self.subTest(change=change), patch.dict(os.environ, change):
                router = stub("OpenRouter", [PLAN])
                with patch("ai_providers.Gemini") as google, patch("ai_providers.OpenRouter", return_value=router):
                    FailoverAI().plan("version", ["R1"])
                    google.assert_not_called()
        with patch.dict(os.environ, {"ALLOW_GOOGLE_DEVICE_DATA": "false",
                                    "ALLOW_OPENROUTER_DEVICE_DATA": "false"}):
            with self.assertRaisesRegex(AgentError, "No AI provider"):
                FailoverAI()

    def test_configured_order_and_invalid_order(self):
        with patch.dict(os.environ, {"AI_PROVIDER_ORDER": "openrouter,gemini"}):
            router = stub("OpenRouter", [PLAN])
            with patch("ai_providers.Gemini") as google, patch("ai_providers.OpenRouter", return_value=router):
                FailoverAI().plan("version", ["R1"])
                google.assert_not_called()
        for order in ["", "other", "gemini,gemini", "gemini,"]:
            with patch.dict(os.environ, {"AI_PROVIDER_ORDER": order}), self.assertRaises(AgentError):
                provider_status()

    def test_missing_google_sdk_can_use_openrouter(self):
        router = stub("OpenRouter", [PLAN])
        with patch("ai_providers.Gemini", side_effect=ModuleNotFoundError("test")), patch("ai_providers.OpenRouter", return_value=router):
            ai = FailoverAI()
            ai.plan("version", ["R1"])
            self.assertEqual(ai.preferred, "openrouter")

    def test_refusal_bad_request_and_malformed_plan_do_not_trigger_fallback(self):
        for result in [AgentError("Model declined"), api_failure("Gemini", 400),
                       api_failure("Gemini", 403), "not json"]:
            google = stub("Gemini", [result])
            with self.subTest(result=result), patch("ai_providers.Gemini", return_value=google), patch("ai_providers.OpenRouter") as router:
                with self.assertRaises(AgentError):
                    FailoverAI().plan("version", ["R1"])
                router.assert_not_called()

    def test_all_fail_returns_safe_combined_errors_and_bounded_attempts(self):
        google = stub("Gemini", [api_failure("Gemini", 504)])
        router = stub("OpenRouter", [api_failure("OpenRouter", 429)])
        with patch("ai_providers.Gemini", return_value=google), patch("ai_providers.OpenRouter", return_value=router):
            ai = FailoverAI()
            with self.assertRaisesRegex(AgentError, "All enabled AI providers failed") as caught:
                ai.plan("version", ["R1"])
            self.assertIn("504", str(caught.exception))
            self.assertIn("429", str(caught.exception))
            self.assertEqual(len(ai.trace), 2)
            self.assertNotIn(SETTINGS["OPENROUTER_API_KEY"], str(caught.exception))


class OpenRouterTests(unittest.TestCase):
    def setUp(self):
        context = patch.dict(os.environ, SETTINGS, clear=True)
        context.start()
        self.addCleanup(context.stop)
        self.client = OpenRouter()
        self.response = Mock()
        self.response.__enter__ = Mock(return_value=self.response)
        self.response.__exit__ = Mock(return_value=False)
        self.client.opener.open = Mock(return_value=self.response)

    def respond(self, content, **fields):
        self.response.read.return_value = json.dumps({
            "model": "actual/free-model", "choices": [{
                "message": {"content": content}, "finish_reason": "stop",
            }], **fields,
        }).encode()

    def test_exact_endpoint_schema_privacy_and_provider_contract(self):
        self.respond(PLAN)
        plan = self.client.plan("version", ["R1"])
        self.assertEqual(plan["steps"][0]["device"], "R1")
        request = self.client.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer dummy-router-secret")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "openrouter/free")
        self.assertFalse(body["stream"])
        self.assertEqual(body["provider"], {"require_parameters": True, "data_collection": "deny"})
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(body["response_format"]["json_schema"]["schema"]["properties"]["steps"]["maxItems"], 12)
        self.assertNotIn("dummy-router-secret", request.data.decode())
        self.assertEqual(self.client.last_model, "actual/free-model")

    def test_interpretation_keeps_limitations_and_has_no_tools(self):
        self.respond("Evidence answer")
        self.client.answer("version", [{"id": "test-evidence", "output": "Version 12.4"}])
        request = self.client.opener.open.call_args.args[0]
        body = json.loads(request.data)
        self.assertNotIn("response_format", body)
        self.assertNotIn("tools", body)
        self.assertTrue(json.loads(body["messages"][1]["content"])["limitations"])
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example"))

    def test_api_and_network_failures_do_not_expose_raw_details(self):
        self.client.opener.open.side_effect = urllib.error.HTTPError(
            "https://openrouter.ai", 503, "dummy-router-secret", {}, io.BytesIO(b"secret body"))
        with self.assertRaises(AgentError) as caught:
            self.client.call("system", {})
        self.assertIn("503", str(caught.exception))
        self.assertNotIn("dummy-router-secret", str(caught.exception))
        self.client.opener.open.side_effect = urllib.error.URLError("dummy-router-secret")
        with self.assertRaises(AgentError) as caught:
            self.client.call("system", {})
        self.assertNotIn("dummy-router-secret", str(caught.exception))

    def test_embedded_errors_empty_refusal_malformed_and_oversized_responses(self):
        responses = [
            b"not-json", b"[]", b'{"error":{"code":503,"message":"secret"}}',
            b'{"choices":[]}', b'{"choices":[{"message":{"content":""}}]}',
            b'{"choices":[{"message":{"content":"text","refusal":"blocked"}}]}',
            b'{"choices":[{"message":{"content":"text"},"finish_reason":"length"}]}',
            b'{"choices":[{"message":{"content":"partial"},"finish_reason":"error","error":{"code":503}}]}',
            b'{"choices":[{"message":{"content":"partial"},"finish_reason":"tool_calls"}]}',
            b"x" * (MAX_RESPONSE + 1),
        ]
        for raw in responses:
            self.response.read.return_value = raw
            with self.subTest(raw=raw[:60]), self.assertRaises(AgentError):
                self.client.call("system", {})

    def test_missing_key_and_disabled_sharing_block_initialization(self):
        for change in [{"OPENROUTER_API_KEY": ""}, {"ALLOW_OPENROUTER_DEVICE_DATA": "false"}]:
            with patch.dict(os.environ, change), self.assertRaises(AgentError):
                OpenRouter()


class AgentFailoverTests(unittest.TestCase):
    def setUp(self):
        context = patch.dict(os.environ, SETTINGS, clear=True)
        context.start()
        self.addCleanup(context.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "evidence.sqlite3")
        self.runner = Mock(return_value={"command": "show version", "status": "ok",
                                        "output": "Version 12.4", "truncated": False})
        self.agent = Agent("live", load_inventory(ROOT / "inventory.json"), self.store,
                           Path(self.tmp.name) / "known_hosts", runner=self.runner)

    def test_end_to_end_fallback_preserves_policy_trace_and_redaction(self):
        google = stub("Gemini", [api_failure("Gemini", 503)])
        router = stub("OpenRouter", [PLAN, "Version 12.4 dummy-router-secret"])
        with patch("ai_providers.Gemini", return_value=google), patch("ai_providers.OpenRouter", return_value=router):
            report = self.agent.investigate({"devices": ["R1"], "question": "version"})
        self.runner.assert_called_once()
        self.assertEqual(len(report["ai_trace"]), 3)
        self.assertEqual(report["ai_trace"][1]["provider"], "openrouter")
        self.assertNotIn("dummy-router-secret", json.dumps(report))
        self.assertTrue(any("503" in warning for warning in report["warnings"]))
        with self.store.connect() as db:
            row = db.execute("SELECT payload FROM reports").fetchone()
        self.assertEqual(json.loads(row["payload"]), report)

    def test_unsafe_plan_from_fallback_never_executes(self):
        google = stub("Gemini", [api_failure("Gemini", 503)])
        router = stub("OpenRouter", [json.dumps({"steps": [
            {"device": "R1", "command_id": "version"},
            {"device": "R1", "command_id": "reload"},
        ]})])
        with patch("ai_providers.Gemini", return_value=google), patch("ai_providers.OpenRouter", return_value=router):
            with self.assertRaises(ValueError):
                self.agent.investigate({"devices": ["R1"], "question": "change things"})
        self.runner.assert_not_called()

    def test_partial_device_coverage_never_executes(self):
        router = stub("OpenRouter", [PLAN])
        with patch.dict(os.environ, {"AI_PROVIDER_ORDER": "openrouter"}), patch("ai_providers.OpenRouter", return_value=router):
            with self.assertRaisesRegex(ValueError, "omitted selected devices"):
                self.agent.investigate({"devices": ["R1", "R2", "R3"], "question": "version on every device"})
        self.runner.assert_not_called()

    def test_interpretation_failures_preserve_collected_evidence(self):
        google = stub("Gemini", [PLAN, api_failure("Gemini", 503)])
        router = stub("OpenRouter", [api_failure("OpenRouter", 429)])
        with patch("ai_providers.Gemini", return_value=google), patch("ai_providers.OpenRouter", return_value=router):
            report = self.agent.investigate({"devices": ["R1"], "question": "version"})
        self.runner.assert_called_once()
        self.assertEqual(report["evidence"][0]["output"], "Version 12.4")
        self.assertIn("AI interpretation failed", report["answer"])
        self.assertEqual(len(report["ai_trace"]), 3)

    def test_manual_collection_does_not_initialize_any_provider(self):
        with patch("ai_providers.Gemini") as google, patch("ai_providers.OpenRouter") as router:
            report = self.agent.investigate({"devices": ["R1"], "question": "version", "command_id": "version"})
        google.assert_not_called()
        router.assert_not_called()
        self.assertEqual(report["ai_trace"], [])


if __name__ == "__main__":
    unittest.main()
