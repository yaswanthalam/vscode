"""Optional real-browser smoke check: pip install playwright; uses installed Edge."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ROOT, load_inventory, make_server
from gemini_agent import Agent
from storage import Store


def main():
    from playwright.sync_api import expect, sync_playwright
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--https", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "test.sqlite3")
        agent = Agent("demo", load_inventory(ROOT / "inventory.json"), store, Path(tmp) / "known_hosts")
        context = None
        if args.https:
            from local_tls import local_context
            context, _, _ = local_context(Path(tmp) / "tls")
        server, token = make_server(agent, 0, tls_context=context)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                try:
                    # Exception is scoped to this temporary test browser context only.
                    page = browser.new_page(viewport={"width": 1366, "height": 1000},
                                            ignore_https_errors=args.https)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    scheme = "https" if args.https else "http"
                    page.goto(f"{scheme}://127.0.0.1:{server.server_port}")
                    page.locator("#token").fill(token)
                    page.locator("#connect-form button").click()
                    page.locator("#workspace").wait_for(state="visible")
                    assert page.locator("#devices input:checked").count() == 3
                    assert page.locator("#mode").inner_text() == "DEMO / SYNTHETIC"
                    page.locator("#question").fill("When was IOS downgraded and who did it?")
                    page.locator("#ask-button").click()
                    page.locator("#result-panel").wait_for(state="visible")
                    assert "UNKNOWN" in page.locator("#answer").inner_text()
                    assert page.locator(".plan .chip").count() == 12
                    assert page.locator("#evidence details").count() == 12
                    with page.expect_download() as download:
                        page.locator("#export").click()
                    report_path = Path(tmp) / "download.json"
                    download.value.save_as(report_path)
                    report = json.loads(report_path.read_text())
                    assert report["mode"] == "demo"
                    assert len(report["evidence"]) == 12
                    page.locator("#import-form").evaluate("(form) => form.closest('details').open = true")
                    page.locator("#log-text").fill("<script>window.pwned=true</script>\nHistorical record: actor unknown.")
                    page.locator("#import-form button").click()
                    expect(page.locator("#status")).to_contain_text("Stored unverified")
                    page.locator("#command-form").evaluate("(form) => form.closest('details').open = true")
                    page.locator("#command").select_option("version")
                    page.locator("#command-form button").click()
                    expect(page.locator(".plan .chip")).to_have_count(3)
                    assert not page.evaluate("window.pwned === true")
                    page.locator("#evidence details").evaluate_all(
                        "(items) => items.forEach(item => { item.open = true; })")
                    assert "<script>" in page.locator("#evidence").inner_text()
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    assert not errors, errors
                    print(f"Browser smoke ({scheme.upper()}): login, 3-device question, 12 checks, export, log import, manual command, text safety and mobile layout OK.")
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
