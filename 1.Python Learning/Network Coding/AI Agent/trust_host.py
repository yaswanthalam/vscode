"""Display SSH host fingerprints; save only after independent verification."""
import argparse
import base64
import hashlib
import hmac
import socket

from app import ROOT, load_inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", help="Inventory ID, such as R1")
    parser.add_argument("--inventory", default=ROOT / "inventory.json")
    parser.add_argument("--fingerprint", help="Independently verified SHA256:... fingerprint")
    args = parser.parse_args()
    import paramiko
    inventory = load_inventory(args.inventory)
    if args.device not in inventory:
        parser.error("Unknown device ID")
    device = inventory[args.device]
    with socket.create_connection((device["host"], device["port"]), timeout=8) as sock:
        with paramiko.Transport(sock) as transport:
            transport.start_client(timeout=10)
            key = transport.get_remote_server_key()
            digest = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
            fingerprint = "SHA256:" + digest
    print(f"{args.device} {device['host']}:{device['port']} {key.get_name()} {fingerprint}")
    if not args.fingerprint:
        print("NOT SAVED. Verify this fingerprint using a trusted console or administrator, "
              "then rerun with --fingerprint SHA256:...")
        return
    if not hmac.compare_digest(args.fingerprint, fingerprint):
        parser.error("Fingerprint mismatch; host key NOT saved")
    path = ROOT / "known_hosts"
    keys = paramiko.HostKeys()
    if path.exists():
        keys.load(str(path))
    host = device["host"] if device["port"] == 22 else f"[{device['host']}]:{device['port']}"
    existing = keys.lookup(host)
    if existing and (key.get_name() not in existing or existing[key.get_name()] != key):
        parser.error("An enrolled key differs. Investigate before manually updating known_hosts.")
    keys.add(host, key.get_name(), key)
    keys.save(str(path))
    print("Verified host key saved locally. No credentials were used and no CLI commands were sent.")


if __name__ == "__main__":
    main()
