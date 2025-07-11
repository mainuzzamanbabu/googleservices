import csv
import trafilatura
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import time
import re
import signal
from contextlib import contextmanager
import json
from datetime import datetime
import concurrent.futures  # ADD THIS LINE
import threading

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Blacklist domains that are known to be slow or problematic
BLACKLIST_DOMAINS = {
    'lenovo.com',
    'reddit',
    'ibm.com',
    'oracle.com',
    'salesforce.com',
    'microsoft.com',
    'adobe.com',
    'sap.com',
    'workday.com',
    'servicenow.com',
    'tableau.com',
    'zoom.us',
    'webex.com',
    'gotomeeting.com',
    # Add more problematic domains as needed
}

@contextmanager
def timeout_context(seconds):
    """Cross-platform timeout context manager using threading"""
    timeout_occurred = threading.Event()
    
    def timeout_handler():
        time.sleep(seconds)
        timeout_occurred.set()
    
    # Start timeout thread
    timeout_thread = threading.Thread(target=timeout_handler, daemon=True)
    timeout_thread.start()
    
    try:
        yield timeout_occurred
    finally:
        # Clean up - thread will exit when daemon process ends
        pass

def get_domain(url):
    return urlparse(url).netloc.lower().replace('www.', '')

def is_blacklisted(url):
    """Check if URL domain is in blacklist"""
    domain = get_domain(url)
    return any(blacklisted in domain for blacklisted in BLACKLIST_DOMAINS)

def clean_text(text):
    """Clean and normalize text content"""
    if not text:
        return ""
    # Remove extra whitespace and normalize
    text = re.sub(r'\s+', ' ', text.strip())
    # Remove common web cruft
    text = re.sub(r'(cookie|privacy policy|terms of service|subscribe|newsletter)', '', text, flags=re.IGNORECASE)
    return text

def scrape_searxng_local(query, max_results=10):
    """Search using local SearXNG instance"""
    url = "http://localhost:8888/search"
    data = {"q": query, "format": "json"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    try:
        print(f"Searching SearXNG for: '{query}'")
        response = requests.post(url, data=data, headers=headers, timeout=15)
        response.raise_for_status()
        search_results = response.json()
        
        if not search_results.get('results'):
            print("No results found in SearXNG response")
            return []
        
        results = []
        seen_domains = set()
        
        for result in search_results['results']:
            if len(results) >= max_results:
                break
            
            # Extract URL
            result_url = result.get('url', '')
            if not result_url:
                continue
                
            # Skip blacklisted domains
            if is_blacklisted(result_url):
                print(f"  Skipping blacklisted domain: {get_domain(result_url)}")
                continue
                
            # Skip duplicate domains
            domain = get_domain(result_url)
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            
            # Extract other fields
            title = result.get('title', 'No title available')
            content = result.get('content', 'No description available')
            
            results.append({
                'title': title,
                'href': result_url,
                'body': content
            })
            
        print(f"Found {len(results)} unique results from SearXNG (after filtering blacklist)")
        return results
        
    except requests.exceptions.HTTPError as e:
        print(f"[SearXNG] HTTP error for '{query}': {e}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"[SearXNG] Connection error for '{query}': {e}")
        return []
    except Exception as e:
        print(f"[SearXNG] Unexpected error for '{query}': {e}")
        return []

def extract_smart_content(html, url):
    """Extract only the most important content based on site type and structure"""
    soup = BeautifulSoup(html, "lxml")
    result = {
        "url": url,
        "domain": get_domain(url),
        "title": "",
        "main_content": "",
        "key_points": [],
        "metadata": {}
    }
    
    # Extract title
    title_tag = soup.find('title')
    if title_tag:
        result["title"] = clean_text(title_tag.get_text())
    
    # Site-specific extraction
    if "amazon." in url:
        return extract_amazon_smart(soup, url)
    elif any(domain in url for domain in ["reddit.com", "stackoverflow.com", "github.com"]):
        return extract_forum_smart(soup, url)
    elif any(domain in url for domain in ["wikipedia.org", "britannica.com"]):
        return extract_wiki_smart(soup, url)
    elif any(domain in url for domain in ["youtube.com", "vimeo.com"]):
        return extract_video_smart(soup, url)
    else:
        return extract_generic_smart(soup, url)

def extract_amazon_smart(soup, url):
    """Extract key Amazon product information"""
    result = {
        "url": url,
        "domain": "amazon",
        "type": "product",
        "title": "",
        "price": "",
        "rating": "",
        "key_features": [],
        "description": "",
        "specs": {}
    }
    
    # Product title
    title = soup.find(id="productTitle")
    if title:
        result["title"] = clean_text(title.get_text())
    
    # Price
    price_selectors = [
        ".a-price-whole",
        ".a-price .a-offscreen",
        "#priceblock_dealprice",
        "#priceblock_ourprice"
    ]
    for selector in price_selectors:
        price = soup.select_one(selector)
        if price:
            result["price"] = clean_text(price.get_text())
            break
    
    # Rating
    rating = soup.select_one("[data-hook='average-star-rating'] .a-icon-alt")
    if rating:
        result["rating"] = clean_text(rating.get_text())
    
    # Key features (limit to top 5)
    bullets = soup.select("#feature-bullets ul li span")
    if bullets:
        result["key_features"] = [clean_text(b.get_text()) for b in bullets[:5] if clean_text(b.get_text())]
    
    # Description (first paragraph only)
    desc = soup.find(id="productDescription")
    if desc:
        desc_text = clean_text(desc.get_text())
        # Take only first 500 characters
        result["description"] = desc_text[:500] + "..." if len(desc_text) > 500 else desc_text
    
    # Key specs only (limit to most important ones)
    important_specs = ["Brand", "Model", "Color", "Size", "Weight", "Material", "Dimensions"]
    for table_id in ["productDetails_techSpec_section_1", "productDetails_detailBullets_sections1"]:
        table = soup.find(id=table_id)
        if table:
            for row in table.find_all("tr"):
                th = row.find("th")
                td = row.find("td")
                if th and td:
                    spec_name = clean_text(th.get_text())
                    if any(imp_spec.lower() in spec_name.lower() for imp_spec in important_specs):
                        result["specs"][spec_name] = clean_text(td.get_text())
    
    return result

def extract_forum_smart(soup, url):
    """Extract key information from forum/discussion sites"""
    result = {
        "url": url,
        "domain": get_domain(url),
        "type": "forum",
        "title": "",
        "question": "",
        "top_answers": [],
        "tags": []
    }
    
    # Title
    title_selectors = ["h1", ".title", "[data-testid='post-content'] h1"]
    for selector in title_selectors:
        title = soup.select_one(selector)
        if title:
            result["title"] = clean_text(title.get_text())
            break
    
    # Question/main content
    content_selectors = [".post-text", "[data-testid='post-content'] div", ".usertext-body"]
    for selector in content_selectors:
        content = soup.select_one(selector)
        if content:
            content_text = clean_text(content.get_text())
            result["question"] = content_text[:800] + "..." if len(content_text) > 800 else content_text
            break
    
    # Top answers (limit to 2)
    answer_selectors = [".answer .post-text", ".comment-body", ".reply .usertext-body"]
    for selector in answer_selectors:
        answers = soup.select(selector)
        if answers:
            result["top_answers"] = [clean_text(ans.get_text())[:400] + "..." if len(clean_text(ans.get_text())) > 400 else clean_text(ans.get_text()) for ans in answers[:2]]
            break
    
    return result

def extract_wiki_smart(soup, url):
    """Extract key information from Wikipedia-style sites"""
    result = {
        "url": url,
        "domain": get_domain(url),
        "type": "encyclopedia",
        "title": "",
        "summary": "",
        "key_sections": []
    }
    
    # Title
    title = soup.find('h1')
    if title:
        result["title"] = clean_text(title.get_text())
    
    # Summary (first paragraph)
    first_p = soup.select_one("p")
    if first_p:
        summary_text = clean_text(first_p.get_text())
        result["summary"] = summary_text[:600] + "..." if len(summary_text) > 600 else summary_text
    
    # Key sections (first 3 h2 sections)
    sections = soup.select("h2")
    for section in sections[:3]:
        section_title = clean_text(section.get_text())
        if section_title and not any(skip in section_title.lower() for skip in ["reference", "external", "see also"]):
            result["key_sections"].append(section_title)
    
    return result

def extract_video_smart(soup, url):
    """Extract key information from video sites"""
    result = {
        "url": url,
        "domain": get_domain(url),
        "type": "video",
        "title": "",
        "description": "",
        "duration": "",
        "views": ""
    }
    
    # Title
    title_selectors = ["h1", ".title", "[name='title']"]
    for selector in title_selectors:
        title = soup.select_one(selector)
        if title:
            result["title"] = clean_text(title.get_text())
            break
    
    # Description (first 300 chars)
    desc_selectors = [".description", "[name='description']", ".content"]
    for selector in desc_selectors:
        desc = soup.select_one(selector)
        if desc:
            desc_text = clean_text(desc.get_text())
            result["description"] = desc_text[:300] + "..." if len(desc_text) > 300 else desc_text
            break
    
    return result

def extract_generic_smart(soup, url):
    """Extract key information from generic websites"""
    result = {
        "url": url,
        "domain": get_domain(url),
        "type": "generic",
        "title": "",
        "main_content": "",
        "key_sections": [],
        "important_details": [],
        "summary": ""
    }
    
    # Title
    title = soup.find('title')
    if title:
        result["title"] = clean_text(title.get_text())
    
    # Try to get a summary from meta description
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc:
        result["summary"] = clean_text(meta_desc.get('content', ''))
    
    # Main content areas (prioritize article, main, or content divs)
    content_selectors = [
        "article", "main", ".content", ".post-content", 
        ".entry-content", ".article-content", "#content",
        ".main-content", ".page-content", ".site-content"
    ]
    
    main_content_found = False
    for selector in content_selectors:
        content = soup.select_one(selector)
        if content:
            content_text = clean_text(content.get_text())
            if len(content_text) > 100:  # Ensure substantial content
                # Limit to first 1500 characters for more comprehensive info
                result["main_content"] = content_text[:1500] + "..." if len(content_text) > 1500 else content_text
                main_content_found = True
                break
    
    # If no main content found, get body content but filter out navigation/footer
    if not main_content_found:
        # Remove navigation, footer, sidebar elements
        for unwanted in soup.select('nav, footer, aside, .nav, .footer, .sidebar, .menu, .header, .advertisement, .ads'):
            unwanted.decompose()
        
        # Get all paragraphs and list items
        content_elements = soup.select("p, li, div.description, div.summary, .info, .details")
        content_texts = []
        
        for elem in content_elements:
            text = clean_text(elem.get_text())
            if len(text) > 20 and not any(skip in text.lower() for skip in 
                ['cookie', 'privacy', 'terms', 'subscribe', 'newsletter', 'login', 'register']):
                content_texts.append(text)
        
        if content_texts:
            combined_text = " ".join(content_texts)
            result["main_content"] = combined_text[:1500] + "..." if len(combined_text) > 1500 else combined_text
    
    # Extract key sections with their content
    headings = soup.select("h1, h2, h3")
    for heading in headings[:6]:  # Top 6 headings
        heading_text = clean_text(heading.get_text())
        if heading_text and len(heading_text) > 3:
            # Find content after this heading
            section_content = []
            current = heading.find_next_sibling()
            
            while current and current.name not in ['h1', 'h2', 'h3'] and len(section_content) < 3:
                if current.name in ['p', 'div', 'ul', 'ol']:
                    text = clean_text(current.get_text())
                    if len(text) > 20:
                        section_content.append(text)
                current = current.find_next_sibling()
            
            if section_content:
                section_text = " ".join(section_content)
                # Limit each section to 300 characters
                if len(section_text) > 300:
                    section_text = section_text[:300] + "..."
                
                result["key_sections"].append({
                    "heading": heading_text,
                    "content": section_text
                })
    
    # Extract important details (prices, specs, features, etc.)
    detail_patterns = [
        r'(?:price|cost|₹|rs\.?|usd|\$)\s*:?\s*([0-9,]+(?:\.[0-9]+)?)',
        r'(?:mileage|efficiency|mpg|kmpl)\s*:?\s*([0-9]+(?:\.[0-9]+)?)',
        r'(?:power|hp|bhp|kw)\s*:?\s*([0-9]+(?:\.[0-9]+)?)',
        r'(?:engine|displacement|cc)\s*:?\s*([0-9]+(?:\.[0-9]+)?)',
        r'(?:weight|mass|kg|pounds)\s*:?\s*([0-9]+(?:\.[0-9]+)?)',
        r'(?:features?|specifications?|specs?)\s*:?\s*([a-zA-Z0-9\s,.-]+)'
    ]
    
    full_text = result["main_content"] + " " + " ".join([section["content"] for section in result["key_sections"]])
    
    for pattern in detail_patterns:
        matches = re.findall(pattern, full_text, re.IGNORECASE)
        if matches:
            detail_type = pattern.split('|')[0].replace('(?:', '').replace('\\', '')
            result["important_details"].append(f"{detail_type}: {matches[0]}")
    
    # If we still don't have good content, try table data
    if len(result["main_content"]) < 200:
        tables = soup.select("table")
        table_data = []
        for table in tables[:2]:  # Max 2 tables
            rows = table.select("tr")
            for row in rows[:5]:  # Max 5 rows per table
                cells = row.select("td, th")
                if len(cells) >= 2:
                    row_text = " | ".join([clean_text(cell.get_text()) for cell in cells])
                    if len(row_text) > 10:
                        table_data.append(row_text)
        
        if table_data:
            result["important_details"].extend(table_data[:10])
    
    return result

def try_scrape_smart(url, timeout_seconds=8):
    """Try to scrape with smart content extraction and timeout"""
    scrape_start = time.time()
    print(f"  Attempting to scrape: {url} (timeout: {timeout_seconds}s)")
    
    try:
        with timeout_context(timeout_seconds) as timeout_event:
            # Try requests + smart extraction first
            print(f"    Trying requests + smart extraction...")
            try:
                if timeout_event.is_set():
                    raise TimeoutError(f"Operation timed out after {timeout_seconds} seconds")
                
                resp = requests.get(url, timeout=timeout_seconds, headers={"User-Agent": "Mozilla/5.0"})
                if resp.ok:
                    if timeout_event.is_set():
                        raise TimeoutError(f"Operation timed out after {timeout_seconds} seconds")
                    
                    smart_content = extract_smart_content(resp.text, url)
                    if smart_content and (smart_content.get("main_content") or smart_content.get("key_sections")):
                        scrape_time = time.time() - scrape_start
                        print(f"    ✓ Success with requests+smart ({scrape_time:.2f}s)")
                        return {"url": url, "method": "requests+smart", "content": smart_content}
            except requests.exceptions.RequestException as e:
                print(f"    ✗ Requests failed: {e}")
            
            # Try trafilatura as fallback
            print(f"    Trying trafilatura...")
            if timeout_event.is_set():
                raise TimeoutError(f"Operation timed out after {timeout_seconds} seconds")
            
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                if timeout_event.is_set():
                    raise TimeoutError(f"Operation timed out after {timeout_seconds} seconds")
                
                extracted = trafilatura.extract(downloaded)
                if extracted and len(extracted.strip()) > 30:
                    # For trafilatura, we still do smart extraction from the HTML
                    smart_content = extract_smart_content(downloaded, url)
                    if smart_content:
                        scrape_time = time.time() - scrape_start
                        print(f"    ✓ Success with trafilatura+smart ({scrape_time:.2f}s)")
                        return {"url": url, "method": "trafilatura+smart", "content": smart_content}
    
    except TimeoutError:
        scrape_time = time.time() - scrape_start
        print(f"    ✗ Timeout after {scrape_time:.2f}s")
        return None
    
    scrape_time = time.time() - scrape_start
    print(f"    ✗ Failed to scrape ({scrape_time:.2f}s)")
    return None

def try_playwright_scrape_smart(url, timeout_seconds=15):
    """Try Playwright with smart content extraction and timeout"""
    if not PLAYWRIGHT_AVAILABLE:
        print(f"    Playwright not installed. Can't scrape JS-heavy site: {url}")
        return None
    
    playwright_start = time.time()
    print(f"    Trying Playwright with smart extraction... (timeout: {timeout_seconds}s)")
    
    try:
        with timeout_context(timeout_seconds) as timeout_event:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                try:
                    if timeout_event.is_set():
                        raise TimeoutError(f"Operation timed out after {timeout_seconds} seconds")
                    
                    page.goto(url, timeout=timeout_seconds * 1000)
                    time.sleep(2)  # Wait for dynamic content
                    
                    if timeout_event.is_set():
                        raise TimeoutError(f"Operation timed out after {timeout_seconds} seconds")
                    
                    html = page.content()
                    smart_content = extract_smart_content(html, url)
                    if smart_content and (smart_content.get("main_content") or smart_content.get("title")):
                        playwright_time = time.time() - playwright_start
                        print(f"    ✓ Success with playwright+smart ({playwright_time:.2f}s)")
                        return {"url": url, "method": "playwright+smart", "content": smart_content}
                except Exception as e:
                    print(f"    ✗ Playwright error: {e}")
                finally:
                    browser.close()
    
    except TimeoutError:
        playwright_time = time.time() - playwright_start
        print(f"    ✗ Playwright timeout after {playwright_time:.2f}s")
        return None
    
    playwright_time = time.time() - playwright_start
    print(f"    ✗ Playwright failed ({playwright_time:.2f}s)")
    return None

# ADD THIS NEW FUNCTION FOR FILTERING URLS
def filter_urls(urls):
    """Filter URLs to remove duplicates and blacklisted domains"""
    seen_domains = set()
    filtered_urls = []
    for url in urls:
        domain = get_domain(url)
        if domain not in seen_domains and not is_blacklisted(url):
            filtered_urls.append(url)
            seen_domains.add(domain)
    return filtered_urls

# REPLACE THE ENTIRE scrape_single_site FUNCTION WITH THIS NEW ONE
def scrape_multiple_sites_truly_parallel(query, max_sites=2, max_total_time=60, max_search_results=15):
    """
    Scrape multiple sites in TRUE parallel within the same time budget
    All sites are scraped simultaneously, not one by one
    """
    total_start = time.time()
    
    # Get search results from SearXNG
    print(f"Searching local SearXNG for: '{query}'")
    search_start = time.time()
    results = scrape_searxng_local(query, max_search_results)
    search_time = time.time() - search_start
    
    if not results:
        print("No search results found from SearXNG")
        return None
    
    print(f"SearXNG search completed in {search_time:.2f}s - Found {len(results)} results")
    
    # Extract and filter URLs
    urls = [result['href'] for result in results]
    filtered_urls = filter_urls(urls)
    
    print(f"Filtered to {len(filtered_urls)} unique, non-blacklisted domains")
    
    if not filtered_urls:
        print("No valid URLs after filtering")
        return None
    
    # TRUE PARALLEL PROCESSING - All sites scraped simultaneously
    print(f"\nStarting TRUE parallel scraping of {min(max_sites, len(filtered_urls))} sites...")
    
    successful_scrapes = []
    remaining_time = max_total_time - (time.time() - total_start)
    
    # Use ThreadPoolExecutor for TRUE parallel execution
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_sites) as executor:
        # Submit ALL target URLs simultaneously
        target_urls = filtered_urls[:max_sites]
        
        print(f"  Submitting {len(target_urls)} URLs for simultaneous processing...")
        print(f"  Target sites: {[get_domain(url) for url in target_urls]}")
        
        # Submit all scraping tasks at once
        future_to_url = {
            executor.submit(try_scrape_smart_with_better_timeout, url, min(12, remaining_time - 5)): url 
            for url in target_urls
        }
        
        scrape_start_time = time.time()
        
        # Wait for all results to complete (or timeout)
        try:
            for future in concurrent.futures.as_completed(future_to_url, timeout=remaining_time):
                url = future_to_url[future]
                try:
                    result = future.result()
                    if result:
                        successful_scrapes.append(result)
                        elapsed = time.time() - scrape_start_time
                        print(f"  ✓ {get_domain(url)} completed in {elapsed:.2f}s ({len(successful_scrapes)}/{len(target_urls)})")
                    else:
                        elapsed = time.time() - scrape_start_time
                        print(f"  ✗ {get_domain(url)} failed after {elapsed:.2f}s")
                except Exception as e:
                    elapsed = time.time() - scrape_start_time
                    print(f"  ✗ {get_domain(url)} error after {elapsed:.2f}s: {e}")
        
        except concurrent.futures.TimeoutError:
            print(f"  ⏰ Parallel scraping timeout after {remaining_time:.1f}s")
            # Cancel remaining futures
            for future in future_to_url:
                future.cancel()
    
    # Fallback with Playwright if we didn't get enough results
    if len(successful_scrapes) < max_sites and PLAYWRIGHT_AVAILABLE:
        remaining_time = max_total_time - (time.time() - total_start)
        if remaining_time > 20:  # Need sufficient time for Playwright
            print(f"\nPlaywright fallback for remaining sites (time remaining: {remaining_time:.1f}s)")
            
            # Get URLs that failed in the first attempt
            successful_domains = {get_domain(scrape['url']) for scrape in successful_scrapes}
            fallback_urls = [url for url in filtered_urls[max_sites:max_sites+3] 
                           if get_domain(url) not in successful_domains]
            
            sites_needed = max_sites - len(successful_scrapes)
            
            # Also try Playwright in parallel for remaining sites
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(sites_needed, 2)) as executor:
                playwright_futures = {
                    executor.submit(try_playwright_scrape_smart, url, min(15, remaining_time - 5)): url 
                    for url in fallback_urls[:sites_needed]
                }
                
                try:
                    for future in concurrent.futures.as_completed(playwright_futures, timeout=remaining_time):
                        if len(successful_scrapes) >= max_sites:
                            break
                        
                        url = playwright_futures[future]
                        try:
                            result = future.result()
                            if result:
                                successful_scrapes.append(result)
                                print(f"  ✓ Playwright success from {get_domain(url)} ({len(successful_scrapes)}/{max_sites})")
                        except Exception as e:
                            print(f"  ✗ Playwright error for {get_domain(url)}: {e}")
                
                except concurrent.futures.TimeoutError:
                    print(f"  ⏰ Playwright fallback timeout")
    
    # Return results
    total_time = time.time() - total_start
    
    if successful_scrapes:
        print(f"\n" + "="*60)
        print(f"SUCCESS: Scraped {len(successful_scrapes)} sites in {total_time:.2f} seconds")
        print(f"Sites scraped: {[get_domain(site['url']) for site in successful_scrapes]}")
        print(f"TRUE PARALLEL EFFICIENCY: {total_time/len(successful_scrapes):.2f}s average per site")
        print(f"="*60)
        return successful_scrapes
    else:
        print(f"\n" + "="*60)
        print(f"FAILED: Unable to scrape any site after all attempts ({total_time:.2f} seconds)")
        print(f"Data pulling is not possible for this query.")
        print(f"="*60)
        return None


# Enhanced version with better timeout handling
def try_scrape_smart_with_better_timeout(url, timeout_seconds=10):
    """Enhanced scraping with better timeout control"""
    start_time = time.time()
    print(f"    Starting {get_domain(url)} at {time.strftime('%H:%M:%S')}")
    
    try:
        # Try requests first with strict timeout
        try:
            response = requests.get(
                url, 
                timeout=timeout_seconds,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )
            
            if response.ok:
                smart_content = extract_smart_content(response.text, url)
                if smart_content and (smart_content.get("main_content") or smart_content.get("key_sections")):
                    elapsed = time.time() - start_time
                    print(f"    ✓ {get_domain(url)} completed in {elapsed:.2f}s")
                    return {"url": url, "method": "requests+smart", "content": smart_content}
        
        except requests.exceptions.RequestException as e:
            print(f"    ✗ {get_domain(url)} requests failed: {str(e)[:50]}...")
        
        # Fallback to trafilatura
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                extracted = trafilatura.extract(downloaded)
                if extracted and len(extracted.strip()) > 30:
                    smart_content = extract_smart_content(downloaded, url)
                    if smart_content:
                        elapsed = time.time() - start_time
                        print(f"    ✓ {get_domain(url)} completed with trafilatura in {elapsed:.2f}s")
                        return {"url": url, "method": "trafilatura+smart", "content": smart_content}
        
        except Exception as e:
            print(f"    ✗ {get_domain(url)} trafilatura failed: {str(e)[:50]}...")
    
    except Exception as e:
        print(f"    ✗ {get_domain(url)} general error: {str(e)[:50]}...")
    
    elapsed = time.time() - start_time
    print(f"    ✗ {get_domain(url)} failed after {elapsed:.2f}s")
    return None


# Update the main function to use the truly parallel version
def scrape_multiple_sites_parallel(query, max_sites=2, max_total_time=60, max_search_results=15):
    """
    Wrapper function - now uses truly parallel implementation
    """
    return scrape_multiple_sites_truly_parallel(query, max_sites, max_total_time, max_search_results)


# KEEP THE ORIGINAL SINGLE SITE FUNCTION FOR BACKWARD COMPATIBILITY
def scrape_single_site(query, max_search_results=15):
    """
    Original single site scraping function (kept for backward compatibility)
    """
    return scrape_multiple_sites_parallel(query, max_sites=1, max_total_time=60, max_search_results=max_search_results)

if __name__ == "__main__":
    print("Smart Web Scraper - Parallel Multi-Site Scraping")
    print("=" * 60)
    
    query = input("Enter your search query: ").strip()
    
    # Default to 2 sites (as requested)
    num_sites = 2
    
    execution_start = time.time()
    print(f"\nStarting execution at {time.strftime('%H:%M:%S')}")
    print(f"Target: {num_sites} sites")
    print("=" * 60)
    
    # Use the new parallel function
    results = scrape_multiple_sites_parallel(query, max_sites=num_sites, max_total_time=60)
    
    execution_time = time.time() - execution_start
    
    print(f"\nRESULTS:")
    print("=" * 60)
    
    if results:
        for idx, result in enumerate(results, 1):
            print(f"\n--- RESULT {idx} ---")
            print(f"URL: {result['url']}")
            print(f"Method: {result['method']}")
            print(f"Domain: {result['content'].get('domain', 'unknown')}")
            print(f"Content Type: {result['content'].get('type', 'unknown')}")
            print("-" * 40)
            
            content = result['content']
            for key, value in content.items():
                if key in ['url', 'domain', 'type']:
                    continue
                elif key == 'key_sections':
                    if value:
                        print(f"Key Sections:")
                        for section in value:
                            if isinstance(section, dict):
                                print(f"  📍 {section.get('heading', 'Unknown Section')}")
                                print(f"     {section.get('content', 'No content')}")
                            else:
                                print(f"  📍 {section}")
                            print()
                elif key == 'key_features':
                    if value:
                        print(f"Key Features:")
                        for feature in value:
                            print(f"  ✓ {feature}")
                        print()
                elif key == 'top_answers':
                    if value:
                        print(f"Top Answers:")
                        for i, answer in enumerate(value, 1):
                            print(f"  {i}. {answer}")
                        print()
                elif key == 'specs':
                    if value:
                        print(f"Specifications:")
                        for spec_name, spec_value in value.items():
                            print(f"  {spec_name}: {spec_value}")
                        print()
                elif key == 'important_details':
                    if value:
                        print(f"Important Details:")
                        for detail in value:
                            print(f"  • {detail}")
                        print()
                elif isinstance(value, list):
                    if value:  # Only show non-empty lists
                        print(f"{key.replace('_', ' ').title()}:")
                        for item in value:
                            print(f"  • {item}")
                        print()
                elif isinstance(value, dict):
                    if value:  # Only show non-empty dicts
                        print(f"{key.replace('_', ' ').title()}:")
                        for k, v in value.items():
                            print(f"  {k}: {v}")
                        print()
                elif value:  # Only show non-empty strings
                    print(f"{key.replace('_', ' ').title()}: {value}")
                    print()
            
            # Add separator between results
            if idx < len(results):
                print("\n" + "="*60)
    else:
        print("Failed to scrape any site.")
        print("This could be due to:")
        print("  • Network connectivity issues")
        print("  • All target sites being blacklisted")
        print("  • Sites blocking scraping attempts")
        print("  • Timeout issues")
    
    print(f"\n" + "="*60)
    print(f"EXECUTION SUMMARY:")
    print(f"Query: '{query}'")
    print(f"Sites scraped: {len(results) if results else 0}/{num_sites}")
    print(f"Total execution time: {execution_time:.2f} seconds")
    if results:
        print(f"Parallel efficiency: {execution_time:.2f}s total for {len(results)} sites")
        print(f"Sequential would have taken: ~{execution_time * len(results):.2f} seconds")
        print(f"Time saved by parallel processing: ~{execution_time * (len(results) - 1):.2f} seconds")
    else:
        print("No successful scrapes to analyze")
    print(f"="*60)