
from playwright.sync_api import sync_playwright
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse

def main():

    # Step 1: Ask user to enter website URL
    url = input("Enter website URL: ").strip()

    if not url:
        print("Error: URL cannot be empty.")
        return

    # Add https:// if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Step 2: Create screenshots folder
    screenshot_folder = Path("screenshots")
    screenshot_folder.mkdir(parents=True, exist_ok=True)

    # Step 3: Launch browser
    with sync_playwright() as p:

        browser = p.chromium.launch(headless=False)

        try:
            page = browser.new_page()

            print(f"\nOpening website: {url}")

            # Step 4: Navigate to user-provided URL
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            print("Page title:", page.title())

            # Step 5: Generate unique filename
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
            unique_id = uuid4().hex[:8]

            # Include website name in filename
            website_name = urlparse(url).hostname or "website"
            website_name = "".join(
                c if c.isalnum() or c in "-_" else "_"
                for c in website_name
            )

            screenshot_name = (
                f"{website_name}_{timestamp}_{unique_id}.png"
            )

            screenshot_path = screenshot_folder / screenshot_name

            # Step 6: Take full-page screenshot
            page.screenshot(
                path=str(screenshot_path),
                full_page=True
            )

            print("\nScreenshot captured successfully!")
            print(f"Saved location: {screenshot_path.resolve()}")

        except Exception as error:
            print(f"\nError: {error}")

        finally:
            browser.close()


if __name__ == "__main__":
    main()
