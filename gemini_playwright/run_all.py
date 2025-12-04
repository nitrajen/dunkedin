"""
Continuous runner for all stages: processes all jobs in greenhouse_collected.

Usage (from project root):
    uv run gemini_playwright/run_all.py

This script:
1. Loops through all jobs with NULL application_status
2. Runs Stage 1 → Stage 2 → Stage 3 for each job
3. Continues until no more jobs remain
4. Handles errors gracefully (marks failed jobs, continues to next)
"""

import json
import sys
import time
from pathlib import Path

# Add parent directory to path for imports when running as script
sys.path.insert(0, str(Path(__file__).parent.parent))

from gemini_playwright.config import TMP_DIR, CANDIDATE_PROFILE_PATH, EXPERIENCE_INFO_PATH
from gemini_playwright.db import get_greenhouse_job, update_application_status
from gemini_playwright.browser import BrowserSession
from gemini_playwright.stage1_extract_schema import extract_form_schema
from gemini_playwright.stage2_answer_plan import generate_answer_plan
from gemini_playwright.stage3_execute import execute_form_filling
from gemini_playwright.models import FormSchema, AnswerPlan
from gemini_playwright.logger import get_logger


log = get_logger(__name__)

# Configuration
MAX_JOBS = 2  # Limit number of jobs to process (None = unlimited)


MONITOR_TIMEOUT_SECONDS = 300  # 5 minute timeout for user review


def monitor_for_completion(page, session, initial_url: str, timeout: int = MONITOR_TIMEOUT_SECONDS) -> str:
    """Monitor page for submit or close events. Returns status after detection or timeout."""
    start_time = time.time()
    browser = session.browser

    while True:
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > timeout:
            log.warning(f"Monitor timeout after {timeout}s - assuming not applied")
            return "not_applied"

        # Check if page is closed
        if page.is_closed():
            log.info("Page closed detected via is_closed()")
            return "not_applied"

        # Check if browser is still connected
        if not browser.is_connected():
            log.info("Browser disconnected detected")
            return "not_applied"

        try:
            current_url = page.url
            if current_url != initial_url:
                log.info(f"URL changed - submit detected")
                return "applied"
        except Exception:
            log.info("Page access failed - assuming closed")
            return "not_applied"

        try:
            submission_state = page.evaluate('''
                () => {
                    const form = document.querySelector('form[id*="application"]') ||
                                 document.querySelector('form:has(input[name^="job_application"])');
                    const formHidden = form && (form.style.display === 'none' ||
                                                form.classList.contains('hidden') ||
                                                form.classList.contains('application-form__form--hidden'));
                    const successMsg = document.querySelector('#application-form-success, .application-form__success');
                    const successVisible = successMsg && (successMsg.classList.contains('visible') ||
                                                          successMsg.classList.contains('application-form__success--visible') ||
                                                          successMsg.style.display !== 'none');
                    return { formHidden, successVisible };
                }
            ''')
            if submission_state['formHidden'] or submission_state['successVisible']:
                log.info("Same-page submission detected")
                return "applied"
        except Exception:
            pass

        time.sleep(0.1)


def run_stage1(job, session: BrowserSession) -> dict | None:
    """Run Stage 1: Extract form schema using existing browser session."""
    log.info(f"[Stage 1] Navigating to job page...")
    session.navigate(job.job_link)

    log.info(f"[Stage 1] Scrolling to form...")
    try:
        session.scroll_to_form()
    except Exception as e:
        log.warning(f"[Stage 1] Could not scroll to form: {e}")

    log.info(f"[Stage 1] Capturing screenshots...")
    screenshots = session.capture_screenshots()
    session.save_screenshots(screenshots)
    log.info(f"[Stage 1] Captured {len(screenshots)} screenshots")

    log.info(f"[Stage 1] Extracting form schema...")
    form_schema, token_usage = extract_form_schema(screenshots)
    log.info(f"[Stage 1] Extracted {len(form_schema.fields)} fields")

    output_data = {
        "job_id": job.job_id,
        "job_name": job.job_name,
        "company": job.company,
        "job_link": job.job_link,
        "form_schema": form_schema.model_dump(),
        "token_usage": token_usage,
    }

    output_path = TMP_DIR / f"{job.job_id}_stage1_output.json"
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    return output_data


def run_stage2(stage1_data: dict) -> dict | None:
    """Run Stage 2: Generate answer plan."""
    form_schema = FormSchema(**stage1_data["form_schema"])

    with open(CANDIDATE_PROFILE_PATH) as f:
        candidate_profile = json.load(f)

    experience_info = EXPERIENCE_INFO_PATH.read_text()

    log.info(f"[Stage 2] Generating answer plan...")
    answer_plan, token_usage = generate_answer_plan(
        form_schema=form_schema,
        candidate_profile=candidate_profile,
        experience_info=experience_info,
    )
    log.info(f"[Stage 2] Generated {len(answer_plan.answers)} answers")

    output_data = {
        "job_id": stage1_data["job_id"],
        "job_name": stage1_data["job_name"],
        "company": stage1_data["company"],
        "job_link": stage1_data["job_link"],
        "answer_plan": answer_plan.model_dump(),
        "token_usage": token_usage,
    }

    output_path = TMP_DIR / f"{stage1_data['job_id']}_stage2_output.json"
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    return output_data


def run_stage3(stage2_data: dict, session: BrowserSession) -> str:
    """Run Stage 3: Execute form filling and monitor for completion. Returns status."""
    job_id = stage2_data["job_id"]
    job_link = stage2_data["job_link"]
    answer_plan = AnswerPlan(**stage2_data["answer_plan"])
    page = session.page

    # Scroll back to top of form for CUA
    log.info(f"[Stage 3] Scrolling to form start...")
    try:
        # First scroll to absolute top
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        # Then scroll to form
        result = session.scroll_to_form()
        scroll_pos = page.evaluate("window.scrollY")
        log.info(f"[Stage 3] Scroll result: {result}, position: {scroll_pos}px")
    except Exception as e:
        log.error(f"[Stage 3] Scroll failed: {e}")

    log.info(f"[Stage 3] Executing form filling...")
    results = execute_form_filling(page, answer_plan)

    log.info(f"[Stage 3] Completed: {results['total_actions']} actions, {results['turns']} turns")

    # Save stage 3 output
    output_data = {
        "job_id": job_id,
        "job_name": stage2_data["job_name"],
        "company": stage2_data["company"],
        "job_link": job_link,
        "status": "ready_for_review",
        "results": results,
    }
    output_path = TMP_DIR / f"{job_id}_stage3_output.json"
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    # Monitor for user action
    log.info("")
    log.info("=" * 60)
    log.info("READY FOR REVIEW - Submit or Close the tab")
    log.info("=" * 60)

    initial_url = page.url
    final_status = monitor_for_completion(page, session, initial_url)

    return final_status


def process_job(job) -> str:
    """Process a single job through all stages. Returns status: 'applied', 'not_applied', or 'failed'."""
    job_id = job.job_id
    log.info("")
    log.info("=" * 70)
    log.info(f"PROCESSING: {job.job_name} at {job.company}")
    log.info(f"Job ID: {job_id}")
    log.info("=" * 70)

    try:
        # Single browser session for all stages
        with BrowserSession(headless=False) as session:
            # Stage 1
            stage1_data = run_stage1(job, session)
            if not stage1_data:
                raise Exception("Stage 1 failed")

            # Stage 2 (no browser needed)
            stage2_data = run_stage2(stage1_data)
            if not stage2_data:
                raise Exception("Stage 2 failed")

            # Stage 3 (reuses same browser)
            final_status = run_stage3(stage2_data, session)

        # Update database
        update_application_status(job_id, final_status)
        log.info(f"Job {job_id} marked as '{final_status}'")

        return final_status

    except Exception as e:
        log.error(f"Error processing job {job_id}: {e}")
        # Mark as failed so we don't retry indefinitely
        update_application_status(job_id, "failed")
        log.warning(f"Job {job_id} marked as 'failed'")
        return "failed"


def main():
    log.info("=" * 70)
    log.info("CONTINUOUS JOB APPLICATION RUNNER")
    log.info(f"Max jobs: {MAX_JOBS if MAX_JOBS else 'unlimited'}")
    log.info("=" * 70)

    processed = 0
    applied = 0
    not_applied = 0
    failed = 0

    while True:
        # Check if we've hit the limit
        if MAX_JOBS and processed >= MAX_JOBS:
            log.info("")
            log.info("=" * 70)
            log.info(f"REACHED MAX JOBS LIMIT ({MAX_JOBS})")
            log.info(f"Total: {processed}, Applied: {applied}, Not Applied: {not_applied}, Failed: {failed}")
            log.info("=" * 70)
            break

        # Get next job with NULL status
        job = get_greenhouse_job(status="NULL")

        if job is None:
            log.info("")
            log.info("=" * 70)
            log.info("ALL JOBS PROCESSED")
            log.info(f"Total: {processed}, Applied: {applied}, Not Applied: {not_applied}, Failed: {failed}")
            log.info("=" * 70)
            break

        status = process_job(job)
        processed += 1

        if status == "applied":
            applied += 1
        elif status == "not_applied":
            not_applied += 1
        else:  # "failed"
            failed += 1

        log.info(f"Progress: {processed}/{MAX_JOBS if MAX_JOBS else '∞'} - {applied} applied, {not_applied} skipped, {failed} failed")
        log.info("")

    log.info("Done!")


if __name__ == "__main__":
    main()
