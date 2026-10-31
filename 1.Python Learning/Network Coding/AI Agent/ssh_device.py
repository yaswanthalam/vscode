"""Cisco IOS interactive SSH: exact show commands and pagination spaces only."""
import os
from pathlib import Path
import re
import time

from policy import MAX_OUTPUT, clean_terminal, command_for

PROMPT = re.compile(r"(?:^|\n)([A-Za-z0-9_.:/-]+[>#])\s*$")
CLI_ERROR = re.compile(
    r"(?im)^%\s*(?:Invalid input|Ambiguous command|Incomplete command|"
    r"Authorization failed|Error|Unrecognized command|Unknown command|"
    r"Access denied|Permission denied|Command authorization failed)"
)


class DeviceError(RuntimeError):
    pass


def credentials(device):
    def setting(suffix):
        return os.environ.get(f"{device}_{suffix}") or os.environ.get(f"NETWORK_{suffix}") or None
    result = {"username": setting("USERNAME"), "password": setting("PASSWORD"),
              "key_filename": setting("KEY_FILE"), "passphrase": setting("KEY_PASSPHRASE")}
    if not result["username"] or not (result["password"] or result["key_filename"]):
        raise DeviceError(f"Set local credentials for {device} in .env before live SSH.")
    return result


def receive(channel, prompt=None, timeout=20):
    deadline = time.monotonic() + timeout
    chunks = bytearray()
    page_count = 0
    while time.monotonic() < deadline:
        if channel.recv_ready():
            chunk = channel.recv(4096)
            if not chunk:
                raise DeviceError("SSH channel closed before the IOS prompt.")
            chunks.extend(chunk)
            raw = chunks.decode("utf-8", errors="replace")
            text = clean_terminal(raw)
            if len(chunks) >= MAX_OUTPUT:
                return text[:MAX_OUTPUT], True, None
            # Count raw markers, even when IOS later erases them with backspaces.
            pages = raw.count("--More--")
            if prompt and pages > page_count:
                for _ in range(pages - page_count):
                    channel.sendall(" ")
                page_count = pages
            if prompt:
                if re.search(r"(?:^|\n)" + re.escape(prompt) + r"\s*$", text):
                    return text, False, prompt
            else:
                match = PROMPT.search(text)
                if match:
                    return text, False, match.group(1)
        elif channel.closed:
            raise DeviceError("SSH channel closed before command completion.")
        else:
            time.sleep(0.03)
    raise DeviceError("Timed out waiting for IOS output; no complete evidence collected.")


def run_show(device_id, device, command_id, known_hosts):
    command = command_for(command_id)  # Revalidate at the execution boundary.
    import paramiko
    auth = credentials(device_id)
    if not Path(known_hosts).is_file():
        raise DeviceError("known_hosts is missing. Enroll and verify SSH host keys first.")
    try:
        with paramiko.SSHClient() as client:
            client.load_host_keys(str(known_hosts))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(hostname=device["host"], port=device["port"], **auth,
                           allow_agent=False, look_for_keys=False,
                           timeout=8, auth_timeout=8, banner_timeout=8, channel_timeout=8)
            with client.invoke_shell(width=200, height=1000) as channel:
                channel.settimeout(8)
                _, truncated, prompt = receive(channel, timeout=10)
                if truncated or not prompt:
                    raise DeviceError("Could not establish an IOS EXEC prompt.")
                # Never send enable, terminal settings, configuration, shell or file commands.
                channel.sendall(command + "\n")
                output, truncated, _ = receive(channel, prompt)
                lines = output.splitlines()
                if lines and lines[0].strip() == command:
                    lines.pop(0)
                if lines and lines[-1].strip() == prompt:
                    lines.pop()
                output = "\n".join(lines).replace("--More--", "").strip()
                status = "unsupported_or_denied" if CLI_ERROR.search(output) else "ok"
                if not output:
                    raise DeviceError("Device returned empty output.")
                return {"command": command, "status": status, "output": output,
                        "truncated": truncated}
    except paramiko.BadHostKeyException as exc:
        raise DeviceError("SSH host key changed. Verify the device identity; access blocked.") from exc
    except paramiko.AuthenticationException as exc:
        raise DeviceError("SSH authentication failed; check the local read-only account.") from exc
    except (paramiko.SSHException, OSError, EOFError) as exc:
        raise DeviceError(
            "SSH connection failed. Check reachability, verified known_hosts, IOS SSH "
            "algorithms and device permissions. No insecure algorithm fallback is enabled."
        ) from exc
