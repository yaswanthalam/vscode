"""The model selects IDs, never executable command text."""
import re

COMMANDS = {
    "version": ("show version", "Current IOS image, version, uptime and reload reason"),
    "interfaces": ("show ip interface brief", "Interface addresses and line/protocol state"),
    "interface_detail": ("show interfaces", "Interface errors, counters and link details"),
    "bgp": ("show ip bgp summary", "BGP session state; numeric State/PfxRcd means established"),
    "routes": ("show ip route", "IPv4 routing table"),
    "isis": ("show isis neighbors", "IS-IS neighbor state"),
    "ospf": ("show ip ospf neighbor", "OSPF neighbors"),
    "lacp": ("show lacp summary", "LACP summary, if supported by this image"),
    "etherchannel": ("show etherchannel summary", "Port-channel state, if supported"),
    "cpu": ("show processes cpu", "CPU utilization and processes"),
    "memory": ("show processes memory", "Memory pools and processes"),
    "environment": ("show environment", "Temperature, fans and power, if supported"),
    "inventory": ("show inventory", "Hardware inventory, if supported"),
    "logs": ("show logging", "Retained device syslog buffer, not guaranteed complete"),
    "clock": ("show clock detail", "Device clock and clock source"),
    "boot": ("show bootvar", "Boot variables, if supported"),
    "config_history": ("show archive log config all", "Config accounting, only if already enabled"),
    "users": ("show users", "Current sessions; not historical change attribution"),
}
MAX_STEPS = 12
MAX_OUTPUT = 24000
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def command_for(command_id):
    if not isinstance(command_id, str) or command_id not in COMMANDS:
        raise ValueError("Command ID is not in the exact reviewed allowlist.")
    return COMMANDS[command_id][0]


def validate_plan(plan, selected):
    if not isinstance(plan, dict) or set(plan) != {"steps"}:
        raise ValueError("AI returned an invalid plan.")
    steps = plan["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError(f"Plan must have 1-{MAX_STEPS} steps.")
    seen = set()
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"device", "command_id"}:
            raise ValueError("Invalid plan step.")
        if not isinstance(step["device"], str) or step["device"] not in selected:
            raise ValueError("Plan attempted to access an unselected device.")
        command_for(step["command_id"])
        key = (step["device"], step["command_id"])
        if key in seen:
            raise ValueError("AI returned duplicate commands.")
        seen.add(key)
    missing = set(selected) - {device for device, _ in seen}
    if missing:
        raise ValueError("AI plan omitted selected devices: " + ", ".join(sorted(missing)) +
                         ". No commands executed; narrow the selected scope or retry.")
    return steps


def clean_terminal(text):
    text = ANSI.sub("", text).replace("\r", "")
    # Apply backspaces used by IOS to erase the pagination prompt.
    while "\b" in text:
        updated = re.sub(r"[^\n]\x08", "", text)
        if updated == text:
            text = text.replace("\b", "")
            break
        text = updated
    return "".join(c for c in text if c in "\n\t" or ord(c) >= 32)


def redact(text, secrets=()):
    text = clean_terminal(text)
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)",
                  "[REDACTED PRIVATE KEY]", text, flags=re.S)
    text = re.sub(
        r"(?im)^.*(?:\b(?:password|secret|community|private.key|api.key|"
        r"key.string|authentication.key|authorization|access.token)\b).*$",
        "[REDACTED sensitive line]", text,
    )
    return text
