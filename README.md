# dunkedin

LinkedIn job search and automated application filling using Gemini CUA.

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

# 3. Search jobs on LinkedIn (saves to jobs table)
uv run job_search.py

# 4. Extract job metadata and apply links
uv run extract_jobs_combined.py

# 5. Identify ATS systems and create greenhouse_collected table
uv run ats_identify.py

# 6. Run form filling automation (Gemini CUA)
uv run gemini_playwright/run_all.py
```

## Database Tables

| Table | Description |
|-------|-------------|
| `search_results` | Raw job listings from LinkedIn search |
| `job_info_extracted` | Jobs with extracted metadata (description, apply links) |
| `{ats}_collected` | ATS-specific tables (e.g., `greenhouse_collected`) with `application_status` |
