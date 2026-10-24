from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        page = browser.new_page()

        page.goto("https://example.com")

        print("Page title:", page.title())

        page.screenshot(path="example.png")

        print("Screenshot saved successfully!")

        browser.close()

if __name__ == "__main__":
    main()
