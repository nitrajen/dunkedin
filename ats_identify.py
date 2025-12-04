"""
ATS Identification Script

Scans job_application_link in search_results and tags jobs by ATS system.
Creates ATS-specific tables (e.g., greenhouse_collected) for each identified ATS.

Usage:
    uv run ats_identify.py
"""

import sqlite3
import logging
import os

# Configuration
DB_FILE = "data/jobs.db"

# ATS patterns to match in job_application_link
ATS_PATTERNS = {
    "greenhouse": ["greenhouse", "grnh"],
}

# Setup logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/ats_identify.log', mode='a'),
        logging.StreamHandler()
    ]
)


def create_ats_table(cursor, ats_name):
    """Create an ATS-specific collected table if it doesn't exist."""
    table_name = f"{ats_name}_collected"

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS {table_name} (
            job_id TEXT PRIMARY KEY,
            job_name TEXT,
            company TEXT,
            description TEXT,
            job_link TEXT NOT NULL,
            application_status TEXT DEFAULT NULL,
            FOREIGN KEY (job_id) REFERENCES search_results(job_id)
        )
    ''')

    logging.info(f"Ensured table '{table_name}' exists")


def identify_and_populate_ats(cursor, ats_name, patterns):
    """Identify jobs matching ATS patterns and populate the ATS table."""
    table_name = f"{ats_name}_collected"

    # Build WHERE clause for pattern matching
    pattern_conditions = " OR ".join([
        f"job_application_link LIKE '%{pattern}%'"
        for pattern in patterns
    ])

    # Select jobs that match patterns and aren't already in the table
    query = f'''
        SELECT sr.job_id, sr.job_name, sr.job_company, jie.job_description, sr.job_application_link
        FROM search_results sr
        LEFT JOIN job_info_extracted jie ON sr.job_id = jie.job_id
        WHERE ({pattern_conditions})
          AND sr.job_application_link IS NOT NULL
          AND sr.job_id NOT IN (SELECT job_id FROM {table_name})
    '''

    cursor.execute(query)
    jobs = cursor.fetchall()

    if not jobs:
        logging.info(f"No new {ats_name} jobs found")
        return 0

    # Insert into ATS table
    inserted = 0
    for job_id, job_name, company, description, job_link in jobs:
        try:
            cursor.execute(f'''
                INSERT INTO {table_name} (job_id, job_name, company, description, job_link)
                VALUES (?, ?, ?, ?, ?)
            ''', (job_id, job_name, company, description, job_link))
            inserted += 1
        except sqlite3.IntegrityError:
            pass

    logging.info(f"Inserted {inserted} jobs into {table_name}")
    return inserted


def main():
    logging.info("=" * 60)
    logging.info("ATS IDENTIFICATION RUN")
    logging.info("=" * 60)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Get total jobs with application links
    cursor.execute('''
        SELECT COUNT(*) FROM search_results
        WHERE job_application_link IS NOT NULL
    ''')
    total_with_links = cursor.fetchone()[0]
    logging.info(f"Total jobs with application links: {total_with_links}")

    total_identified = 0

    for ats_name, patterns in ATS_PATTERNS.items():
        print(f"\nProcessing {ats_name}...")
        logging.info(f"Processing ATS: {ats_name} (patterns: {patterns})")

        # Create table if needed
        create_ats_table(cursor, ats_name)
        conn.commit()

        # Identify and populate
        count = identify_and_populate_ats(cursor, ats_name, patterns)
        conn.commit()

        total_identified += count
        print(f"  -> {count} new jobs added to {ats_name}_collected")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"ATS Identification Complete")
    print(f"{'=' * 60}")
    print(f"Total jobs with links: {total_with_links}")
    print(f"Total newly identified: {total_identified}")

    # Show counts per ATS table
    print(f"\nATS Table Counts:")
    for ats_name in ATS_PATTERNS.keys():
        table_name = f"{ats_name}_collected"
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE application_status IS NULL")
        pending = cursor.fetchone()[0]

        print(f"  {table_name}: {count} total, {pending} pending")

    print(f"{'=' * 60}")

    conn.close()
    logging.info("ATS identification complete")


if __name__ == "__main__":
    main()
