
from playwright.sync_api import sync_playwright
from datetime import datetime
from pathlib import Path
from uuid import uuid4

def main():
    # Create a folder for screenshots
    screenshot_folder = Path("screenshots")
    screenshot_folder.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        try:
            page = browser.new_page()

            # Open website
            page.goto("https://microsoft.com")

            print("Page title:", page.title())

            # Generate unique filename using current date and time
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
            unique_id = uuid4().hex[:8]

            screenshot_name = f"screenshot_{timestamp}_{unique_id}.png"
            screenshot_path = screenshot_folder / screenshot_name

            # Capture full-page screenshot
            page.screenshot(
                path=str(screenshot_path),
                full_page=True
            )

            print(f"Screenshot saved: {screenshot_path.resolve()}")

        finally:
            browser.close()

if __name__ == "__main__":
    main()
