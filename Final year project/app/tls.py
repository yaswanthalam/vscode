import argparse
import ipaddress
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.config import ROOT

CERT_DIR = ROOT / ".certs"


def create_local_certificate(directory=CERT_DIR, renew=False):
    directory = Path(directory)
    paths = {
        "cert": directory / "server.pem",
        "key": directory / "server-key.pem",
        "ca": directory / "root-ca.pem",
        "windows_ca": directory / "root-ca.cer",
    }
    if any(path.exists() for path in paths.values()) and not renew:
        if not all(path.exists() for path in paths.values()):
            raise ValueError(
                "Incomplete local certificates. Run python -m app.tls --renew, then trust the new root."
            )
        cert = x509.load_pem_x509_certificate(paths["cert"].read_bytes())
        if cert.not_valid_after_utc <= datetime.now(timezone.utc) + timedelta(days=1):
            raise ValueError(
                "Local certificate expires soon. Run python -m app.tls --renew, then trust the new root."
            )
        return paths
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "HealthLens localhost development root"),
        ]
    )
    ca = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.NameConstraints(
                permitted_subtrees=[
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_network("127.0.0.1/32")),
                    x509.IPAddress(ipaddress.ip_network("::1/128")),
                ],
                excluded_subtrees=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False
        )
        .sign(root_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.IPAddress(ipaddress.ip_address("::1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
            critical=False,
        )
        .sign(root_key, hashes.SHA256())
    )
    key_bytes = server_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    descriptor = os.open(paths["key"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(key_bytes)
    paths["cert"].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    paths["ca"].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    paths["windows_ca"].write_bytes(ca.public_bytes(serialization.Encoding.DER))
    # The signing key is never persisted; the saved server key cannot issue other certificates.
    return paths


def main():
    parser = argparse.ArgumentParser(
        description="Generate localhost-only development TLS certificates."
    )
    parser.add_argument(
        "--renew",
        action="store_true",
        help="Replace certificates; the new root must be trusted again",
    )
    args = parser.parse_args()
    paths = create_local_certificate(renew=args.renew)
    print("Local certificate ready. Expires after 90 days. No trust store was modified.")
    print("Windows: import this public certificate into your current-user trusted root store:")
    print(paths["windows_ca"])


if __name__ == "__main__":
    main()
