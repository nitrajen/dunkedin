"""
Database utilities for accessing greenhouse_collected jobs.
"""

import sqlite3
from dataclasses import dataclass

from gemini_playwright.config import DB_PATH


@dataclass
class GreenhouseJob:
    """A job from the greenhouse_collected table."""
    job_id: str
    job_name: str
    company: str
    description: str
    job_link: str
    application_status: str | None


def get_greenhouse_job(status: str | None = None) -> GreenhouseJob | None:
    """
    Fetch a single job from greenhouse_collected.

    Args:
        status: Filter by application_status. None means any status.
                Use "NULL" to get jobs with NULL status (not yet processed).

    Returns:
        GreenhouseJob or None if no matching job found.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if status == "NULL":
        cursor.execute(
            "SELECT job_id, job_name, company, description, job_link, application_status "
            "FROM greenhouse_collected WHERE application_status IS NULL LIMIT 1"
        )
    elif status is not None:
        cursor.execute(
            "SELECT job_id, job_name, company, description, job_link, application_status "
            "FROM greenhouse_collected WHERE application_status = ? LIMIT 1",
            (status,)
        )
    else:
        cursor.execute(
            "SELECT job_id, job_name, company, description, job_link, application_status "
            "FROM greenhouse_collected LIMIT 1"
        )

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return GreenhouseJob(
        job_id=row[0],
        job_name=row[1] or "",
        company=row[2] or "",
        description=row[3] or "",
        job_link=row[4],
        application_status=row[5]
    )


def get_greenhouse_job_by_id(job_id: str) -> GreenhouseJob | None:
    """Fetch a specific job by its ID."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT job_id, job_name, company, description, job_link, application_status "
        "FROM greenhouse_collected WHERE job_id = ?",
        (job_id,)
    )

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return GreenhouseJob(
        job_id=row[0],
        job_name=row[1] or "",
        company=row[2] or "",
        description=row[3] or "",
        job_link=row[4],
        application_status=row[5]
    )


def update_application_status(job_id: str, status: str) -> bool:
    """
    Update application_status for a job in greenhouse_collected.

    Args:
        job_id: The job ID to update.
        status: New status ('applied' or 'not_applied').

    Returns:
        True if update succeeded, False otherwise.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE greenhouse_collected SET application_status = ? WHERE job_id = ?",
        (status, job_id)
    )

    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return updated
