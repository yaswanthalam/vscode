"""A bounded plan -> read-only tools -> evidence-based answer agent."""
import os
import re
import threading
import uuid

from ai_providers import AgentError, FailoverAI, Gemini, LIMITATIONS
from policy import MAX_OUTPUT, MAX_STEPS, command_for, redact, validate_plan
from ssh_device import DeviceError, run_show
from storage import stamp

class BusyError(AgentError):
    pass


def demo_plan(question, devices):
    q = question.lower()
    ids = []
    for pattern, commands in [
        (r"version|image|ios|upgrade|downgrade|who|when", ["version", "logs", "clock", "config_history"]),
        (r"interface|link|\bup\b|\bdown\b", ["interfaces"]),
        (r"bgp", ["bgp"]), (r"isis|is-is", ["isis"]), (r"ospf", ["ospf"]),
        (r"lacp|etherchannel|port.channel", ["lacp", "etherchannel"]),
        (r"cpu|processor", ["cpu"]), (r"memory|ram", ["memory"]),
        (r"power|fan|temperature|environment", ["environment"]),
        (r"log|syslog", ["logs", "clock"]),
    ]:
        if re.search(pattern, q):
            ids.extend(commands)
    ids = list(dict.fromkeys(ids or ["version", "interfaces", "cpu"]))
    # Interleave devices so every selected device gets a check within the budget.
    return {"steps": [{"device": device, "command_id": cid}
                      for cid in ids for device in devices][:MAX_STEPS]}


def demo_output(device, command_id):
    interfaces = {
        "R1": "Ethernet1/0  10.12.12.1       YES manual up      up\n"
              "Ethernet1/1  192.168.32.168   YES DHCP   up      up",
        "R2": "Ethernet1/0  10.12.12.2       YES manual up      up\n"
              "Ethernet1/1  10.23.23.1       YES manual up      up\n"
              "Ethernet1/2  192.168.32.167   YES DHCP   up      up",
        "R3": "Ethernet1/0  192.168.32.166   YES DHCP   up      up\n"
              "Ethernet1/1  10.23.23.2       YES manual up      up",
    }
    samples = {
        "version": f"{device}: SYNTHETIC Cisco IOS Software, Version 15.2(4)S7\n"
                   "System image file is flash:c7200-demo.bin\nUptime is 2 days",
        "interfaces": "Interface    IP-Address       OK? Method Status  Protocol\n"
                      + interfaces.get(device, "No synthetic interface fixture for this device."),
        "bgp": "% BGP not active",
        "isis": "% IS-IS not running",
        "cpu": "CPU utilization for five seconds: 4%/1%; one minute: 3%; five minutes: 2%",
        "memory": "Processor Pool Total: 256000000 Used: 64000000 Free: 192000000",
        "logs": "%SYS-5-RESTART: System restarted (synthetic; no retained actor or image-change record)",
        "clock": f"Collector UTC: {stamp()} (synthetic; not a device clock reading)",
    }
    output = samples.get(command_id, "% Invalid input detected at '^' marker. (synthetic unsupported command)")
    return {"command": command_for(command_id),
            "status": "unsupported_or_denied" if output.startswith("%") else "ok",
            "output": "SYNTHETIC DEMO - NOT A REAL DEVICE OBSERVATION\n" + output,
            "truncated": False}


class Agent:
    def __init__(self, mode, inventory, store, known_hosts, ai_factory=FailoverAI, runner=run_show):
        self.mode, self.inventory, self.store = mode, inventory, store
        self.known_hosts, self.ai_factory, self.runner = known_hosts, ai_factory, runner
        self.lock = threading.Lock()

    def devices(self, selected):
        if (not isinstance(selected, list) or not selected or
                any(not isinstance(d, str) or d not in self.inventory for d in selected) or
                len(set(selected)) != len(selected)):
            raise ValueError("Select one or more registered devices without duplicates.")
        return selected

    def secrets(self):
        return [v for k, v in os.environ.items()
                if k in {"GEMINI_API_KEY", "OPENROUTER_API_KEY", "NETWORK_PASSWORD", "NETWORK_KEY_PASSPHRASE"}
                or k.endswith(("_PASSWORD", "_KEY_PASSPHRASE"))]

    def scrub(self, text):
        return redact(text, self.secrets())

    def investigate(self, request):
        if not isinstance(request, dict):
            raise ValueError("Request must be a JSON object.")
        selected = self.devices(request.get("devices"))
        question = request.get("question", "")
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise ValueError("Question must be 1-2000 characters.")
        manual = request.get("command_id")
        if manual is not None:
            command_for(manual)
        if not self.lock.acquire(blocking=False):
            raise BusyError("An investigation is already running. Wait for it to finish.")
        ai = None
        try:
            run_id = uuid.uuid4().hex
            self.store.audit("investigation_started", run_id=run_id, mode=self.mode,
                             devices=selected, manual=manual is not None)
            if manual is not None:
                plan = {"steps": [{"device": d, "command_id": manual} for d in selected]}
            elif self.mode == "demo":
                plan = demo_plan(question, selected)
            else:
                ai = self.ai_factory()
                try:
                    plan = ai.plan(self.scrub(question), selected)
                except AgentError:
                    self.store.audit("ai_failed", run_id=run_id, attempts=getattr(ai, "trace", []))
                    raise
            steps = validate_plan(plan, selected)
            # Past observations are captured BEFORE this run; keep demo/live separate.
            history = self.store.history(self.mode, selected, limit=12, source="ssh")
            logs = self.store.history(self.mode, selected, limit=12, source="syslog")
            imports = self.store.history(self.mode, selected, limit=6, source="import")
            evidence = history + logs + imports
            for step in steps:
                device, cid = step["device"], step["command_id"]
                self.store.audit("command_started", run_id=run_id, device=device, command_id=cid)
                try:
                    result = (demo_output(device, cid) if self.mode == "demo" else
                              self.runner(device, self.inventory[device], cid, self.known_hosts))
                except DeviceError as exc:
                    result = {"command": command_for(cid), "status": "error",
                              "output": str(exc), "truncated": False}
                raw = result["output"]
                result["output"] = self.scrub(raw[:MAX_OUTPUT])
                result["truncated"] = result["truncated"] or len(raw) > MAX_OUTPUT
                record = self.store.save(self.mode, device, "ssh", run_id=run_id,
                                         command_id=cid, **result)
                evidence.append(record)
                self.store.audit("command_finished", run_id=run_id, device=device,
                                 command_id=cid, status=result["status"], evidence_id=record["id"])
            warnings = list(LIMITATIONS)
            if self.mode == "demo":
                answer = ("DEMO MODE: All command output is synthetic; no SSH or Google calls were made.\n\n"
                          "The keyword-based demo selected the checks shown below. This is not a "
                          "live health assessment. Inspect each command's raw evidence.\n\n"
                          "OS downgrade time and actor: UNKNOWN. No authenticated historical "
                          "image-change and AAA accounting evidence is available.")
            elif manual is not None:
                answer = "Read-only command collection complete. Inspect the evidence and status below. No data was sent to any AI provider."
            else:
                # A global prompt budget bounds cloud data, while full records stay local.
                budget = 55000
                model_evidence = []
                clipped = False
                for item in reversed(evidence):
                    if budget <= 0:
                        clipped = True
                        break
                    entry = dict(item)
                    output = entry.get("output", "")
                    allowed = min(len(output), 6000, budget)
                    if len(output) > allowed:
                        entry["output"] = output[:allowed]
                        entry["truncated"] = True
                        clipped = True
                    budget -= allowed + 600
                    model_evidence.append(entry)
                if clipped:
                    warnings.append("AI received a bounded subset of local evidence; inspect full output below.")
                try:
                    answer = ai.answer(self.scrub(question), model_evidence)
                except AgentError as exc:
                    warnings.append(str(exc))
                    answer = "AI interpretation failed. Collected evidence is preserved below; no AI diagnosis is available."
            trace = getattr(ai, "trace", [])
            warnings.extend(f"AI {item['stage']}: {item['detail']}"
                            for item in trace if item["status"] == "failed")
            if trace:
                self.store.audit("ai_providers", run_id=run_id, attempts=trace)
            report = {"run_id": run_id, "mode": self.mode, "completed_at": stamp(),
                      "question": self.scrub(question), "plan": steps,
                      "answer": self.scrub(answer), "evidence": evidence, "warnings": warnings,
                      "ai_trace": trace}
            self.store.save_report(report)
            self.store.audit("investigation_finished", run_id=run_id, evidence_count=len(evidence))
            return report
        finally:
            try:
                if ai is not None:
                    ai.close()
            finally:
                self.lock.release()

    def import_log(self, request):
        if not isinstance(request, dict):
            raise ValueError("Request must be an object.")
        device = self.devices([request.get("device")])[0]
        text = request.get("text")
        if not isinstance(text, str) or not 1 <= len(text) <= MAX_OUTPUT:
            raise ValueError(f"Log text must be 1-{MAX_OUTPUT} characters.")
        self.store.audit("log_import", mode=self.mode, device=device)
        return self.store.save(self.mode, device, "import", output=self.scrub(text),
                               status="unverified_import", truncated=False,
                               note="User-supplied log text. Import time is not event time; authenticity not verified.")
