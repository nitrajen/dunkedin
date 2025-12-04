"""
Playwright browser utilities for capturing form screenshots.

Screenshots are captured by scrolling 80% of viewport height at a time,
ensuring 20% overlap between consecutive screenshots. Deduplication of
fields across screenshots is handled by the Gemini Flash-Lite model.
"""

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright, Browser, Page

from gemini_playwright.config import VIEWPORT_WIDTH, VIEWPORT_HEIGHT, SCREENSHOTS_DIR
from gemini_playwright.logger import get_logger

log = get_logger(__name__)

SCROLL_PERCENTAGE = 0.8  # Scroll 80% of viewport per step (20% overlap)
MAX_SCREENSHOTS = 3  # Limit screenshots to reduce API costs


class BrowserSession:
    """Manages a Playwright browser session for form screenshot capture."""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.playwright = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            channel="chrome",  # Use installed Chrome, not bundled Chromium
            headless=self.headless
        )
        self.page = self.browser.new_page(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Handle cleanup gracefully even if browser was already closed by user
        try:
            if self.browser:
                self.browser.close()
        except Exception as e:
            log.debug(f"Browser already closed: {e}")

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            log.debug(f"Playwright stop error: {e}")

    def navigate(self, url: str, wait_until: str = "networkidle") -> None:
        """Navigate to URL and wait for page to load."""
        self.page.goto(url, wait_until=wait_until)

    def _find_form(self):
        """Try to find the application form using common Greenhouse patterns."""
        form = self.page.query_selector('form[id*="application"]')
        if not form:
            form = self.page.query_selector('form:has(input[name^="job_application"])')
        return form

    def scroll_to_form(self) -> bool:
        """
        Find the application form and scroll to its first input field.

        If no form is found, looks for an "Apply" button and clicks it,
        then tries to find the form again.

        This skips the job description section at the top of the page,
        reducing the number of screenshots needed.

        Returns:
            True if form was found and scrolled to, False otherwise.
        """
        form = self._find_form()

        # If no form, try clicking an Apply button
        if not form:
            apply_btn = self.page.query_selector(
                'button:has-text("Apply"), a:has-text("Apply")'
            )
            if apply_btn:
                btn_text = apply_btn.inner_text()
                # Click only if it's an apply button, not a submit button
                if "apply" in btn_text.lower() and "submit" not in btn_text.lower():
                    log.debug(f"Clicking Apply button: {btn_text}")
                    apply_btn.click()
                    self.page.wait_for_timeout(3000)
                    # Try finding form again
                    form = self._find_form()

        if not form:
            log.warning("No application form found, will screenshot entire page")
            return False

        # Find first input field in the form and scroll to it
        first_input = form.query_selector(
            'input[type="text"], input[type="email"], input[type="tel"], textarea'
        )
        target_element = first_input if first_input else form

        # Always scroll to position element at top of viewport (with 50px padding)
        self.page.evaluate('''(element) => {
            const rect = element.getBoundingClientRect();
            const scrollTop = window.scrollY + rect.top - 50;
            window.scrollTo({ top: Math.max(0, scrollTop), behavior: 'instant' });
        }''', target_element)
        self.page.wait_for_timeout(500)
        log.debug("Scrolled to top of form")
        return True

    def capture_screenshots(self) -> list[Image.Image]:
        """
        Capture screenshots from current position to end of page.

        Scrolls 80% of viewport each step, starting from the current scroll
        position (e.g., after scroll_to_form() has positioned at the form).

        Returns:
            List of PIL Image objects covering the page from current position.
        """
        screenshots = []
        scroll_step = int(VIEWPORT_HEIGHT * SCROLL_PERCENTAGE)

        # Get total page height
        page_height = self.page.evaluate("document.body.scrollHeight")

        # Start from current scroll position (don't reset to top)
        current_scroll = self.page.evaluate("window.scrollY")

        while True:
            # Capture current viewport
            screenshot_bytes = self.page.screenshot()
            image = Image.open(io.BytesIO(screenshot_bytes))
            screenshots.append(image)

            # Stop if we've hit the max screenshot limit
            if len(screenshots) >= MAX_SCREENSHOTS:
                log.info(f"Reached max screenshots ({MAX_SCREENSHOTS})")
                break

            # Check if we can scroll further
            next_scroll = current_scroll + scroll_step
            max_scroll = page_height - VIEWPORT_HEIGHT

            if current_scroll >= max_scroll:
                break

            # Scroll down
            current_scroll = min(next_scroll, max_scroll)
            self.page.evaluate(f"window.scrollTo(0, {current_scroll})")
            self.page.wait_for_timeout(300)

        return screenshots

    def save_screenshots(
        self, screenshots: list[Image.Image], prefix: str = "form"
    ) -> list[Path]:
        """Save screenshots to disk for debugging."""
        saved_paths = []
        for i, img in enumerate(screenshots):
            path = SCREENSHOTS_DIR / f"{prefix}_{i + 1}.png"
            img.save(path)
            saved_paths.append(path)
        return saved_paths


def capture_form_screenshots(
    url: str, headless: bool = False, save: bool = True
) -> list[Image.Image]:
    """
    Capture all screenshots from a form URL.

    Automatically scrolls to the application form to skip job description,
    then captures screenshots by scrolling 80% of viewport at a time.

    Args:
        url: The job application form URL.
        headless: Run browser in headless mode.
        save: Save screenshots to disk for debugging.

    Returns:
        List of PIL Image objects.
    """
    with BrowserSession(headless=headless) as session:
        session.navigate(url)
        session.scroll_to_form()  # Skip job description, go to form
        screenshots = session.capture_screenshots()

        if save:
            session.save_screenshots(screenshots)

        return screenshots
