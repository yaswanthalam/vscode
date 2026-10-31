"""Single-user loopback GUI for the read-only lab agent."""
import argparse
import hmac
import ipaddress
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import secrets
import sqlite3

from gemini_agent import Agent, AgentError, BusyError
from ai_providers import provider_status
from policy import COMMANDS
from storage import Store

ROOT = Path(__file__).resolve().parent
MAX_BODY = 110000


def load_inventory(path):
    inventory = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(inventory, dict) or not 1 <= len(inventory) <= 10:
        raise ValueError("Inventory must contain 1-10 devices.")
    addresses = set()
    for name, device in inventory.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", name):
            raise ValueError("Inventory device names must be safe identifiers.")
        if not isinstance(device, dict):
            raise ValueError("Inventory entries must be objects.")
        ipaddress.IPv4Address(device["host"])
        port = device.get("port", 22)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("SSH port must be 1-65535.")
        device["port"] = port
        if device["host"] in addresses:
            raise ValueError("Each device must have a unique management IP for syslog mapping.")
        addresses.add(device["host"])
    return inventory


def make_server(agent, port=8501, token=None, tls_context=None):
    session_token = token or secrets.token_urlsafe(32)
    scheme = "https" if tls_context else "http"

    class LocalServer(ThreadingHTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(10)
            if tls_context is not None:
                try:
                    connection = tls_context.wrap_socket(connection, server_side=True)
                except OSError:
                    connection.close()
                    raise
            return connection, address

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, fmt, *args):
            pass  # Never log request bodies, tokens or device output.

        def reply(self, status, payload, content_type="application/json"):
            body = json.dumps(payload).encode() if content_type == "application/json" else payload
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; "
                             "base-uri 'none'; form-action 'self'")
            try:
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionError, TimeoutError):
                self.close_connection = True
                logging.warning("Client disconnected before receiving the response. "
                                "Completed evidence remains in local storage.")

        def permitted(self):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != host:
                self.reply(403, {"error": "Use the printed 127.0.0.1 address."})
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin != f"{scheme}://{host}":
                self.reply(403, {"error": "Cross-origin requests are blocked."})
                return False
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied.encode(), ("Bearer " + session_token).encode()):
                self.reply(401, {"error": "Enter the local session token printed in the terminal."})
                return False
            return True

        def do_GET(self):
            static = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if self.path in static:
                name, kind = static[self.path]
                self.reply(200, (ROOT / "static" / name).read_bytes(), kind)
                return
            if not self.permitted():
                return
            if self.path == "/api/status":
                providers = provider_status()
                self.reply(200, {"mode": agent.mode, "devices": agent.inventory,
                                "commands": {k: {"command": v[0], "purpose": v[1]}
                                             for k, v in COMMANDS.items()},
                                "ai_configured": any(item["configured"] for item in providers),
                                "ai_providers": providers,
                                "google_sharing": os.environ.get("ALLOW_GOOGLE_DEVICE_DATA", "").lower() == "true"})
            else:
                self.reply(404, {"error": "Unknown route."})

        def do_POST(self):
            if not self.permitted():
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Transfer encoding is unsupported.")
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Send application/json.")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    self.reply(413, {"error": "Request is empty or too large."})
                    return
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("Incomplete request.")
                request = json.loads(body)
                if self.path == "/api/investigate":
                    result = agent.investigate(request)
                elif self.path == "/api/import":
                    result = agent.import_log(request)
                else:
                    self.reply(404, {"error": "Unknown route."})
                    return
                self.reply(200, result)
            except BusyError as exc:
                self.reply(409, {"error": str(exc)})
            except (ValueError, UnicodeDecodeError) as exc:
                self.reply(400, {"error": str(exc)})
            except AgentError as exc:
                self.reply(502, {"error": str(exc)})
            except (sqlite3.Error, OSError):
                logging.error("Local I/O failed. Investigation not completed; check database/disk.")
                self.reply(503, {"error": "Local storage or I/O failed. Investigation is incomplete."})
            except Exception:
                logging.error("Unexpected backend error. Investigation not completed.")
                self.reply(500, {"error": "Unexpected backend failure. Investigation is incomplete; see local setup and tests."})

    server = LocalServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server, session_token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--https", action="store_true", help="Use a local self-signed HTTPS certificate")
    parser.add_argument("--inventory", type=Path, default=ROOT / "inventory.json")
    parser.add_argument("--syslog", action="store_true", help="Enable UDP receiver (live only)")
    parser.add_argument("--syslog-bind", default="127.0.0.1")
    parser.add_argument("--syslog-port", type=int, default=5514)
    args = parser.parse_args()
    if (ROOT / ".env").exists():
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    if args.syslog and args.mode != "live":
        parser.error("--syslog requires --mode live")
    try:
        provider_status()
    except AgentError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    agent = Agent(args.mode, load_inventory(args.inventory), Store(ROOT / "data" / "evidence.sqlite3"),
                  ROOT / "known_hosts")
    receiver = None
    tls_context = None
    if args.https:
        from local_tls import local_context
        tls_context, cert_path, fingerprint = local_context(ROOT / "data" / "tls")
    try:
        server, token = make_server(agent, args.port, tls_context=tls_context)
    except OSError as exc:
        parser.exit(1, f"Could not listen on 127.0.0.1:{args.port}: {exc}\n")
    try:
        if args.syslog:
            from syslog_receiver import SyslogReceiver
            receiver = SyslogReceiver(args.syslog_bind, args.syslog_port, agent)
            receiver.start()
            print(f"UDP syslog: {args.syslog_bind}:{args.syslog_port} (source IP is not authentication)")
        print(f"\nRead-only Network Agent [{args.mode.upper()}]")
        scheme = "https" if args.https else "http"
        print(f"Open: {scheme}://127.0.0.1:{server.server_port}")
        if args.https:
            print(f"Local development certificate: {cert_path}")
            print(f"Certificate SHA256: {fingerprint}")
            print("Self-signed: browsers may warn. OS certificate trust has NOT been changed.")
        print(f"Local session token: {token}")
        print("Paste the token in the GUI. Keep this terminal open. Ctrl+C to stop.\n", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if receiver:
            receiver.close()
        server.server_close()


if __name__ == "__main__":
    main()
