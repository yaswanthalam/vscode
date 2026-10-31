import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import ROOT, load_inventory, make_server
from gemini_agent import Agent, AgentError, BusyError, Gemini, demo_plan
from policy import COMMANDS, MAX_OUTPUT, command_for, redact, validate_plan
from ssh_device import DeviceError, receive, run_show
from storage import Store
from syslog_receiver import SyslogReceiver


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "test.sqlite3")
        self.inventory = load_inventory(ROOT / "inventory.json")
        self.agent = Agent("demo", self.inventory, self.store, Path(self.tmp.name) / "known_hosts")


class PolicyTests(unittest.TestCase):
    def test_exact_allowlist_blocks_injection(self):
        for value in ["show version", "version\nreload", "version;reload", "enable",
                      "show running-config", "version | redirect flash:x", "../version", [], None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                command_for(value)
        for cid, (command, _) in COMMANDS.items():
            self.assertEqual(command_for(cid), command)
            self.assertTrue(command.startswith("show "))
            self.assertNotRegex(command, r"[;\n\r|&<>]")

    def test_plan_fail_closed(self):
        for plan in [
            {"steps": [{"device": "R4", "command_id": "version"}]},
            {"steps": [{"device": "R1", "command_id": "enable"}]},
            {"steps": []},
            {"steps": [{"device": "R1", "command_id": "version", "command": "reload"}]},
            {"steps": [{"device": "R1", "command_id": "version"}] * 2},
            {"steps": [{"device": ["R1"], "command_id": "version"}]},
            {"steps": [{"device": "R1", "command_id": "version"}], "extra": True},
        ]:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                validate_plan(plan, ["R1"])

    def test_redaction(self):
        text = ("CPU 3%\nusername admin secret 5 HASH\nsnmp-server community PRIVATE\n"
                "-----BEGIN OPENSSH PRIVATE KEY-----\nVERY_SECRET_BODY\n"
                "-----END OPENSSH PRIVATE KEY-----\nmy_api_key_value\n")
        result = redact(text, ["my_api_key_value"])
        for value in ["HASH", "PRIVATE\n", "VERY_SECRET_BODY", "my_api_key_value"]:
            self.assertNotIn(value, result)
        self.assertIn("CPU 3%", result)
        self.assertNotIn("TRUNCATED_SECRET", redact(
            "-----BEGIN RSA PRIVATE KEY-----\nTRUNCATED_SECRET"))

    def test_demo_budget_includes_every_selected_device(self):
        plan = demo_plan("IOS version downgrade who and when interfaces BGP CPU memory power",
                         ["R1", "R2", "R3"])
        self.assertLessEqual(len(plan["steps"]), 12)
        self.assertEqual({s["device"] for s in plan["steps"]}, {"R1", "R2", "R3"})


class AgentTests(Fixture):
    def test_demo_offline_and_persistent(self):
        def forbidden(*args, **kwargs):
            self.fail("Demo attempted external access")
        self.agent.runner = forbidden
        self.agent.ai_factory = forbidden
        report = self.agent.investigate({"devices": ["R1", "R2", "R3"], "question": "IOS downgrade who?"})
        self.assertIn("UNKNOWN", report["answer"])
        self.assertEqual(len(report["plan"]), 12)
        self.assertTrue(all("SYNTHETIC" in e["output"] for e in report["evidence"]))
        with self.store.connect() as db:
            row = db.execute("SELECT payload FROM reports WHERE run_id=?", (report["run_id"],)).fetchone()
        self.assertEqual(json.loads(row["payload"]), report)
        self.assertEqual(len(self.store.history("demo", ["R1"])), 4)
        self.assertEqual(self.store.history("live", ["R1"]), [])

    def test_invalid_manual_command_never_calls_ssh(self):
        self.agent.mode = "live"
        with patch.object(self.agent, "runner") as runner:
            with self.assertRaises(ValueError):
                self.agent.investigate({"devices": ["R1"], "question": "run", "command_id": "reload"})
            runner.assert_not_called()

    def test_live_manual_without_google(self):
        self.agent.mode = "live"
        self.agent.ai_factory = lambda: self.fail("Manual command attempted Google")
        self.agent.runner = lambda *args: {"command": "show version", "status": "ok",
                                          "output": "Version 15.2", "truncated": False}
        report = self.agent.investigate({"devices": ["R1"], "question": "show version", "command_id": "version"})
        self.assertIn("No data was sent", report["answer"])
        self.assertEqual(report["evidence"][0]["output"], "Version 15.2")

    def test_bad_ai_plan_validated_before_any_ssh(self):
        class BadAI:
            def plan(self, *args):
                return {"steps": [{"device": "R1", "command_id": "version"},
                                  {"device": "R2", "command_id": "reload"}]}
            def close(self):
                pass
        self.agent.mode = "live"
        self.agent.ai_factory = BadAI
        with patch.object(self.agent, "runner") as runner:
            with self.assertRaises(ValueError):
                self.agent.investigate({"devices": ["R1", "R2"], "question": "check"})
            runner.assert_not_called()
        self.assertFalse(self.agent.lock.locked())

    def test_ai_answer_failure_retains_errors_and_evidence(self):
        class FakeAI:
            def plan(self, *args):
                return {"steps": [{"device": "R1", "command_id": "version"}]}
            def answer(self, *args):
                raise AgentError("Gemini failed")
            def close(self):
                pass
        self.agent.mode = "live"
        self.agent.ai_factory = FakeAI
        def fail(*args):
            raise DeviceError("SSH authentication failed")
        self.agent.runner = fail
        report = self.agent.investigate({"devices": ["R1"], "question": "version"})
        self.assertEqual(report["evidence"][0]["status"], "error")
        self.assertIn("failed", report["answer"])
        self.assertIn("Gemini failed", report["warnings"])

    def test_plan_failure_and_busy_are_explicit(self):
        self.agent.lock.acquire()
        try:
            with self.assertRaises(BusyError):
                self.agent.investigate({"devices": ["R1"], "question": "version"})
        finally:
            self.agent.lock.release()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "ALLOW_GOOGLE_DEVICE_DATA": "false"}):
            # Missing SDK is acceptable for the dependency-free demo, so test opt-in
            # only when live dependencies are installed.
            try:
                import google.genai
            except ImportError:
                return
            with self.assertRaises(AgentError):
                Gemini()

    def test_import_scoping_and_redaction(self):
        with patch.dict(os.environ, {"NETWORK_PASSWORD": "fake-secret-value"}):
            item = self.agent.import_log({"device": "R2", "text": "Login fake-secret-value"})
        self.assertNotIn("fake-secret-value", item["output"])
        self.assertEqual(self.store.history("demo", ["R1"], source="import"), [])
        self.assertEqual(len(self.store.history("demo", ["R2"], source="import")), 1)
        with self.assertRaises(ValueError):
            self.agent.import_log({"device": "R1", "text": "x" * (MAX_OUTPUT + 1)})

    def test_syslog_ingestion_only_inventory_source(self):
        receiver = SyslogReceiver("127.0.0.1", 0, self.agent)
        self.addCleanup(receiver.socket.close)
        receiver.ingest(b"not stored", ("10.0.0.99", 999))
        receiver.ingest(b"%SYS-5-RESTART: reboot", ("192.168.32.168", 999))
        rows = self.store.history("live", ["R1"], source="syslog")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "unverified_udp")
        self.assertEqual(self.store.history("demo", ["R1"], source="syslog"), [])

    def test_output_limits_and_secrets(self):
        self.agent.mode = "live"
        self.agent.runner = lambda *args: {
            "command": "show version", "status": "ok", "truncated": False,
            "output": "API_SECRET_VALUE\n" + "x" * MAX_OUTPUT,
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "API_SECRET_VALUE"}):
            report = self.agent.investigate({"devices": ["R1"], "question": "run", "command_id": "version"})
        self.assertNotIn("API_SECRET_VALUE", json.dumps(report))
        self.assertTrue(report["evidence"][0]["truncated"])


class FakeChannel:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []
        self.closed = False

    def recv_ready(self):
        return bool(self.chunks)

    def recv(self, size):
        return self.chunks.pop(0)

    def sendall(self, value):
        self.sent.append(value)


class SSHTests(unittest.TestCase):
    def test_initial_prompt(self):
        self.assertEqual(receive(FakeChannel([b"Welcome\r\nR1#"]))[2], "R1#")

    def test_paging_split_and_prompt(self):
        channel = FakeChannel([b"show version\r\noutput\r\n--Mo", b"re--",
                               b"\b \b" * 8 + b"\r\nremaining\r\nR1#"])
        text, truncated, _ = receive(channel, "R1#")
        self.assertFalse(truncated)
        self.assertIn("remaining", text)
        self.assertEqual(channel.sent, [" "])

    def test_output_cap_timeout_and_closed_channel(self):
        text, truncated, _ = receive(FakeChannel([b"x" * MAX_OUTPUT]), "R1#")
        self.assertTrue(truncated)
        self.assertEqual(len(text), MAX_OUTPUT)
        with self.assertRaises(DeviceError):
            receive(FakeChannel([]), timeout=0)
        channel = FakeChannel([])
        channel.closed = True
        with self.assertRaises(DeviceError):
            receive(channel)

    def test_boundary_validation_before_dependency_or_connect(self):
        with self.assertRaises(ValueError):
            run_show("R1", {"host": "127.0.0.1", "port": 22}, "enable", "missing")

    def test_real_local_ssh_sends_only_show_and_pagination(self):
        try:
            import paramiko
        except ImportError:
            self.skipTest("Install live requirements for SSH integration test")
        key = paramiko.RSAKey.generate(2048)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(8)
        port = listener.getsockname()[1]
        sent = []
        failures = []
        ready = threading.Event()

        class FakeIOS(paramiko.ServerInterface):
            def check_auth_password(self, username, password):
                return (paramiko.AUTH_SUCCESSFUL if (username, password) == ("readonly", "dummy-local")
                        else paramiko.AUTH_FAILED)
            def get_allowed_auths(self, username):
                return "password"
            def check_channel_request(self, kind, chanid):
                return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
            def check_channel_pty_request(self, *args):
                return True
            def check_channel_shell_request(self, channel):
                ready.set()
                return True

        def serve():
            try:
                with listener:
                    sock, _ = listener.accept()
                    with paramiko.Transport(sock) as transport:
                        transport.add_server_key(key)
                        transport.start_server(server=FakeIOS())
                        channel = transport.accept(8)
                        if channel is None or not ready.wait(8):
                            raise AssertionError("SSH shell not opened")
                        channel.settimeout(8)
                        channel.sendall(b"R1#")
                        line = b""
                        while not line.endswith(b"\n"):
                            part = channel.recv(1024)
                            if not part:
                                raise AssertionError("SSH command missing")
                            line += part
                        sent.append(line.decode())
                        channel.sendall(b"show version\r\nCisco IOS Version 15.2\r\n--More--")
                        sent.append(channel.recv(1).decode())
                        channel.sendall(b"\r\nUptime is 2 days\r\nR1#")
                        while channel.recv(1024):
                            pass
            except Exception as exc:
                failures.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "known_hosts"
            keys = paramiko.HostKeys()
            keys.add(f"[127.0.0.1]:{port}", key.get_name(), key)
            keys.save(str(path))
            with patch.dict(os.environ, {"R1_USERNAME": "readonly", "R1_PASSWORD": "dummy-local",
                                        "R1_KEY_FILE": "", "NETWORK_KEY_FILE": ""}):
                result = run_show("R1", {"host": "127.0.0.1", "port": port}, "version", path)
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(sent, ["show version\n", " "])
        self.assertEqual(result["status"], "ok")
        self.assertIn("Version 15.2", result["output"])
        self.assertNotIn("R1#", result["output"])


class GeminiSDKTests(unittest.TestCase):
    def test_sdk_schema_plan_and_answer_without_cloud(self):
        try:
            from google.genai import types
        except ImportError:
            self.skipTest("Install live requirements for SDK contract test")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy-test-key",
                                    "ALLOW_GOOGLE_DEVICE_DATA": "true"}):
            ai = Gemini()
        self.addCleanup(ai.close)
        response = types.GenerateContentResponse(candidates=[types.Candidate(
            content=types.Content(parts=[types.Part(text=json.dumps({
                "steps": [{"device": "R1", "command_id": "version"}]
            }))]))])
        with patch.object(ai.client.models, "generate_content", return_value=response) as generate:
            plan = ai.plan("What IOS?", ["R1"])
            self.assertEqual(validate_plan(plan, ["R1"])[0]["command_id"], "version")
            config = generate.call_args.kwargs["config"]
            self.assertEqual(config.response_mime_type, "application/json")
            self.assertEqual(config.response_json_schema["properties"]["steps"]["maxItems"], 12)
            self.assertNotIn("dummy-test-key", generate.call_args.kwargs["contents"])
        with patch.object(ai.client.models, "generate_content",
                          return_value=types.GenerateContentResponse()):
            with self.assertRaises(AgentError):
                ai.answer("question", [])
        incomplete = types.GenerateContentResponse(candidates=[types.Candidate(
            content=types.Content(parts=[types.Part(text="partial answer")]),
            finish_reason=types.FinishReason.MAX_TOKENS)])
        with patch.object(ai.client.models, "generate_content", return_value=incomplete):
            with self.assertRaisesRegex(AgentError, "did not complete"):
                ai.answer("question", [])


class HTTPTests(Fixture):
    def setUp(self):
        super().setUp()
        self.server, self.token = make_server(self.agent, 0, token="test-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def auth(self):
        return {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}

    def test_static_and_auth(self):
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Network Lens", body)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("GET", "/api/status")[0], 401)
        self.assertEqual(self.request("GET", "/api/status", headers=self.auth())[0], 200)
        self.assertEqual(self.request("GET", "/../.env", headers=self.auth())[0], 404)

    def test_host_origin_and_payload_validation(self):
        headers = self.auth()
        headers["Origin"] = "https://evil.example"
        self.assertEqual(self.request("POST", "/api/investigate", "{}", headers)[0], 403)
        headers = self.auth()
        headers["Host"] = "evil.example"
        self.assertEqual(self.request("GET", "/api/status", headers=headers)[0], 403)
        for payload in ["{bad", "[]", '{"devices":["NOT_REGISTERED"],"question":"check"}']:
            self.assertEqual(self.request("POST", "/api/investigate", payload, self.auth())[0], 400)
        self.assertEqual(self.request("POST", "/api/import", "x" * 110001, self.auth())[0], 413)

    def test_http_end_to_end_and_xss_remains_text(self):
        log = json.dumps({"device": "R1", "text": "<script>alert(1)</script>"})
        self.assertEqual(self.request("POST", "/api/import", log, self.auth())[0], 200)
        request = json.dumps({"devices": ["R1"], "question": "interfaces"})
        status, body, _ = self.request("POST", "/api/investigate", request, self.auth())
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["mode"], "demo")
        self.assertTrue(any("alert" in e["output"] for e in data["evidence"]))
        javascript = (ROOT / "static" / "app.js").read_text()
        self.assertNotIn("innerHTML", javascript)
        self.assertNotIn("localStorage", javascript)


class HTTPSTests(Fixture):
    def setUp(self):
        super().setUp()
        try:
            from local_tls import local_context
            context, self.cert_path, self.fingerprint = local_context(Path(self.tmp.name) / "tls")
        except ImportError:
            self.skipTest("Install requirements for HTTPS tests")
        self.server, self.token = make_server(self.agent, 0, token="test-token", tls_context=context)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, *, origin=None, body=None, trust=True, token="test-token"):
        context = ssl.create_default_context(cafile=str(self.cert_path)) if trust else ssl.create_default_context()
        connection = http.client.HTTPSConnection("127.0.0.1", self.server.server_port,
                                                  timeout=5, context=context)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        try:
            connection.request("GET" if body is None else "POST", path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_https_verified_certificate_and_authenticated_investigation(self):
        origin = f"https://127.0.0.1:{self.server.server_port}"
        self.assertIn(b"Network Lens", self.request("/")[1])
        self.assertEqual(self.request("/api/status", origin=origin)[0], 200)
        status, body = self.request("/api/investigate", origin=origin, body=json.dumps({
            "devices": ["R1"], "question": "show version", "command_id": "version",
        }))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "demo")

    def test_https_rejects_wrong_origin_and_token(self):
        self.assertEqual(self.request("/api/status", origin=f"http://127.0.0.1:{self.server.server_port}")[0], 403)
        self.assertEqual(self.request("/api/status", origin="https://evil.example")[0], 403)
        self.assertEqual(self.request("/api/status", token="wrong")[0], 401)

    def test_certificate_is_not_implicitly_trusted_and_is_reused(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.request("/", trust=False)
        from local_tls import local_context
        _, _, fingerprint = local_context(self.cert_path.parent)
        self.assertEqual(fingerprint, self.fingerprint)
        self.cert_path.unlink()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            local_context(self.cert_path.parent)


if __name__ == "__main__":
    unittest.main()
