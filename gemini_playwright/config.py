"""
Configuration constants for Gemini Playwright job application automation.

Note: All scripts should be run from project root: uv run gemini_playwright/script.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Paths (relative to project root where scripts are executed)
DB_PATH = Path("data/jobs.db")
SCREENSHOTS_DIR = Path("gemini_playwright/screenshots")
CANDIDATE_PROFILE_PATH = Path("gemini_playwright/candidate_profile.json")
EXPERIENCE_INFO_PATH = Path("gemini_playwright/experience_info.txt")
PROMPTS_DIR = Path("gemini_playwright/docs")
TMP_DIR = Path("gemini_playwright/tmp")

# Ensure directories exist
SCREENSHOTS_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)

# Gemini API
GEMINI_API_KEY = os.environ.get("gemini_api_key", "")
MODEL_FLASH_LITE = "gemini-2.5-flash-lite"
MODEL_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"

# Browser settings
VIEWPORT_WIDTH = 960
VIEWPORT_HEIGHT = 1000
