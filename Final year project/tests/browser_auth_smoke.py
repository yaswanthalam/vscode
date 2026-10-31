"""Deterministic GUI check: python -m tests.browser_auth_smoke."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from app.config import ROOT


def main():
    origin = "https://healthlens.test"
    captured = []
    with sync_playwright() as playwright:
        edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        options = {"executable_path": str(edge)} if edge.exists() else {}
        browser = playwright.chromium.launch(headless=True, **options)
        page = browser.new_page()
        page.clock.install()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route_request(route):
            path = route.request.url.removeprefix(origin)
            if path == "/":
                route.fulfill(
                    path=str(ROOT / "app" / "static" / "index.html"), content_type="text/html"
                )
            elif path in {"/static/app.js", "/static/style.css"}:
                route.fulfill(
                    path=str(
                        ROOT
                        / "app"
                        / "static"
                        / ("app.js" if path.endswith(".js") else "style.css")
                    ),
                    content_type="application/javascript" if path.endswith(".js") else "text/css",
                )
            elif path == "/api/auth/me":
                route.fulfill(status=401, json={"detail": "Please sign in"})
            elif path == "/api/auth/account-status":
                body = json.loads(route.request.post_data)
                captured.append(body)
                route.fulfill(json={"exists": body["username"] == "fictional-existing"})
            elif path == "/api/auth/login":
                route.fulfill(status=504, content_type="text/html", body="Gateway Timeout")
            else:
                route.fulfill(status=404)

        page.route(origin + "/**", route_request)
        page.goto(origin)
        page.locator("#auth-user").fill("fictional-existing")
        page.locator("#account-check").click()
        expect(page.locator("#account-status")).to_contain_text("Account exists")
        page.locator("#auth-user").fill("fictional-missing")
        expect(page.locator("#account-status")).to_be_hidden()
        page.locator("#account-check").click()
        expect(page.locator("#account-status")).to_contain_text("No account found")
        assert captured == [{"username": "fictional-existing"}, {"username": "fictional-missing"}]
        page.locator("#auth-password").fill("Fictional-browser-password-2026!")
        page.evaluate("""() => {
            const original = window.fetch.bind(window);
            window.stallLogin = true;
            window.fetch = (url, options = {}) => {
                if (url === "/api/auth/login" && window.stallLogin) {
                    return new Promise((resolve, reject) => {
                        options.signal.addEventListener("abort", () => {
                            reject(new DOMException("Timed out", "AbortError"));
                        }, { once: true });
                    });
                }
                return original(url, options);
            };
        }""")
        page.locator("#auth-submit").click()
        expect(page.locator("#auth-submit")).to_be_disabled()
        page.clock.fast_forward(21000)
        expect(page.locator("#status")).to_contain_text("timed out")
        expect(page.locator("#auth-submit")).to_be_enabled()
        page.evaluate("window.stallLogin = false")
        page.locator("#auth-submit").click()
        expect(page.locator("#status")).to_contain_text("private tunnel gateway")
        expect(page.locator("#auth-submit")).to_be_enabled()
        assert not errors, errors
        browser.close()
    print(
        "GUI passed: existing/missing account, no password in lookup, stalled-request timeout and 504 message."
    )


if __name__ == "__main__":
    main()
