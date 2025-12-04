import sqlite3
import os

def create_database():
    """Create the SQLite database with three tables:
    1. search_results - for data from search page
    2. job_info_extracted - for data from individual job pages
    3. linkedin_apply_which_jobs - for application review/selection
    """
    # Create data directory if it doesn't exist
    os.makedirs('data', exist_ok=True)

    conn = sqlite3.connect('data/jobs.db')
    cursor = conn.cursor()

    # Table 1: Search results (from search page list)
    # job_id is PRIMARY KEY to prevent duplicates automatically
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS search_results (
        job_id TEXT PRIMARY KEY,
        search_term TEXT NOT NULL,
        search_geo_id TEXT,
        search_time_filtered TEXT,
        date_of_search TEXT NOT NULL,
        search_page_number INTEGER NOT NULL,
        job_link TEXT NOT NULL,
        job_name TEXT,
        job_title TEXT,
        job_company TEXT,
        promoted_or_not TEXT,
        application_type TEXT,
        extraction_status TEXT,
        application_status TEXT,
        job_application_link TEXT
    )
    ''')

    # Table 2: Individual job details (from individual job pages)
    # Only job_id and job_link are required - other fields are nice-to-have
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS job_info_extracted (
        job_id TEXT PRIMARY KEY,
        job_link TEXT NOT NULL,
        extraction_timestamp TEXT NOT NULL,
        job_title TEXT,
        company_name TEXT,
        location TEXT,
        workplace_type TEXT,
        employment_type TEXT,
        salary_range TEXT,
        benefits TEXT,
        posted_date TEXT,
        num_applicants TEXT,
        job_description TEXT,
        seniority_level TEXT,
        FOREIGN KEY (job_id) REFERENCES search_results(job_id)
    )
    ''')

    # Table 3: LinkedIn application review/selection (truncated each collection run)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS linkedin_apply_which_jobs (
        job_id TEXT PRIMARY KEY,
        job_name TEXT,
        company TEXT,
        description TEXT,
        apply INTEGER,
        FOREIGN KEY (job_id) REFERENCES search_results(job_id)
    )
    ''')

    # Table 4: LinkedIn questions and answers
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS linkedin_questions_answers (
        question TEXT PRIMARY KEY,
        answer TEXT NOT NULL,
        input_type TEXT NOT NULL,
        comments TEXT,
        approval_status TEXT DEFAULT 'unapproved',
        CHECK (approval_status IN ('approved', 'unapproved'))
    )
    ''')

    # Table 5: Jobs where question extraction failed (truncated each collection run)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS linkedin_unable_to_get_q (
        job_id TEXT PRIMARY KEY,
        job_name TEXT,
        company TEXT,
        description TEXT,
        job_link TEXT NOT NULL,
        manual_apply INTEGER DEFAULT NULL,
        FOREIGN KEY (job_id) REFERENCES search_results(job_id)
    )
    ''')

    conn.commit()
    conn.close()
    print("✓ Database created successfully at: data/jobs.db")
    print("  Tables created:")
    print("    1. search_results - job_id as PRIMARY KEY (prevents duplicates)")
    print("    2. job_info_extracted - for individual job page data")
    print("    3. linkedin_apply_which_jobs - for application review/selection")
    print("    4. linkedin_questions_answers - for questions/answers with approval status")
    print("    5. linkedin_unable_to_get_q - for jobs where extraction failed (manual review)")

if __name__ == "__main__":
    create_database()
