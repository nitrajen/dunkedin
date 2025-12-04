"""
Entry point for Stage 3: Execute form filling with CUA.

Usage (from project root):
    uv run gemini_playwright/run_stage3.py

This script:
1. Reads job_id from tmp/current.txt
2. Loads Stage 2 output (AnswerPlan)
3. Opens browser and navigates to job URL
4. Uses CUA to fill visible form fields
5. Monitors for submit (applied) or tab close (not_applied)
6. Updates greenhouse_collected.application_status accordingly
"""

import json
import sys
import time
from pathlib import Path

# Add parent directory to path for imports when running as script
sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright

from gemini_playwright.config import TMP_DIR, VIEWPORT_WIDTH, VIEWPORT_HEIGHT
from gemini_playwright.models import AnswerPlan
from gemini_playwright.stage3_execute import execute_form_filling
from gemini_playwright.db import update_application_status
from gemini_playwright.logger import get_logger

log = get_logger(__name__)


def monitor_for_completion(page, job_id: str, initial_url: str) -> str:
    """
    Monitor page for submit or close events.

    Handles 4 scenarios:
    1. Tab closed → 'not_applied'
    2. URL changed (navigation after submit) → 'applied'
    3. Form hidden (same-page submission) → 'applied'
    4. Success message visible (same-page submission) → 'applied'

    Returns:
        'applied' if form was submitted
        'not_applied' if tab was closed without submitting
    """
    log.info("Monitoring for submit or close...")
    log.info("  - Submit the form → status becomes 'applied'")
    log.info("  - Close the tab → status becomes 'not_applied'")

    while True:
        # Scenario 1: Check if page/browser was closed
        try:
            # This will throw if page is closed
            _ = page.url
        except Exception:
            log.info("Tab closed by user")
            return "not_applied"

        # Scenario 2: Check for URL change (navigation after submit)
        try:
            current_url = page.url
            if current_url != initial_url:
                log.info(f"URL changed: {current_url[:60]}...")
                log.info("Submit detected (navigation)!")
                return "applied"
        except Exception:
            log.info("Page closed during URL check")
            return "not_applied"

        # Scenarios 3 & 4: Check for same-page submission indicators
        try:
            submission_state = page.evaluate('''
                () => {
                    // Check if form is hidden (same page submission)
                    const form = document.querySelector('form[id*="application"]') ||
                                 document.querySelector('form:has(input[name^="job_application"])');
                    const formHidden = form && (form.style.display === 'none' ||
                                                form.classList.contains('hidden') ||
                                                form.classList.contains('application-form__form--hidden'));

                    // Check if success message is visible (greenhouse-specific)
                    const successMsg = document.querySelector('#application-form-success, .application-form__success');
                    const successVisible = successMsg && (successMsg.classList.contains('visible') ||
                                                          successMsg.classList.contains('application-form__success--visible') ||
                                                          successMsg.style.display !== 'none');

                    return {
                        formHidden: formHidden,
                        successVisible: successVisible
                    };
                }
            ''')

            if submission_state['formHidden'] or submission_state['successVisible']:
                log.info("Same-page submission detected!")
                log.info(f"  Form hidden: {submission_state['formHidden']}")
                log.info(f"  Success visible: {submission_state['successVisible']}")
                return "applied"
        except Exception:
            # Page might be closed or navigating
            pass

        # Poll every 100ms for quick response
        time.sleep(0.1)


def main():
    # 1. Read current job_id
    current_path = TMP_DIR / "current.txt"
    if not current_path.exists():
        log.error(f"No current job found. Run Stage 1 first. Missing: {current_path}")
        return

    job_id = current_path.read_text().strip()
    log.info(f"Current job ID: {job_id}")

    # 2. Load Stage 2 output
    stage2_path = TMP_DIR / f"{job_id}_stage2_output.json"
    if not stage2_path.exists():
        log.error(f"Stage 2 output not found: {stage2_path}")
        return

    with open(stage2_path) as f:
        stage2_data = json.load(f)

    job_name = stage2_data["job_name"]
    company = stage2_data["company"]
    job_link = stage2_data["job_link"]

    log.info(f"Job: {job_name} at {company}")
    log.info(f"URL: {job_link}")

    # Parse AnswerPlan
    answer_plan = AnswerPlan(**stage2_data["answer_plan"])
    log.info(f"Loaded AnswerPlan with {len(answer_plan.answers)} fields")

    # 3. Launch browser
    log.info("Launching browser...")
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(channel="chrome", headless=False)
    page = browser.new_page(viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})

    # 4. Navigate to job URL
    log.info(f"Navigating to: {job_link}")
    page.goto(job_link)
    page.wait_for_timeout(2000)

    # Scroll to form area (skip job description)
    log.info("Scrolling to form area...")
    form_input = page.query_selector("input, textarea, select")
    if form_input:
        try:
            form_input.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(500)
        except Exception as e:
            log.warning(f"Could not scroll to form (continuing anyway): {e}")

    # 5. Execute form filling
    log.info("=" * 60)
    log.info("Starting CUA form filling")
    log.info("=" * 60)

    results = execute_form_filling(page, answer_plan)

    # 6. Log summary
    log.info("=" * 60)
    log.info("CUA FORM FILLING COMPLETE")
    log.info("=" * 60)
    log.info(f"Turns: {results['turns']}")
    log.info(f"Total actions executed: {results['total_actions']}")
    log.info(f"Fields to fill: {results['fields_to_fill']}")
    log.info(f"Fields skipped: {results['fields_skipped']}")
    log.info(
        f"Tokens - Prompt: {results['token_usage']['prompt']}, "
        f"Response: {results['token_usage']['response']}, "
        f"Total: {results['token_usage']['total']}"
    )

    # 7. Save CUA output
    output_data = {
        "job_id": job_id,
        "job_name": job_name,
        "company": company,
        "job_link": job_link,
        "status": "ready_for_review",
        "results": results,
    }

    output_path = TMP_DIR / f"{job_id}_stage3_output.json"
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    log.info(f"Stage 3 output saved to {output_path}")

    # 8. Monitor for user action (submit or close)
    log.info("")
    log.info("=" * 60)
    log.info("READY FOR REVIEW")
    log.info("Review the form, fill remaining fields, upload files")
    log.info("Then SUBMIT or CLOSE the tab")
    log.info("=" * 60)

    initial_url = page.url
    final_status = monitor_for_completion(page, job_id, initial_url)

    # 9. Update database
    log.info(f"Updating application_status to '{final_status}'...")
    if update_application_status(job_id, final_status):
        log.info(f"✓ Job {job_id} marked as '{final_status}'")
    else:
        log.warning(f"Failed to update status for job {job_id}")

    # 10. Cleanup
    try:
        browser.close()
    except Exception:
        pass  # Browser might already be closed

    playwright.stop()
    log.info("Done")


if __name__ == "__main__":
    main()
