
from playwright.sync_api import sync_playwright
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
import sys

def main():
    url = sys.argv[1].strip()

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    screenshot_folder = Path("screenshots")
    screenshot_folder.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        try:
            page = browser.new_page()

            print(f"Opening: {url}", flush=True)

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            print("Page title:", page.title(), flush=True)

            timestamp = datetime.now().strftime(
                "%Y-%m-%d_%H-%M-%S-%f"
            )

            website_name = urlparse(url).hostname or "website"
            website_name = "".join(
                c if c.isalnum() or c in "-_" else "_"
                for c in website_name
            )

            unique_id = uuid4().hex[:8]

            filename = (
                f"{website_name}_{timestamp}_{unique_id}.png"
            )

            screenshot_path = screenshot_folder / filename

            page.screenshot(
                path=str(screenshot_path),
                full_page=True
            )

            print(
                "Screenshot saved:",
                screenshot_path.resolve(),
                flush=True
            )

        finally:
            browser.close()

if __name__ == "__main__":
    main()
