"""
Entry point for Stage 1: Extract FormSchema from a Greenhouse job application.

Usage (from project root):
    uv run gemini_playwright/run_stage1.py

This script:
1. Fetches a job from greenhouse_collected table
2. Opens the job URL in a browser
3. Captures screenshots by scrolling
4. Sends screenshots to Gemini Flash-Lite
5. Persists output to tmp/{job_id}_stage1_output.json
6. Writes job_id to tmp/current.txt for subsequent stages
"""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports when running as script
sys.path.insert(0, str(Path(__file__).parent.parent))

from gemini_playwright.config import TMP_DIR
from gemini_playwright.db import get_greenhouse_job
from gemini_playwright.browser import capture_form_screenshots
from gemini_playwright.stage1_extract_schema import extract_form_schema
from gemini_playwright.logger import get_logger

log = get_logger(__name__)


def main():
    # 1. Get a job with NULL application_status (not yet processed)
    log.info("Fetching job from greenhouse_collected (status=NULL)...")
    job = get_greenhouse_job(status="NULL")

    if job is None:
        log.error("No jobs found in greenhouse_collected table.")
        return

    log.info(f"Job ID: {job.job_id}")
    log.info(f"Job: {job.job_name} at {job.company}")
    log.debug(f"Job URL: {job.job_link}")

    # 2. Capture screenshots
    log.info("Capturing screenshots...")
    screenshots = capture_form_screenshots(job.job_link, headless=False, save=True)
    log.info(f"Captured {len(screenshots)} screenshots")

    # 3. Extract form schema
    log.info("Extracting form schema with Gemini Flash-Lite...")
    form_schema, token_usage = extract_form_schema(screenshots)

    # 4. Log results
    log.info(f"Extracted {len(form_schema.fields)} form fields")
    log.info(
        f"Token usage - Prompt: {token_usage['prompt_tokens']}, "
        f"Response: {token_usage['response_tokens']}, "
        f"Total: {token_usage['total_tokens']}"
    )

    # 5. Save output to tmp/{job_id}_stage1_output.json
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
    log.info(f"Stage 1 output saved to {output_path}")

    # 6. Write current job_id to tmp/current.txt
    current_path = TMP_DIR / "current.txt"
    with open(current_path, "w") as f:
        f.write(job.job_id)
    log.info(f"Current job ID written to {current_path}")


if __name__ == "__main__":
    main()
