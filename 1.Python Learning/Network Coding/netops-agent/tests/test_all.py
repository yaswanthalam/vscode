"""Run with:  python -m unittest -v   (or pytest)"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ["NETOPS_MOCK"] = "true"
os.environ["AUDIT_LOG"] = str(Path(tempfile.mkdtemp()) / "audit.jsonl")

from app import agent, api, device_tool, guardrails, kusto_tool  # noqa: E402


class GuardrailTests(unittest.TestCase):
    ALLOWED = [
        "show version", "sh version", "SHOW VERSION", "show lacp summary", "show isis neighbors",
        "show isis adjacency", "show logging | include install", "show logging | include LACP | count",
        "show install log", "show system commit", "show configuration commit list",
        "show interfaces Ethernet1/1", "show running-config", "show bgp summary",
        "show logging | include reload", "show logging | include configure",
    ]
    BLOCKED = [
        "reload", "configure terminal", "conf t", "show version; reload", "show version && reload",
        "show logging | redirect harddisk:/x", "show logging | tee flash:x", "show logging | append x",
        "show version | include x | include y | include z", "run bash", "bash ls", "start shell",
        "show tech-support", "delete flash:x", "copy run start", "write memory", "clear counters",
        "debug ip packet", "show version `id`", "show version $(id)", "show version\nreload",
        "show ip route > file", "request system reboot", "show something-unknown",
        "show logging | include x; reload", "", "   ", "show logging | reload",
        "show logging | include `reload`", "show logging | file x", "show version | redirect x",
    ]

    def test_allowed(self):
        for c in self.ALLOWED:
            with self.subTest(c=c):
                v = guardrails.validate_command(c)
                self.assertTrue(v.allowed, f"{c!r} should be allowed: {v.reasons}")

    def test_blocked(self):
        for c in self.BLOCKED:
            with self.subTest(c=c):
                self.assertFalse(guardrails.validate_command(c).allowed, f"{c!r} should be blocked")

    def test_redaction(self):
        out = guardrails.redact_output("username a\n secret 10 $6$abc\nsnmp-server community PUBLIC RO\nhostname r1")
        self.assertNotIn("$6$abc", out)
        self.assertNotIn("PUBLIC", out)
        self.assertIn("hostname r1", out)


class KustoTests(unittest.TestCase):
    def test_injection_rejected(self):
        with self.assertRaises(kusto_tool.KustoError):
            kusto_tool.bind_params("os_change_events", {"device": "r1\" | .drop table Syslog"})

    def test_unknown_template_and_param(self):
        with self.assertRaises(kusto_tool.KustoError):
            kusto_tool.bind_params("drop_everything", {})
        with self.assertRaises(kusto_tool.KustoError):
            kusto_tool.bind_params("os_change_events", {"device": "r1", "evil": 1})

    def test_defaults_and_range(self):
        _, bound = kusto_tool.bind_params("os_change_events", {"device": "rtr-lab-01"})
        self.assertEqual(bound["days"], 30)
        with self.assertRaises(kusto_tool.KustoError):
            kusto_tool.bind_params("os_change_events", {"device": "r1", "days": 9999})


class DeviceTests(unittest.TestCase):
    def test_unknown_device(self):
        with self.assertRaises(device_tool.DeviceError):
            device_tool.run_show("not-in-inventory", "show version")

    def test_blocked_command_never_runs(self):
        with self.assertRaises(device_tool.DeviceError):
            device_tool.run_show("rtr-lab-01", "reload")

    def test_secrets_redacted(self):
        out = device_tool.run_show("rtr-lab-01", "show running-config")["output"]
        self.assertNotIn("hashedvalue", out)


class ApiTests(unittest.TestCase):
    def test_run_allowed(self):
        r = api.run("tester", "rtr-lab-01", "show version")
        self.assertTrue(r["executed"])
        self.assertIn("7.5.2", r["result"]["output"])

    def test_run_blocked(self):
        r = api.run("tester", "rtr-lab-01", "reload")
        self.assertFalse(r["executed"])
        self.assertEqual(r["validation"]["decision"], "deny")
        self.assertEqual(r["validation"]["ai"]["verdict"], "skipped")

    def test_warning_needs_ack(self):
        r = api.run("tester", "rtr-lab-01", "show bgp summary")
        self.assertTrue(r.get("needs_acknowledgement"))
        self.assertFalse(r["executed"])
        r = api.run("tester", "rtr-lab-01", "show bgp summary", acknowledge_warning=True)
        self.assertTrue(r["executed"])


class AgentTests(unittest.TestCase):
    def test_downgrade_answered_from_kusto(self):
        r = agent.ask("When was the OS on rtr-lab-01 downgraded and who did it?", "tester")
        self.assertIn("jdoe", r["answer"])
        self.assertIn("2026-10-20", r["answer"])
        self.assertTrue(all(s["tool"] == "kusto_query" for s in r["steps"]))

    def test_falls_back_to_device(self):
        r = agent.ask("Was sw-lab-02 downgraded recently? Who did it?", "tester")
        tools = [s["tool"] for s in r["steps"]]
        self.assertEqual(tools[0], "kusto_query")
        self.assertIn("device_show", tools)
        self.assertIn("admin2", r["answer"])

    def test_device_before_kusto_is_refused(self):
        run = agent.Run("tester", "x")
        self.assertIn("error", run.device("rtr-lab-01", "show version"))


if __name__ == "__main__":
    unittest.main()
