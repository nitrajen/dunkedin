import os
import sqlite3
import logging
import random
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re

# Configuration
SESSION_FILE = "data/linkedin_session.json"

# Setup logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/job_search.log', mode='a'),
        logging.StreamHandler()
    ]
)

# Add separator for each run
logging.info("=" * 80)
logging.info("NEW RUN STARTED")
logging.info("=" * 80)

def extract_search_params(url):
    """Extract search parameters from LinkedIn search URL"""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    return {
        'search_term': params.get('keywords', [''])[0],
        'search_geo_id': params.get('geoId', [''])[0],
        'search_time_filtered': params.get('f_TPR', [''])[0]
    }

def extract_jobs_with_bs4(page_html, page_number=1):
    """Extract job listings from HTML using BeautifulSoup

    Returns: (jobs_list, elements_found_count)
    """

    # Save HTML for debugging (first page only)
    if page_number == 1:
        os.makedirs('logs', exist_ok=True)
        with open(f'logs/sample_job_list.html', 'w', encoding='utf-8') as f:
            f.write(page_html[:100000])

    try:
        soup = BeautifulSoup(page_html, 'lxml')

        # Find all job listing <li> elements
        job_elements = soup.find_all('li', attrs={'data-occludable-job-id': True})
        elements_found = len(job_elements)

        jobs = []
        empty_placeholders = 0
        parsing_errors = 0

        for idx, job_elem in enumerate(job_elements):
            try:
                # Extract job_id from data attribute
                job_id = job_elem.get('data-occludable-job-id', '').strip()
                if not job_id:
                    continue

                # Check if this is an empty placeholder (lazy loading)
                is_placeholder = 'jobs-search-results__job-card-search--generic-occludable-area' in job_elem.get('class', [])

                # Find job title link
                title_link = job_elem.find('a', class_=lambda x: x and 'job-card-list__title' in x)
                if not title_link:
                    if is_placeholder:
                        empty_placeholders += 1
                    else:
                        parsing_errors += 1
                    continue

                # Extract href and construct job_link
                href = title_link.get('href', '')
                if href.startswith('/'):
                    job_link = f"https://www.linkedin.com{href}"
                else:
                    job_link = href

                # Clean up job_link to only include up to job ID
                # Format: https://www.linkedin.com/jobs/view/JOBID/
                match = re.search(r'(https://www\.linkedin\.com/jobs/view/\d+/)', job_link)
                if match:
                    job_link = match.group(1)
                else:
                    # Fallback: construct from job_id
                    job_link = f"https://www.linkedin.com/jobs/view/{job_id}/"

                # Extract job title
                title_strong = title_link.find('strong')
                if title_strong:
                    job_title = title_strong.get_text(strip=True)
                else:
                    job_title = title_link.get_text(strip=True)

                # Extract company name (from subtitle)
                subtitle = job_elem.find('div', class_=lambda x: x and 'artdeco-entity-lockup__subtitle' in x)
                if subtitle:
                    job_company = subtitle.get_text(strip=True)
                else:
                    job_company = ""

                # Check if promoted
                promoted_or_not = "Not Promoted"
                if job_elem.find(string=re.compile(r'\s*Promoted\s*', re.IGNORECASE)):
                    promoted_or_not = "Promoted"

                # Check if Easy Apply
                application_type = None
                if job_elem.find(string=re.compile(r'\s*Easy Apply\s*', re.IGNORECASE)):
                    application_type = "linkedin"

                jobs.append({
                    'job_id': job_id,
                    'job_link': job_link,
                    'job_name': job_title,
                    'job_title': job_title,
                    'job_company': job_company,
                    'promoted_or_not': promoted_or_not,
                    'application_type': application_type
                })

            except Exception as e:
                print(f"   ⚠ Error parsing job element: {e}")
                parsing_errors += 1
                continue

        return jobs, elements_found, empty_placeholders, parsing_errors

    except Exception as e:
        print(f"   ✗ Error with parsing: {e}")
        import traceback
        traceback.print_exc()
        return [], 0, 0, 0

def save_to_database(jobs, search_params, date_of_search, page_number, elements_found=0, empty_placeholders=0, parsing_errors=0):
    """Save extracted job listings to database"""
    conn = sqlite3.connect('data/jobs.db')
    cursor = conn.cursor()

    saved_count = 0
    duplicate_count = 0
    skipped_count = 0

    for job in jobs:
        # Skip jobs without a valid job_id
        job_id = job.get('job_id', '').strip()
        if not job_id:
            skipped_count += 1
            continue

        try:
            cursor.execute('''
            INSERT INTO search_results (
                job_id, search_term, search_geo_id, search_time_filtered,
                date_of_search, search_page_number,
                job_link, job_name, job_title, job_company, promoted_or_not, application_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job_id,
                search_params['search_term'],
                search_params['search_geo_id'],
                search_params['search_time_filtered'],
                date_of_search,
                page_number,
                job.get('job_link', ''),
                job.get('job_name', ''),
                job.get('job_title', ''),
                job.get('job_company', ''),
                job.get('promoted_or_not', 'Not Promoted'),
                job.get('application_type', None)
            ))
            saved_count += 1
        except sqlite3.IntegrityError as e:
            # Duplicate job_id (PRIMARY KEY constraint)
            duplicate_count += 1
            continue
        except Exception as e:
            logging.error(f"Error saving job {job_id}: {e}")
            continue

    conn.commit()
    conn.close()

    # Log the results
    total_jobs = len(jobs)
    search_info = (
        f"Page {page_number} - Search: '{search_params['search_term']}' | "
        f"Geo ID: {search_params['search_geo_id']} | "
        f"Time filter: {search_params['search_time_filtered']}"
    )
    job_stats = (
        f"HTML elements: {elements_found} | Parsed: {total_jobs} | "
        f"Empty placeholders: {empty_placeholders} | Parse errors: {parsing_errors} | "
        f"Inserted: {saved_count} | Duplicates: {duplicate_count}"
    )
    logging.info(f"{search_info} - {job_stats}")

    # Alert if we have actual parsing errors (not just empty placeholders)
    if parsing_errors > 0:
        logging.warning(
            f"⚠ {parsing_errors} real parsing errors on page {page_number} "
            f"(not lazy-load placeholders)"
        )

    return saved_count, duplicate_count

def process_search(search_url, max_jobs, context):
    """Process a single search URL"""

    search_params = extract_search_params(search_url)
    date_of_search = datetime.now().strftime('%Y-%m-%d')

    print(f"\n{'='*60}")
    print(f"Processing Search: {search_params['search_term']}")
    print(f"{'='*60}")
    print(f"Geo ID: {search_params['search_geo_id']}")
    print(f"Time filter: {search_params['search_time_filtered']}")
    print(f"Max jobs: {max_jobs if max_jobs else 'Unlimited'}")
    print(f"{'='*60}\n")

    max_jobs_str = max_jobs if max_jobs else 'Unlimited'
    logging.info("-" * 80)
    logging.info(
        f"Starting search: '{search_params['search_term']}' | "
        f"Geo ID: {search_params['search_geo_id']} | "
        f"Time filter: {search_params['search_time_filtered']} | "
        f"Max jobs: {max_jobs_str}"
    )

    page = context.new_page()

    try:
        total_jobs_extracted = 0
        start_offset = 0
        page_number = 1

        while True:
            print(f"Page {page_number}...", end=" ", flush=True)

            try:
                # Construct URL with current offset
                base_url = search_url.split('&start=')[0] if '&start=' in search_url else search_url
                page_url = f"{base_url}&start={start_offset}"

                # Navigate to the search page
                page.goto(page_url, wait_until='domcontentloaded', timeout=30000)

                # Wait for job listings container
                page.wait_for_selector('ul', timeout=10000)

                # Additional wait after page load to let initial content populate
                page.wait_for_timeout(4000)
            except Exception as e:
                logging.error(f"Error loading page {page_number}: {e}")
                print(f"✗ Error loading page: {e}")
                break

            # Scroll and wait for DOM elements to be populated with content
            # LinkedIn adds elements AND populates them as you scroll
            max_scrolls = 20
            scroll_wait_min = 5000  # 5-7 seconds after each scroll (randomized)
            scroll_wait_max = 7000

            for scroll_iteration in range(max_scrolls):
                # Small delay before starting scroll iteration
                page.wait_for_timeout(500)

                # Count populated elements before scroll (elements with actual content)
                counts_before = page.evaluate('''
                    const total = document.querySelectorAll('li[data-occludable-job-id]').length;
                    const empty = document.querySelectorAll('li.jobs-search-results__job-card-search--generic-occludable-area').length;
                    const populated = total - empty;
                    ({total, populated, empty})
                ''')

                # Scroll to make items visible in viewport (triggers IntersectionObserver)
                # Find the last visible job item and scroll it into view
                page.evaluate('''
                    const jobItems = Array.from(document.querySelectorAll('li[data-occludable-job-id]'));
                    if (jobItems.length > 0) {
                        // Scroll the last item into view to trigger lazy loading
                        const lastItem = jobItems[jobItems.length - 1];
                        lastItem.scrollIntoView({ behavior: 'smooth', block: 'end' });
                    }
                ''')

                # Wait for content to load after scroll (randomized for human-like behavior)
                page.wait_for_timeout(random.randint(scroll_wait_min, scroll_wait_max))

                # Count populated elements after scroll
                counts_after = page.evaluate('''
                    const total = document.querySelectorAll('li[data-occludable-job-id]').length;
                    const empty = document.querySelectorAll('li.jobs-search-results__job-card-search--generic-occludable-area').length;
                    const populated = total - empty;
                    ({total, populated, empty})
                ''')

                # Check if we've reached scroll end
                at_scroll_end = page.evaluate('''
                    const jobList = document.querySelector('ul.scaffold-layout__list, ul.jobs-search-results__list');
                    if (jobList) {
                        jobList.scrollTop + jobList.clientHeight >= jobList.scrollHeight - 10
                    } else {
                        true
                    }
                ''')

                # If no new elements populated AND no new elements added AND at scroll end, stop
                no_new_populated = counts_after['populated'] == counts_before['populated']
                no_new_elements = counts_after['total'] == counts_before['total']

                if no_new_populated and no_new_elements and at_scroll_end:
                    break

            # Get all job list elements
            job_list_elements = page.query_selector_all('ul.scaffold-layout__list, ul.jobs-search-results__list')
            if job_list_elements:
                job_list_html = job_list_elements[0].inner_html()
            else:
                job_list_html = page.content()

            # Extract jobs using BeautifulSoup
            jobs, elements_found, empty_placeholders, parsing_errors = extract_jobs_with_bs4(job_list_html, page_number)

            # If no jobs found on first page, try refreshing once
            if len(jobs) == 0 and page_number == 1:
                print("No jobs found. Refreshing page once...")
                page.reload(wait_until='domcontentloaded', timeout=30000)
                page.wait_for_selector('ul', timeout=10000)
                page.wait_for_timeout(5000)

                # Try extraction again after refresh
                job_list_elements = page.query_selector_all('ul.scaffold-layout__list, ul.jobs-search-results__list')
                if job_list_elements:
                    job_list_html = job_list_elements[0].inner_html()
                else:
                    job_list_html = page.content()

                jobs, elements_found, empty_placeholders, parsing_errors = extract_jobs_with_bs4(job_list_html, page_number)

            # If still no jobs found, we've reached the end
            if len(jobs) == 0:
                print("No more jobs - ran out of pages.")
                logging.info(
                    f"Search '{search_params['search_term']}' ended: No more results found after page {page_number - 1}. "
                    f"Total extracted: {total_jobs_extracted} jobs"
                )
                break

            # Save to database
            saved, duplicates = save_to_database(
                jobs, search_params, date_of_search, page_number,
                elements_found, empty_placeholders, parsing_errors
            )

            # Update counters
            total_jobs_extracted += len(jobs)
            start_offset += len(jobs)  # Use actual count for next page offset

            print(f"✓ ({total_jobs_extracted} total)")

            # Check if we've reached the max limit
            if max_jobs and total_jobs_extracted >= max_jobs:
                print(f"Reached limit ({max_jobs}).")
                logging.info(
                    f"Search '{search_params['search_term']}' ended: Reached max_jobs limit of {max_jobs}. "
                    f"Total extracted: {total_jobs_extracted} jobs from {page_number} pages"
                )
                break

            # Increment page number for next iteration
            page_number += 1

            # Wait between pages (randomized for human-like behavior)
            page.wait_for_timeout(random.randint(15000, 20000))

        print(f"✓ Complete: {total_jobs_extracted} jobs from {page_number} pages\n")

        logging.info(
            f"Completed search: '{search_params['search_term']}' | "
            f"Geo ID: {search_params['search_geo_id']} | "
            f"Time filter: {search_params['search_time_filtered']} - "
            f"Total extracted: {total_jobs_extracted} jobs from {page_number} pages"
        )

        return total_jobs_extracted

    finally:
        page.close()

def main(search_urls, max_jobs=25):
    """Main function

    Args:
        search_urls: List of LinkedIn job search URLs
        max_jobs: Maximum number of jobs to extract per search (None for unlimited)
    """

    print(f"\n{'='*60}")
    print("LinkedIn Job Search - Starting")
    print(f"{'='*60}")
    print(f"Number of searches: {len(search_urls)}")
    print(f"Max jobs per search: {max_jobs if max_jobs else 'Unlimited'}")
    print(f"{'='*60}")

    with sync_playwright() as p:
        # Launch browser with saved session
        browser = p.chromium.launch(
            channel="chrome",
            headless=False
        )

        # Load saved LinkedIn session if it exists
        if os.path.exists(SESSION_FILE):
            context = browser.new_context(storage_state=SESSION_FILE)
        else:
            print("\n⚠ No saved LinkedIn session found!")
            print("Please run: python linkedin_login.py first\n")
            browser.close()
            return

        logging.info("Browser launched with saved LinkedIn session")

        try:
            grand_total = 0

            for idx, search_url in enumerate(search_urls, 1):
                print(f"\n\n{'#'*60}")
                print(f"# SEARCH {idx}/{len(search_urls)}")
                print(f"{'#'*60}")

                count = process_search(search_url, max_jobs, context)
                grand_total += count

                # Wait between different searches (randomized for human-like behavior)
                if idx < len(search_urls):
                    wait_time = random.uniform(10, 15)
                    print(f"\nWaiting {wait_time:.1f} seconds before next search...")
                    import time
                    time.sleep(wait_time)

            print(f"\n\n{'='*60}")
            print("✓ ALL SEARCHES COMPLETE!")
            print(f"✓ Grand total jobs extracted: {grand_total}")
            print("✓ Check the 'search_results' table in data/jobs.db")
            print(f"{'='*60}")

        except Exception as e:
            print(f"✗ Error during extraction: {e}")
            import traceback
            traceback.print_exc()

        finally:
            browser.close()

if __name__ == "__main__":
    # List of search URLs
    # 1 day - f_TPR=r86400
    search_urls = [
        "https://www.linkedin.com/jobs/search/?f_TPR=r604800&geoId=103644278&keywords=software%20engineer%20-%20data&origin=JOB_SEARCH_PAGE_JOB_FILTER",
        "https://www.linkedin.com/jobs/search/?f_TPR=r604800&geoId=103644278&keywords=senior%20data%20engineer&origin=JOB_SEARCH_PAGE_JOB_FILTER",
        "https://www.linkedin.com/jobs/search/?f_TPR=r604800&geoId=103644278&keywords=software%20engineer&origin=JOB_SEARCH_PAGE_JOB_FILTER",
        "https://www.linkedin.com/jobs/search/?f_TPR=r604800&geoId=103644278&keywords=principal%20software%20engineer%20-%20data&origin=JOB_SEARCH_PAGE_JOB_FILTER",
    ]

    # For testing: limit to 25 jobs per search
    main(search_urls, max_jobs=1500)

    # For production: extract all jobs until no more results
    # main(search_urls, max_jobs=None)
