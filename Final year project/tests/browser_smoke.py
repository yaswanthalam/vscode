"""Run explicitly with python -m tests.browser_smoke (not part of pytest)."""

import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from app.config import ROOT
from app.tls import CERT_DIR, create_local_certificate
from tests.test_workflow import FEATURES


def main():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    create_local_certificate()
    tls_context = ssl.create_default_context(cafile=str(CERT_DIR / "root-ca.pem"))
    origin = f"https://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="healthlens-browser-") as directory:
        env = {
            **os.environ,
            "APP_ENV": "test",
            "TRANSPORT_MODE": "direct_tls",
            "APP_ORIGIN": origin,
            "DATA_DIR": directory,
            "MODEL_DIR": str(ROOT / "models"),
            "ALLOW_DEMO_MODELS": "true",
            "AZURE_OPENAI_ENDPOINT": "",
            "AZURE_OPENAI_API_KEY": "",
            "AZURE_OPENAI_DEPLOYMENT": "",
            "NVIDIA_API_KEY": "",
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(process.stderr.read().decode())
                try:
                    with urllib.request.urlopen(
                        origin + "/ready", timeout=1, context=tls_context
                    ) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.2)
            else:
                raise RuntimeError("Browser test server was not ready")
            with sync_playwright() as playwright:
                edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
                options = {"executable_path": str(edge)} if edge.exists() else {}
                browser = playwright.chromium.launch(headless=True, **options)
                context = browser.new_context(accept_downloads=True)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(origin)
                page.locator("#auth-toggle").click()
                page.locator("#auth-user").fill("browser-student")
                page.locator("#auth-password").fill("Browser-fictional-password-2026!")
                page.locator("#auth-submit").click()
                expect(page.locator("#workspace")).to_be_visible()
                page.locator("#report-file").set_input_files(
                    ROOT / "samples" / "diabetes-report.txt"
                )
                page.locator("#upload").click()
                expect(page.locator("#field-glucose")).to_have_value("110")
                for disease, features in FEATURES.items():
                    page.locator(f'[data-disease="{disease}"]').click()
                    for key, value in features.items():
                        page.locator("#field-" + key).fill(str(value))
                    page.locator("#confirmed").check()
                    page.locator("#assess-submit").click()
                    expect(page.locator("#result")).to_be_visible()
                    expect(page.locator("#result")).to_contain_text("SYNTHETIC DEMO")
                with page.expect_download() as downloaded:
                    page.locator("#result .download").click()
                assert Path(downloaded.value.path()).read_bytes().startswith(b"%PDF-")
                page.locator('[data-tab="history"]').click()
                expect(page.locator(".history-item")).to_have_count(3)
                page.locator('[data-tab="chat"]').click()
                page.locator("#chat-disease").select_option("kidney")
                page.locator("#question").fill("What should I ask about kidney nutrition?")
                page.locator("#chat-form button").click()
                expect(page.locator("#chat-messages .source").first).to_be_visible()
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.locator('[data-tab="assessment"]').click()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.set_viewport_size({"width": 1280, "height": 900})
                page.on("dialog", lambda dialog: dialog.accept())
                page.locator('[data-tab="privacy"]').click()
                page.locator("#delete-password").fill("Browser-fictional-password-2026!")
                page.locator("#delete-account-form button").click()
                expect(page.locator("#auth")).to_be_visible()
                assert not errors, errors
                browser.close()
                print(
                    "Browser workflow passed: registration, three modules, upload, PDF, history, chat, mobile and account deletion."
                )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
