"""Optional UDP syslog receiver. UDP source IP does not authenticate a sender."""
import ipaddress
import logging
import socket
import sqlite3
import threading


class SyslogReceiver:
    def __init__(self, bind, port, agent):
        self.agent = agent
        self.sources = {d["host"]: name for name, d in agent.inventory.items()}
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((str(ipaddress.IPv4Address(bind)), port))
        self.socket.settimeout(0.5)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="syslog", daemon=True)

    def start(self):
        self.thread.start()

    def ingest(self, payload, address):
        device = self.sources.get(address[0])
        if not device:
            return
        self.agent.store.save("live", device, "syslog",
                              output=self.agent.scrub(payload.decode("utf-8", errors="replace")),
                              status="unverified_udp", truncated=len(payload) >= 8192,
                              note="UDP source matched inventory; spoofing is possible. observed_at is receipt UTC.")

    def run(self):
        while not self.stop_event.is_set():
            try:
                payload, address = self.socket.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                if not self.stop_event.is_set():
                    logging.error("Syslog socket failed; receiver stopped.")
                return
            try:
                self.ingest(payload, address)
            except (OSError, sqlite3.Error):
                logging.error("Syslog persistence failed; receiver stopped. Check local disk/database.")
                return

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=2)
        self.socket.close()
