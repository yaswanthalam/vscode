import argparse
import os
import ssl
from urllib.parse import urlparse

import uvicorn

from app.config import Settings


def main():
    settings = Settings()
    parser = argparse.ArgumentParser(
        description="Start HealthLens with direct TLS or a private VS Code tunnel."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--private-tunnel",
        action="store_true",
        help="Use HTTP on loopback behind a private HTTPS Dev Tunnel",
    )
    parser.add_argument(
        "--tunnel-origin", help="Exact forwarded HTTPS address from VS Code's Ports panel"
    )
    args = parser.parse_args()
    if args.tunnel_origin and not args.private_tunnel:
        parser.error("--tunnel-origin requires --private-tunnel")
    if args.private_tunnel:
        os.environ["TRANSPORT_MODE"] = "private_tunnel"
        configured_tunnel = (
            settings.app_origin if settings.transport_mode == "private_tunnel" else None
        )
        os.environ["APP_ORIGIN"] = (
            args.tunnel_origin or configured_tunnel or "https://pending-configuration.devtunnels.ms"
        ).rstrip("/")
        settings = Settings()
    settings.validate_deployment()
    if settings.transport_mode == "private_tunnel":
        if args.host not in {"127.0.0.1", "::1"}:
            parser.error("Private tunnel mode must bind to loopback, not a network interface")
        print(
            "Private-tunnel backend only: HTTP on loopback. Browser access must use the private HTTPS forwarded address.",
            flush=True,
        )
        if settings.app_origin == "https://pending-configuration.devtunnels.ms":
            print(
                "SETUP: VS Code > Ports > Forward a Port > 8000. Keep visibility PRIVATE.",
                flush=True,
            )
            print(
                "Then stop this process (Ctrl+C) and restart with --private-tunnel --tunnel-origin YOUR_EXACT_HTTPS_FORWARDED_ADDRESS.",
                flush=True,
            )
            print(
                "Application access is blocked until that exact address is configured.", flush=True
            )
        else:
            print("Open in browser: " + settings.app_origin, flush=True)
        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port or 8000,
            proxy_headers=False,
        )
        return
    origin = urlparse(settings.app_origin)
    if not settings.tls_cert_file.is_file() or not settings.tls_key_file.is_file():
        parser.error("TLS certificate/key missing. For local development run: python -m app.tls")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port or origin.port or 443,
        ssl_certfile=str(settings.tls_cert_file),
        ssl_keyfile=str(settings.tls_key_file),
        ssl_version=ssl.PROTOCOL_TLS_SERVER,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
