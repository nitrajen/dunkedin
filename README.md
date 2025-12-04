# dunkedin

LinkedIn job search and application pre-filling using playwright and gemini flash-lite and CUA (preview model).  

After pre-filling each application form, you would either submit (status tracked as `applied`) or close the tab without submitting (status tracked as `not_applied`).
After one form is done, the next form opens and the cycle continues for job links parsed from linkedin.

You would see configurable variables (like number of tabs to open in parallel) at the top of scripts listed below to run.

## Setup

Requires Chrome installed. Playwright uses your system Chrome browser.

```bash
uv sync
cp .env.example .env  # Add your Gemini API key
cp gemini_playwright/candidate_profile.example.json gemini_playwright/candidate_profile.json
cp gemini_playwright/experience_info.example.txt gemini_playwright/experience_info.txt
```

## Running

```bash
# 1. Login to LinkedIn (saves session for reuse)
uv run linkedin_login.py

# 2. Setup database tables
uv run db_setup.py

# 3. Search jobs on LinkedIn (saves to search_results table)
uv run job_search.py

# 4. Extract job metadata and apply links (saves to job_info_extracted)
uv run extract_jobs_combined.py

# 5. Identify ATS systems and create a table each for a each ATS system of interest.
uv run ats_identify.py

# 6. Run form filling automation (Gemini Flash lite and CUA)
uv run gemini_playwright/run_all.py
```

## Database Tables

| Table | Description |
|-------|-------------|
| `search_results` | Raw job listings from LinkedIn search |
| `job_info_extracted` | Jobs with extracted metadata (description, apply links) |
| `{ats}_collected` | ATS-specific tables (e.g., `greenhouse_collected`) with `application_status` |
