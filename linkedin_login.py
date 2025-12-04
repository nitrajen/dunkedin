import os
from playwright.sync_api import sync_playwright
import time

def login_to_linkedin():
    """
    One-time login to LinkedIn to save session.
    After running this once, the session will be saved and reused.
    """

    with sync_playwright() as p:
        # Launch browser with a persistent context to save cookies/session
        browser = p.chromium.launch(
            channel="chrome",
            headless=False  # We need to see it to login manually
        )

        context = browser.new_context(
            storage_state="data/linkedin_session.json" if os.path.exists("data/linkedin_session.json") else None
        )

        page = context.new_page()

        # Go to LinkedIn
        page.goto("https://www.linkedin.com/login")

        print("\n" + "="*60)
        print("LinkedIn Login")
        print("="*60)
        print("Please log in to LinkedIn in the browser window.")
        print("Once you're logged in and see your feed, press Enter here...")
        print("="*60 + "\n")

        # Wait for user to login manually
        input("Press Enter after you've logged in successfully...")

        # Save the session state
        os.makedirs('data', exist_ok=True)
        context.storage_state(path="data/linkedin_session.json")

        print("\n✓ Session saved to data/linkedin_session.json")
        print("You can now run job_search.py without logging in again!\n")

        browser.close()

if __name__ == "__main__":
    login_to_linkedin()
