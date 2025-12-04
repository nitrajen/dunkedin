"""
Entry point for Stage 2: Generate AnswerPlan from FormSchema + CandidateProfile.

Usage (from project root):
    uv run gemini_playwright/run_stage2.py

This script:
1. Reads job_id from tmp/current.txt
2. Loads Stage 1 output from tmp/{job_id}_stage1_output.json
3. Loads candidate_profile.json and experience_info.txt
4. Generates AnswerPlan with Gemini Flash-Lite
5. Persists output to tmp/{job_id}_stage2_output.json
"""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports when running as script
sys.path.insert(0, str(Path(__file__).parent.parent))

from gemini_playwright.config import (
    TMP_DIR,
    CANDIDATE_PROFILE_PATH,
    EXPERIENCE_INFO_PATH,
)
from gemini_playwright.models import FormSchema
from gemini_playwright.stage2_answer_plan import generate_answer_plan
from gemini_playwright.logger import get_logger

log = get_logger(__name__)


def main():
    # 1. Read current job_id from tmp/current.txt
    current_path = TMP_DIR / "current.txt"
    if not current_path.exists():
        log.error(f"No current job found. Run Stage 1 first. Missing: {current_path}")
        return

    job_id = current_path.read_text().strip()
    log.info(f"Current job ID: {job_id}")

    # 2. Load Stage 1 output
    stage1_path = TMP_DIR / f"{job_id}_stage1_output.json"
    if not stage1_path.exists():
        log.error(f"Stage 1 output not found: {stage1_path}")
        return

    with open(stage1_path) as f:
        stage1_data = json.load(f)

    log.info(f"Job: {stage1_data['job_name']} at {stage1_data['company']}")
    log.debug(f"Job URL: {stage1_data['job_link']}")

    # Parse FormSchema from stage1 output
    form_schema = FormSchema(**stage1_data["form_schema"])
    log.info(f"Loaded FormSchema with {len(form_schema.fields)} fields")

    # 3. Load candidate profile and experience info
    if not CANDIDATE_PROFILE_PATH.exists():
        log.error(f"Candidate profile not found: {CANDIDATE_PROFILE_PATH}")
        return

    with open(CANDIDATE_PROFILE_PATH) as f:
        candidate_profile = json.load(f)
    log.info("Loaded candidate profile")

    if not EXPERIENCE_INFO_PATH.exists():
        log.error(f"Experience info not found: {EXPERIENCE_INFO_PATH}")
        return

    experience_info = EXPERIENCE_INFO_PATH.read_text()
    log.info("Loaded experience info")

    # 4. Generate answer plan
    log.info("Generating answer plan with Gemini Flash-Lite...")
    answer_plan, token_usage = generate_answer_plan(
        form_schema=form_schema,
        candidate_profile=candidate_profile,
        experience_info=experience_info,
    )

    # 5. Log results
    log.info(f"Generated {len(answer_plan.answers)} planned answers")

    # Count actions by type
    action_counts = {}
    for answer in answer_plan.answers:
        action = answer.action.value
        action_counts[action] = action_counts.get(action, 0) + 1
    log.info(f"Actions: {action_counts}")

    log.info(
        f"Token usage - Prompt: {token_usage['prompt_tokens']}, "
        f"Response: {token_usage['response_tokens']}, "
        f"Total: {token_usage['total_tokens']}"
    )

    # 6. Save output to tmp/{job_id}_stage2_output.json
    output_data = {
        "job_id": job_id,
        "job_name": stage1_data["job_name"],
        "company": stage1_data["company"],
        "job_link": stage1_data["job_link"],
        "answer_plan": answer_plan.model_dump(),
        "token_usage": token_usage,
    }

    output_path = TMP_DIR / f"{job_id}_stage2_output.json"
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    log.info(f"Stage 2 output saved to {output_path}")


if __name__ == "__main__":
    main()
