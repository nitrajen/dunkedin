"""
Combined LinkedIn job extraction script.

Extracts both:
1. Job metadata (title, company, location, description, etc.)
2. Third-party application links (for non-LinkedIn apply jobs)

Uses conservative timing to avoid LinkedIn bot detection:
- 10 parallel tabs
- 2s stagger between navigation starts
- 15s wait for page load
- 4s stagger between tab closes (~40s total)

Usage:
    uv run extract_jobs_combined.py
"""

import os
import sqlite3
import logging
import asyncio
import re
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, unquote

# Configuration
SESSION_FILE = "data/linkedin_session.json"
DB_FILE = "data/jobs.db"
MAX_JOBS = None  # Limit number of jobs to process (None = all)
PARALLEL_JOBS = 10  # Number of tabs to open in parallel
STAGGER_DELAY = 2  # Seconds between each navigation start
PAGE_LOAD_WAIT = 15  # Seconds to wait after page load
CLOSE_STAGGER_TOTAL = 40  # Total seconds distributed across tab closes

# Setup logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/extract_jobs_combined.log', mode='a'),
        logging.StreamHandler()
    ]
)

logging.info("=" * 80)
logging.info("NEW COMBINED EXTRACTION RUN STARTED")
logging.info("=" * 80)


def get_jobs_to_process():
    """Get jobs that haven't been extracted yet."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if MAX_JOBS:
        cursor.execute('''
            SELECT job_id, job_link, job_title, job_company
            FROM search_results
            WHERE extraction_status IS NULL
            ORDER BY date_of_search DESC
            LIMIT ?
        ''', (MAX_JOBS,))
    else:
        cursor.execute('''
            SELECT job_id, job_link, job_title, job_company
            FROM search_results
            WHERE extraction_status IS NULL
            ORDER BY date_of_search DESC
        ''')

    jobs = cursor.fetchall()
    conn.close()
    return jobs


def extract_final_url(linkedin_redirect_url):
    """Extract the actual destination URL from LinkedIn's redirect URL."""
    try:
        parsed = urlparse(linkedin_redirect_url)
        params = parse_qs(parsed.query)
        if 'url' in params:
            return unquote(params['url'][0])
        return None
    except Exception as e:
        logging.error(f"Error extracting URL: {e}")
        return None


def extract_job_description(html):
    """Extract job description from HTML using regex."""
    match = re.search(
        r'<h2[^>]*>About the job</h2>(.*?)(?=<h2|<div[^>]*data-test)',
        html, re.DOTALL | re.IGNORECASE
    )
    if match:
        desc_html = match.group(1)
        soup = BeautifulSoup(desc_html, 'lxml')
        return soup.get_text(separator='\n', strip=True)
    return None


def extract_job_info_from_html(html):
    """Extract all job information from HTML."""
    soup = BeautifulSoup(html, 'lxml')

    job_info = {
        'job_title': None,
        'company_name': None,
        'location': None,
        'workplace_type': None,
        'employment_type': None,
        'salary_range': None,
        'benefits': None,
        'posted_date': None,
        'num_applicants': None,
        'job_description': None,
        'seniority_level': None
    }

    try:
        # Job Title and Company - extract from <title> tag (most reliable)
        # Format: "Job Title | Company | LinkedIn"
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text(strip=True)
            if ' | ' in title_text:
                parts = title_text.split(' | ')
                job_info['job_title'] = parts[0].strip()
                if len(parts) > 1 and parts[1].strip() != 'LinkedIn':
                    job_info['company_name'] = parts[1].strip()

        # Employment Type
        employment_match = re.search(
            r'<strong>(Full-time|Part-time|Contract|Temporary|Internship)</strong>',
            html, re.IGNORECASE
        )
        if employment_match:
            job_info['employment_type'] = employment_match.group(1)

        # Salary Range
        salary_match = re.search(
            r'<strong>(\$[\d,]+\s*[–-]\s*\$[\d,]+[^<]*)</strong>',
            html, re.IGNORECASE
        )
        if salary_match:
            salary_text = salary_match.group(1)
            if '+' in salary_text:
                parts = salary_text.split('+', 1)
                job_info['salary_range'] = parts[0].strip()
                job_info['benefits'] = parts[1].strip()
            else:
                job_info['salary_range'] = salary_text

        # Posted Date
        posted_match = re.search(
            r'Posted[^<]*?(\d+\s+(?:second|minute|hour|day|week|month)s?\s+ago|on\s+[^<]+)',
            html, re.IGNORECASE
        )
        if posted_match:
            job_info['posted_date'] = posted_match.group(1).strip()

        # Number of Applicants
        applicants_match = re.search(r'(\d+)\s*applicants?', html, re.IGNORECASE)
        if applicants_match:
            job_info['num_applicants'] = applicants_match.group(1)

        # Job Description
        job_info['job_description'] = extract_job_description(html)

        # Seniority Level (inferred)
        if job_info['job_description']:
            desc_lower = job_info['job_description'].lower()
            if 'senior' in desc_lower or '7+ years' in desc_lower or '10+ years' in desc_lower:
                job_info['seniority_level'] = 'Mid-Senior level'
            elif 'entry' in desc_lower or '0-2 years' in desc_lower:
                job_info['seniority_level'] = 'Entry level'
            elif 'intern' in desc_lower:
                job_info['seniority_level'] = 'Internship'

    except Exception as e:
        logging.error(f"Error extracting info from HTML: {e}")

    return job_info


async def extract_single_job(page, job_id, job_link, job_title, job_company):
    """Extract all information from a single job page."""
    result = {
        'job_id': job_id,
        'job_link': job_link,
        'extraction_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'status': 'failed',
        'job_info': None,
        'application_link': None,
        'application_status': None,
    }

    try:
        logging.info(f"[{job_id}] Processing: {job_title} at {job_company}")

        # Navigate to job page
        await page.goto(job_link, wait_until='domcontentloaded', timeout=30000)

        # Wait for page to fully load
        await asyncio.sleep(PAGE_LOAD_WAIT)

        # Close any popups/overlays
        try:
            dismiss_btns = await page.query_selector_all(
                'button[aria-label*="Dismiss"], button[aria-label*="Close"]'
            )
            for btn in dismiss_btns:
                try:
                    if await btn.is_visible():
                        await btn.click(timeout=500)
                        await asyncio.sleep(1)
                except:
                    pass
        except:
            pass

        # Try to expand "... more" link for job description
        try:
            await page.evaluate('''
                const aboutSection = document.querySelector('h2');
                if (aboutSection && aboutSection.textContent.includes('About')) {
                    aboutSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            ''')
            await asyncio.sleep(0.5)

            clicked = await page.evaluate('''
                () => {
                    const walker = document.createTreeWalker(
                        document.body, NodeFilter.SHOW_TEXT, null, false
                    );
                    let node;
                    while (node = walker.nextNode()) {
                        const text = node.textContent.trim();
                        if ((text === 'more' || text === '…\\nmore' || text === '...\\nmore') &&
                            node.previousSibling?.textContent?.includes('…')) {
                            let parent = node.parentElement;
                            for (let i = 0; i < 5 && parent; i++) {
                                const tag = parent.tagName;
                                const role = parent.getAttribute('role');
                                const cursor = window.getComputedStyle(parent).cursor;
                                if (tag === 'A' || tag === 'BUTTON' || role === 'button' || cursor === 'pointer') {
                                    parent.click();
                                    return true;
                                }
                                parent = parent.parentElement;
                            }
                        }
                    }
                    const allElements = Array.from(document.querySelectorAll('*'));
                    for (const elem of allElements) {
                        const text = elem.textContent.trim();
                        const innerText = elem.innerText?.trim() || '';
                        if (text.includes('jobs like this') || text.includes('See more jobs') || text.includes('similar jobs')) {
                            continue;
                        }
                        if (innerText.match(/…\\s*more/i) || innerText.match(/\\.\\.\\.\\s*more/i)) {
                            const tag = elem.tagName;
                            const role = elem.getAttribute('role');
                            const cursor = window.getComputedStyle(elem).cursor;
                            if (tag === 'A' || tag === 'BUTTON' || role === 'button' || cursor === 'pointer') {
                                elem.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }
            ''')
            if clicked:
                await asyncio.sleep(2)
                logging.info(f"[{job_id}] Expanded description")
        except:
            pass

        # Get page HTML and extract job info
        html = await page.content()
        job_info = extract_job_info_from_html(html)
        result['job_info'] = job_info

        # Extract third-party application link
        apply_btn = await page.query_selector('a[data-view-name="job-apply-button"]')

        if apply_btn:
            href = await apply_btn.get_attribute('href')
            if href:
                final_url = extract_final_url(href)
                if final_url:
                    result['application_link'] = final_url
                    logging.info(f"[{job_id}] Found application link: {final_url[:60]}...")
        else:
            # Check if job is no longer accepting applications
            not_accepting = await page.query_selector('text=/no longer accepting/i')
            if not_accepting:
                result['application_status'] = 'not_accepting_or_unable_to_apply'
                logging.info(f"[{job_id}] Job no longer accepting applications")

        result['status'] = 'successful'
        logging.info(f"[{job_id}] Extraction successful")

    except Exception as e:
        logging.error(f"[{job_id}] Error: {e}")
        result['error'] = str(e)

    return result


def save_result_to_db(result):
    """Save extraction result to database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    job_id = result['job_id']

    try:
        if result['status'] == 'successful':
            job_info = result['job_info'] or {}

            # Insert into job_info_extracted
            cursor.execute('''
                INSERT OR REPLACE INTO job_info_extracted (
                    job_id, job_link, extraction_timestamp,
                    job_title, company_name, location, workplace_type,
                    employment_type, salary_range, benefits,
                    posted_date, num_applicants, job_description,
                    seniority_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job_id,
                result['job_link'],
                result['extraction_timestamp'],
                job_info.get('job_title'),
                job_info.get('company_name'),
                job_info.get('location'),
                job_info.get('workplace_type'),
                job_info.get('employment_type'),
                job_info.get('salary_range'),
                job_info.get('benefits'),
                job_info.get('posted_date'),
                job_info.get('num_applicants'),
                job_info.get('job_description'),
                job_info.get('seniority_level')
            ))

            # Update search_results
            cursor.execute('''
                UPDATE search_results
                SET extraction_status = 'successful'
                WHERE job_id = ?
            ''', (job_id,))

            # Update application link if found
            if result['application_link']:
                cursor.execute('''
                    UPDATE search_results
                    SET job_application_link = ?
                    WHERE job_id = ?
                ''', (result['application_link'], job_id))

            # Update application status if not accepting
            if result['application_status']:
                cursor.execute('''
                    UPDATE search_results
                    SET application_status = ?
                    WHERE job_id = ?
                ''', (result['application_status'], job_id))

        else:
            # Mark as failed
            cursor.execute('''
                UPDATE search_results
                SET extraction_status = 'failed'
                WHERE job_id = ?
            ''', (job_id,))

        conn.commit()

    except Exception as e:
        logging.error(f"Error saving job {job_id} to database: {e}")
    finally:
        conn.close()


async def main():
    """Main extraction function."""
    jobs = get_jobs_to_process()

    if not jobs:
        print("\n✓ No jobs to extract. All jobs have been processed.")
        logging.info("No jobs to extract")
        return

    print(f"\n{'='*60}")
    print("Combined LinkedIn Job Extraction")
    print(f"{'='*60}")
    print(f"Jobs to process: {len(jobs)}")
    print(f"Parallel tabs: {PARALLEL_JOBS}")
    print(f"Navigation stagger: {STAGGER_DELAY}s")
    print(f"Page load wait: {PAGE_LOAD_WAIT}s")
    print(f"Close stagger total: {CLOSE_STAGGER_TOTAL}s")
    print(f"{'='*60}\n")

    logging.info(f"Processing {len(jobs)} jobs")

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=False)

        if not os.path.exists(SESSION_FILE):
            print("\n⚠ No saved LinkedIn session found!")
            print("Please run: python linkedin_login.py first\n")
            await browser.close()
            return

        context = await browser.new_context(storage_state=SESSION_FILE)
        logging.info("Browser launched with saved LinkedIn session")

        total_successful = 0
        total_failed = 0

        try:
            # Process jobs in batches
            for batch_start in range(0, len(jobs), PARALLEL_JOBS):
                batch = jobs[batch_start:batch_start + PARALLEL_JOBS]
                batch_num = (batch_start // PARALLEL_JOBS) + 1
                total_batches = (len(jobs) + PARALLEL_JOBS - 1) // PARALLEL_JOBS

                print(f"\n{'#'*60}")
                print(f"# BATCH {batch_num}/{total_batches} ({len(batch)} jobs)")
                print(f"{'#'*60}\n")

                logging.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} jobs)")

                # Create all pages at once
                pages = [await context.new_page() for _ in batch]

                # Process with staggered navigation starts
                async def process_with_delay(page, job_data, delay):
                    await asyncio.sleep(delay)
                    job_id, job_link, job_title, job_company = job_data
                    return await extract_single_job(page, job_id, job_link, job_title, job_company)

                tasks = [
                    process_with_delay(page, job_data, i * STAGGER_DELAY)
                    for i, (page, job_data) in enumerate(zip(pages, batch))
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Close pages with staggered delays
                close_delay = CLOSE_STAGGER_TOTAL / len(pages)
                for page in pages:
                    await asyncio.sleep(close_delay)
                    await page.close()

                # Save results to database
                for result in results:
                    if isinstance(result, Exception):
                        logging.error(f"Exception during extraction: {result}")
                        total_failed += 1
                        continue

                    save_result_to_db(result)

                    if result['status'] == 'successful':
                        total_successful += 1
                    else:
                        total_failed += 1

                print(f"✓ Batch {batch_num} complete: {total_successful} successful, {total_failed} failed so far")

            print(f"\n\n{'='*60}")
            print("✓ ALL BATCHES COMPLETE!")
            print(f"✓ Total successful: {total_successful}")
            print(f"✗ Total failed: {total_failed}")
            print(f"{'='*60}")

            logging.info(f"Extraction complete: {total_successful} successful, {total_failed} failed")

        except Exception as e:
            print(f"✗ Error during extraction: {e}")
            logging.error(f"Error during extraction: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
