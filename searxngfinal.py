# Bulk, time management, 2 minimum output, parallel scraping with timeout 

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
    'daraz.com.bd',
    'reddit',
    'mobiledokan.com',
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
def scrape_multiple_sites_truly_parallel(query, max_sites=2, max_total_time=60, max_search_results=15):
    """
    Enhanced parallel scraping with batched approach and strict time management
    - Try 5 sites initially (6 seconds each batch)
    - If insufficient results, try next 5 sites
    - Then try Playwright for first 3 sites (10 seconds)
    - Finally try next 5 sites with Playwright
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
    
    successful_scrapes = []
    
    # PHASE 1: Try first 5 sites with requests/trafilatura (6 seconds)
    print(f"\n=== PHASE 1: First 5 sites (6 seconds) ===")
    batch_1_urls = filtered_urls[:5]
    if batch_1_urls:
        batch_results = scrape_batch_parallel(batch_1_urls, timeout_per_site=6, batch_name="Batch 1")
        successful_scrapes.extend(batch_results)
        
        if len(successful_scrapes) >= max_sites:
            print(f"✓ Got {len(successful_scrapes)} sites from Phase 1 - SUCCESS!")
            return successful_scrapes[:max_sites]
    
    # PHASE 2: Try next 5 sites if we need more (6 seconds)
    if len(successful_scrapes) < max_sites and len(filtered_urls) > 5:
        print(f"\n=== PHASE 2: Next 5 sites (6 seconds) ===")
        print(f"Current results: {len(successful_scrapes)}, need: {max_sites}")
        
        batch_2_urls = filtered_urls[5:10]
        if batch_2_urls:
            batch_results = scrape_batch_parallel(batch_2_urls, timeout_per_site=6, batch_name="Batch 2")
            successful_scrapes.extend(batch_results)
            
            if len(successful_scrapes) >= max_sites:
                print(f"✓ Got {len(successful_scrapes)} sites from Phase 2 - SUCCESS!")
                return successful_scrapes[:max_sites]
    
    # PHASE 3: Try Playwright for first 3 sites (10 seconds)
    if len(successful_scrapes) < max_sites and PLAYWRIGHT_AVAILABLE:
        print(f"\n=== PHASE 3: Playwright fallback - First 3 sites (10 seconds) ===")
        print(f"Current results: {len(successful_scrapes)}, need: {max_sites}")
        
        # Get URLs that haven't been successfully scraped yet
        successful_domains = {get_domain(scrape['url']) for scrape in successful_scrapes}
        playwright_urls = [url for url in filtered_urls[:15] 
                          if get_domain(url) not in successful_domains][:3]
        
        if playwright_urls:
            batch_results = scrape_batch_playwright(playwright_urls, timeout_per_site=10, batch_name="Playwright Batch 1")
            successful_scrapes.extend(batch_results)
            
            if len(successful_scrapes) >= max_sites:
                print(f"✓ Got {len(successful_scrapes)} sites from Phase 3 - SUCCESS!")
                return successful_scrapes[:max_sites]
    
    # PHASE 4: Try next 5 sites with requests/trafilatura (6 seconds)
    if len(successful_scrapes) < max_sites and len(filtered_urls) > 10:
        print(f"\n=== PHASE 4: Final batch - Next 5 sites (6 seconds) ===")
        print(f"Current results: {len(successful_scrapes)}, need: {max_sites}")
        
        successful_domains = {get_domain(scrape['url']) for scrape in successful_scrapes}
        final_urls = [url for url in filtered_urls[10:15] 
                     if get_domain(url) not in successful_domains]
        
        if final_urls:
            batch_results = scrape_batch_parallel(final_urls, timeout_per_site=6, batch_name="Final Batch")
            successful_scrapes.extend(batch_results)
    
    # Return results
    total_time = time.time() - total_start
    
    if successful_scrapes:
        print(f"\n" + "="*60)
        print(f"SUCCESS: Scraped {len(successful_scrapes)} sites in {total_time:.2f} seconds")
        print(f"Sites scraped: {[get_domain(site['url']) for site in successful_scrapes]}")
        print(f"="*60)
        return successful_scrapes[:max_sites]
    else:
        print(f"\n" + "="*60)
        print(f"FAILED: Unable to scrape any site after all attempts ({total_time:.2f} seconds)")
        print(f"Data pulling is not possible for this query.")
        print(f"="*60)
        return None

# def try_scrape_smart_with_better_timeout(url, timeout_seconds=15):
#     """Enhanced scraping with strict timeout control - max 15 seconds"""
#     start_time = time.time()
#     print(f"    Starting {get_domain(url)} at {time.strftime('%H:%M:%S')}")
    
#     # Hard limit - if we exceed this, return None immediately
#     hard_timeout = min(timeout_seconds, 15)  # Never exceed 15 seconds
    
#     try:
#         # Try requests first with strict timeout
#         try:
#             response = requests.get(
#                 url, 
#                 timeout=hard_timeout - 1,  # Leave 1 second for processing
#                 headers={
#                     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
#                 }
#             )
            
#             # Check if we're running out of time
#             if time.time() - start_time > hard_timeout - 2:
#                 print(f"    ⏰ {get_domain(url)} approaching timeout, skipping content extraction")
#                 return None
            
#             if response.ok:
#                 smart_content = extract_smart_content(response.text, url)
#                 if smart_content and (smart_content.get("main_content") or smart_content.get("key_sections")):
#                     elapsed = time.time() - start_time
#                     print(f"    ✓ {get_domain(url)} completed in {elapsed:.2f}s")
#                     return {"url": url, "method": "requests+smart", "content": smart_content}
        
#         except requests.exceptions.RequestException as e:
#             print(f"    ✗ {get_domain(url)} requests failed: {str(e)[:50]}...")
        
#         # Check timeout before trying trafilatura
#         if time.time() - start_time > hard_timeout - 3:
#             print(f"    ⏰ {get_domain(url)} timeout reached, skipping trafilatura")
#             return None
        
#         # Fallback to trafilatura with remaining time
#         try:
#             remaining_time = hard_timeout - (time.time() - start_time)
#             if remaining_time > 2:  # Only try if we have at least 2 seconds
#                 downloaded = trafilatura.fetch_url(url)
#                 if downloaded:
#                     extracted = trafilatura.extract(downloaded)
#                     if extracted and len(extracted.strip()) > 30:
#                         smart_content = extract_smart_content(downloaded, url)
#                         if smart_content:
#                             elapsed = time.time() - start_time
#                             print(f"    ✓ {get_domain(url)} completed with trafilatura in {elapsed:.2f}s")
#                             return {"url": url, "method": "trafilatura+smart", "content": smart_content}
        
#         except Exception as e:
#             print(f"    ✗ {get_domain(url)} trafilatura failed: {str(e)[:50]}...")
    
#     except Exception as e:
#         print(f"    ✗ {get_domain(url)} general error: {str(e)[:50]}...")
    
#     elapsed = time.time() - start_time
#     print(f"    ✗ {get_domain(url)} failed after {elapsed:.2f}s")
#     return None
from typing import Optional

def try_scrape_smart_with_better_timeout(
    url,
    timeout_seconds: int = 6,
    stop_event: Optional[threading.Event] = None,   # <‑‑ NEW ARG
):
    """Scrape one URL, but bail out immediately if stop_event is set."""
    if stop_event and stop_event.is_set():
        return None

    start_time = time.time()
    domain = get_domain(url)
    print(f"    Starting {domain}")

    hard_timeout = timeout_seconds
    try:
        # ---------- first attempt: requests ----------
        if stop_event and stop_event.is_set():
            return None

        resp = requests.get(
            url,
            timeout=hard_timeout - 1,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if stop_event and stop_event.is_set():
            return None

        if resp.ok:
            smart = extract_smart_content(resp.text, url)
            if smart and (smart.get("main_content") or smart.get("key_sections")):
                print(f"    ✓ {domain} completed in {time.time()-start_time:.2f}s")
                return {"url": url, "method": "requests+smart", "content": smart}

        # ---------- fallback: trafilatura ----------
        if stop_event and stop_event.is_set():
            return None

        remaining = hard_timeout - (time.time() - start_time)
        if remaining > 2:
            downloaded = trafilatura.fetch_url(url)
            if stop_event and stop_event.is_set():
                return None
            if downloaded:
                smart = extract_smart_content(downloaded, url)
                if smart:
                    print(f"    ✓ {domain} trafilatura in {time.time()-start_time:.2f}s")
                    return {"url": url, "method": "trafilatura+smart", "content": smart}

    except Exception as e:
        print(f"    ✗ {domain} error: {str(e)[:40]}")

    return None

# def scrape_batch_parallel(
#     urls,
#     timeout_per_site: int = 6,          # ← 6 s instead of 15 s
#     batch_name: str = "Batch",
#     max_sites_needed: int = 2,
# ):
#     """Scrape a batch of URLs in parallel, but abort _immediately_ when
#     enough successes are collected and don't wait for slow threads."""
#     print(f"  {batch_name}: Processing {len(urls)} sites "
#           f"with {timeout_per_site}s hard timeout each")
#     print(f"  Target domains: {[get_domain(u) for u in urls]}")

#     successful = []
#     batch_start = time.time()

#     # ----- create executor WITHOUT a `with` block -----
#     executor = concurrent.futures.ThreadPoolExecutor(
#         max_workers=min(len(urls), 5),  # tune as you wish
#         thread_name_prefix="scraper"
#     )
#     future_to_url = {
#         executor.submit(
#             try_scrape_smart_with_better_timeout, url, timeout_per_site
#         ): url
#         for url in urls
#     }

#     try:
#         # poll every 0.25 s until enough sites or global batch deadline
#         deadline = batch_start + timeout_per_site
#         while future_to_url and time.time() < deadline:
#             done, _ = concurrent.futures.wait(
#                 future_to_url.keys(),
#                 timeout=0.25,
#                 return_when=concurrent.futures.FIRST_COMPLETED,
#             )

#             for fut in done:
#                 url = future_to_url.pop(fut)
#                 try:
#                     res = fut.result()
#                     if res:
#                         successful.append(res)
#                         print(f"  ✓ {get_domain(url)} "
#                               f"completed in {time.time()-batch_start:.2f}s "
#                               f"({len(successful)}/{max_sites_needed})")
#                         # ---- EARLY TERMINATION ----
#                         if len(successful) >= max_sites_needed:
#                             elapsed = time.time() - batch_start
#                             print(f"  🎯 {batch_name} EARLY SUCCESS: "
#                                   f"{len(successful)} sites in {elapsed:.2f}s – returning")
#                             executor.shutdown(wait=False,
#                                               cancel_futures=True)
#                             return successful
#                 except Exception as exc:
#                     print(f"  ✗ {get_domain(url)} error: {str(exc)[:40]}")

#         # batch finished (timeout or all tasks done)
#     finally:
#         # make sure we never block on slow threads
#         executor.shutdown(wait=False, cancel_futures=True)

#     elapsed = time.time() - batch_start
#     print(f"  {batch_name} finished: {len(successful)}/{len(urls)} "
#           f"sites in {elapsed:.2f}s")
#     return successful
def scrape_batch_parallel(
    urls,
    timeout_per_site: int = 6,
    batch_name: str = "Batch",
    max_sites_needed: int = 2,
):
    print(f"  {batch_name}: {len(urls)} sites • {timeout_per_site}s each")
    stop_event = threading.Event()                 # <‑‑ FLAG

    successful, batch_start = [], time.time()
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=min(len(urls), 5), thread_name_prefix="scraper"
    )
    fut_to_url = {
        executor.submit(
            try_scrape_smart_with_better_timeout,
            url,
            timeout_per_site,
            stop_event,                            # <‑‑ PASS FLAG
        ): url for url in urls
    }

    try:
        deadline = batch_start + timeout_per_site
        while fut_to_url and time.time() < deadline:
            done, _ = concurrent.futures.wait(
                fut_to_url.keys(),
                timeout=0.25,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for fut in done:
                url = fut_to_url.pop(fut)
                res = fut.result()
                if res:
                    successful.append(res)
                    print(f"  ✓ {get_domain(url)} "
                          f"({len(successful)}/{max_sites_needed})")
                    if len(successful) >= max_sites_needed:
                        # -------- EARLY SUCCESS --------
                        stop_event.set()           # <‑‑ TELL OTHERS TO STOP
                        executor.shutdown(wait=False, cancel_futures=True)
                        return successful
        # time‑out / no more futures
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    return successful


def scrape_batch_playwright(urls, timeout_per_site=10, batch_name="Playwright Batch", max_sites_needed=2):
    """Scrape a batch of URLs using Playwright in parallel with early termination"""
    if not PLAYWRIGHT_AVAILABLE:
        print(f"  {batch_name}: Playwright not available")
        return []
    
    print(f"  {batch_name}: Processing {len(urls)} sites with {timeout_per_site}s timeout each")
    print(f"  Target domains: {[get_domain(url) for url in urls]}")
    
    successful_scrapes = []
    batch_start = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(urls)) as executor:
        # Submit all URLs for parallel Playwright processing
        future_to_url = {
            executor.submit(try_playwright_scrape_smart, url, timeout_per_site): url 
            for url in urls
        }
        
        # Wait for results with early termination
        total_timeout = timeout_per_site + 3  # Add 3 seconds buffer for Playwright
        
        try:
            for future in concurrent.futures.as_completed(future_to_url, timeout=total_timeout):
                url = future_to_url[future]
                try:
                    result = future.result()
                    if result:
                        successful_scrapes.append(result)
                        elapsed = time.time() - batch_start
                        print(f"  ✓ {get_domain(url)} completed in {elapsed:.2f}s ({len(successful_scrapes)}/{max_sites_needed})")
                        
                        # EARLY TERMINATION: Stop as soon as we have enough sites
                        if len(successful_scrapes) >= max_sites_needed:
                            print(f"  🎯 {batch_name} EARLY SUCCESS: Got {len(successful_scrapes)} sites in {elapsed:.2f}s - Stopping!")
                            # Cancel remaining futures
                            for remaining_future in future_to_url:
                                remaining_future.cancel()
                            break
                    else:
                        elapsed = time.time() - batch_start
                        print(f"  ✗ {get_domain(url)} failed after {elapsed:.2f}s")
                except Exception as e:
                    elapsed = time.time() - batch_start
                    print(f"  ✗ {get_domain(url)} error: {str(e)[:30]}...")
        
        except concurrent.futures.TimeoutError:
            elapsed = time.time() - batch_start
            print(f"  ⏰ {batch_name} timeout after {elapsed:.2f}s")
            # Cancel remaining futures
            for future in future_to_url:
                future.cancel()
    
    elapsed = time.time() - batch_start
    print(f"  {batch_name} completed: {len(successful_scrapes)}/{len(urls)} sites in {elapsed:.2f}s")
    return successful_scrapes

def scrape_multiple_sites_truly_parallel(query, max_sites=2, max_total_time=60, max_search_results=15):
    """Enhanced parallel scraping with immediate early termination"""
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
    
    successful_scrapes = []
    
    # PHASE 1: Try first 8 sites with aggressive timeout (15 seconds max)
    print(f"\n=== PHASE 1: First 8 sites (15 seconds max) ===")
    batch_1_urls = filtered_urls[:8]
    if batch_1_urls:
        batch_results = scrape_batch_parallel(batch_1_urls, timeout_per_site=15, batch_name="Batch 1", max_sites_needed=max_sites)
        successful_scrapes.extend(batch_results)
        
        if len(successful_scrapes) >= max_sites:
            total_time = time.time() - total_start
            print(f"✓ Got {len(successful_scrapes)} sites from Phase 1 in {total_time:.2f}s - SUCCESS!")
            return successful_scrapes[:max_sites]
    
    # PHASE 2: Try next 5 sites if we need more (12 seconds max)
    if len(successful_scrapes) < max_sites and len(filtered_urls) > 8:
        print(f"\n=== PHASE 2: Next 5 sites (12 seconds max) ===")
        print(f"Current results: {len(successful_scrapes)}, need: {max_sites}")
        
        batch_2_urls = filtered_urls[8:13]
        if batch_2_urls:
            batch_results = scrape_batch_parallel(batch_2_urls, timeout_per_site=12, batch_name="Batch 2", max_sites_needed=max_sites - len(successful_scrapes))
            successful_scrapes.extend(batch_results)
            
            if len(successful_scrapes) >= max_sites:
                total_time = time.time() - total_start
                print(f"✓ Got {len(successful_scrapes)} sites from Phase 2 in {total_time:.2f}s - SUCCESS!")
                return successful_scrapes[:max_sites]
    
    # PHASE 3: Try Playwright for remaining sites (20 seconds max)
    if len(successful_scrapes) < max_sites and PLAYWRIGHT_AVAILABLE:
        print(f"\n=== PHASE 3: Playwright fallback (20 seconds max) ===")
        print(f"Current results: {len(successful_scrapes)}, need: {max_sites}")
        
        successful_domains = {get_domain(scrape['url']) for scrape in successful_scrapes}
        playwright_urls = [url for url in filtered_urls[:15] 
                          if get_domain(url) not in successful_domains][:5]
        
        if playwright_urls:
            batch_results = scrape_batch_playwright(playwright_urls, timeout_per_site=20, batch_name="Playwright Batch", max_sites_needed=max_sites - len(successful_scrapes))
            successful_scrapes.extend(batch_results)
    
    # Return results
    total_time = time.time() - total_start
    
    if successful_scrapes:
        print(f"\n" + "="*60)
        print(f"SUCCESS: Scraped {len(successful_scrapes)} sites in {total_time:.2f} seconds")
        print(f"Sites scraped: {[get_domain(site['url']) for site in successful_scrapes]}")
        print(f"="*60)
        return successful_scrapes[:max_sites]
    else:
        print(f"\n" + "="*60)
        print(f"FAILED: Unable to scrape any site after all attempts ({total_time:.2f} seconds)")
        print(f"Data pulling is not possible for this query.")
        print(f"="*60)
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

import csv
import json
import time
from datetime import datetime


def scrape_bulk_products_parallel(product_queries, output_csv="bulk_scraping_results.csv", max_sites=2, max_total_time=60):
    """
    Scrape multiple products in bulk using parallel processing and save to CSV
    Fixed to prevent duplicate URLs
    """
    print("Smart Web Scraper - Bulk Parallel Multi-Site Scraping")
    print("=" * 60)
    
    # Prepare CSV file
    csv_headers = ['query', 'site_index', 'url', 'method', 'domain', 'content_type', 'scraped_content', 'total_time', 'status', 'timestamp']
    
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_headers)
        writer.writeheader()
        
        total_products = len(product_queries)
        successful_scrapes = 0
        failed_scrapes = 0
        
        for index, query in enumerate(product_queries, 1):
            print(f"\n{'='*60}")
            print(f"Processing {index}/{total_products}: {query}")
            print(f"{'='*60}")
            
            execution_start = time.time()
            print(f"Starting execution at {time.strftime('%H:%M:%S')}")
            print(f"Target: {max_sites} sites")
            print("-" * 40)
            
            # Use the parallel function for each query
            results = scrape_multiple_sites_parallel(query, max_sites=max_sites, max_total_time=max_total_time)
            
            execution_time = time.time() - execution_start
            
            if results:
                # REMOVE DUPLICATES BASED ON URL
                unique_results = []
                seen_urls = set()
                
                for result in results:
                    url = result['url']
                    if url not in seen_urls:
                        seen_urls.add(url)
                        unique_results.append(result)
                    else:
                        print(f"  ⚠️  Duplicate URL detected and removed: {url}")
                
                # Write each unique result as a separate row
                for site_idx, result in enumerate(unique_results, 1):
                    row_data = {
                        'query': query,
                        'site_index': site_idx,
                        'url': result['url'],
                        'method': result['method'],
                        'domain': result['content'].get('domain', 'unknown'),
                        'content_type': result['content'].get('type', 'unknown'),
                        'scraped_content': json.dumps(result['content'], ensure_ascii=False),
                        'total_time': f"{execution_time:.2f}",
                        'status': 'SUCCESS',
                        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    
                    writer.writerow(row_data)
                    csvfile.flush()  # Ensure data is written immediately
                
                successful_scrapes += 1
                
                print(f"✓ SUCCESS: {len(unique_results)} unique sites scraped (removed {len(results) - len(unique_results)} duplicates)")
                for site_idx, result in enumerate(unique_results, 1):
                    print(f"  Site {site_idx}: {result['url']} ({result['method']})")
                print(f"  Total Time: {execution_time:.2f}s")
                print(f"  Parallel efficiency: {execution_time:.2f}s for {len(unique_results)} sites")
            else:
                # Write failed attempt
                row_data = {
                    'query': query,
                    'site_index': 0,
                    'url': '',
                    'method': '',
                    'domain': '',
                    'content_type': '',
                    'scraped_content': '',
                    'total_time': f"{execution_time:.2f}",
                    'status': 'FAILED',
                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
                writer.writerow(row_data)
                csvfile.flush()
                
                failed_scrapes += 1
                
                print(f"✗ FAILED: Could not scrape any site")
                print(f"  Time: {execution_time:.2f}s")
            
            # Progress summary
            print(f"\nProgress: {index}/{total_products} completed")
            print(f"Success: {successful_scrapes}, Failed: {failed_scrapes}")
            
            # Small delay between requests to be respectful
            if index < total_products:
                time.sleep(2)  # Slightly longer delay for bulk processing
    
    print(f"\n{'='*60}")
    print(f"BULK PARALLEL SCRAPING COMPLETED")
    print(f"Total Products: {total_products}")
    print(f"Successful: {successful_scrapes}")
    print(f"Failed: {failed_scrapes}")
    print(f"Success Rate: {(successful_scrapes/total_products)*100:.1f}%")
    print(f"Results saved to: {output_csv}")
    print(f"{'='*60}")


if __name__ == "__main__":
    # Your product queries list
    product_queries = [
    "Apple iPhone 17 Pro", "Google Pixel 10 Pro", "Xiaomi 15 Ultra", "OnePlus 14", 
    "Oppo Find X8 Pro", "Vivo X100 Pro+", "Huawei Mate 60 RS", "Sony Xperia 1 VI", 
    "Nokia 10 PureView", "Samsung Galaxy Z Fold 7", "OnePlus 13R", "Apple iPhone 17 Air", 
    "Samsung Galaxy S25 Slim", "Motorola Razr+ (2025)", "Xiaomi Mix Fold 4", "Honor Magic V3",
    "Apple MacBook Pro 2025 (M5)", "Dell XPS 15 (2025)", "Lenovo ThinkPad X1 Carbon Gen 13", 
    "HP Spectre x360 14 (2025)", "ASUS ZenBook Pro Duo 15 OLED (2025)", "Microsoft Surface Laptop 6", 
    "Razer Blade 17 (2025)", "Acer Predator Helios 300 (2025)", "Gigabyte Aero 17 (2025)", 
    "MSI Creator Z17 HX Studio (2025)", "Apple MacBook Air 15 (M4, 2025)", "Lenovo Yoga 9i Gen 9 (2025)", 
    "HP Spectre x360 16 (2025)", "Hisense 136-inch MicroLED TV", "Samsung 85-inch S95F OLED", 
    "TCL QM891G Mini-LED", "Sony Bravia 9 Mini-LED", "LG OLED evo G4 97-inch", 
    "Sony Bravia XR A95M 8K OLED", "Ducati Hypermotard 698 Mono", "BMW R 1300 GS", 
    "Buell Super Cruiser", "KTM 990 Duke", "Royal Enfield Himalayan 450", "Kawasaki Ninja ZX-4R", 
    "Honda CB1000 Hornet", "MV Agusta LXP Orioli", "Triumph Speed 400", "Yamaha YZF-R3", 
    "Aprilia Tuono V4 Factory (2025)", "Ducati Streetfighter V4 Lamborghini (2025)", 
    "Mother Science Retinol Synergist", "Kora Organics Turmeric Glow Moisturizer", 
    "Dr. Dennis Gross Skincare DRx SpectraLite FaceWare Pro", "Charlotte Tilbury Magic Water Cream", 
    "Glow Recipe Watermelon Glow Niacinamide Dew Drops", "The Inkey List Hyaluronic Acid Serum", 
    "Glow Recipe Plum Plump Hyaluronic Acid Moisturizer", "Laneige Water Bank Blue Hyaluronic Serum", 
    "Tatcha Violet-C Brightening Serum", "Ralph Lauren Sullivan Slim Stretch Jean", 
    "Citizens of Humanity Gage Slim Straight Jean", "Men’s Lee 101 Z Regular Fit Straight Leg Jean", 
    "Frame Le High Flare Jeans", "AGOLDE Riley Bootcut Jeans", "Still Here The Classic Straight Jean", 
    "Nudie Jeans Dry On Raw", "Everlane The '90s Cheeky Jean", "Levi's Wedgie Straight Jeans", 
    "Bonobos Dress Pant", "best smartphones 2025", "top laptops of 2025", "new TVs released in 2025", 
    "latest motorcycle models 2025", "new skincare products 2025", "trending jeans styles 2025", 
    "best tech gadgets 2025", "upcoming electronic devices 2025", "new fashion trends 2025", 
    "hottest beauty products 2025", "best selling products on Amazon 2025", 
    "top rated products on Best Buy 2025", "new arrivals in electronics 2025", 
    "latest in home entertainment 2025", "best new motorcycles for adventure riding 2025", 
    "top skincare routines for 2025", "must-have fashion items for 2025", 
    "cutting-edge technology products 2025", "innovative beauty tools 2025", 
    "best denim brands for 2025", "luxury watches released in 2025", "new smart home devices 2025", 
    "best fitness trackers of 2025", "top gaming consoles and accessories 2025", 
    "latest in sustainable fashion 2025", "best cameras for photography 2025", 
    "new audio equipment for audiophiles 2025", "trending accessories for 2025", 
    "best kitchen appliances of 2025", "top travel gear for 2025"
]
    print("Choose an option:")
    print("1. Run all products (bulk processing)")
    print("2. Run a subset of products")
    print("3. Run single query (interactive)")
    
    choice = input("Enter your choice (1-3): ").strip()
    
    if choice == "1":
        # Run all products
        scrape_bulk_products_parallel(product_queries, max_sites=2, max_total_time=60)
    
    elif choice == "2":
        # Run subset
        start_idx = int(input("Enter start index (0-based): "))
        end_idx = int(input("Enter end index (0-based): "))
        subset = product_queries[start_idx:end_idx+1]
        print(f"Running {len(subset)} products...")
        scrape_bulk_products_parallel(subset, output_csv=f"subset_scraping_results_{start_idx}_{end_idx}.csv", max_sites=2, max_total_time=60)
    
    elif choice == "3":
        # Single query (original behavior)
        query = input("Enter your search query: ").strip()
        num_sites = 2
        
        execution_start = time.time()
        print(f"\nStarting execution at {time.strftime('%H:%M:%S')}")
        print(f"Target: {num_sites} sites")
        print("=" * 60)
        
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
                        if value:
                            print(f"{key.replace('_', ' ').title()}:")
                            for item in value:
                                print(f"  • {item}")
                            print()
                    elif isinstance(value, dict):
                        if value:
                            print(f"{key.replace('_', ' ').title()}:")
                            for k, v in value.items():
                                print(f"  {k}: {v}")
                            print()
                    elif value:
                        print(f"{key.replace('_', ' ').title()}: {value}")
                        print()
                
                if idx < len(results):
                    print("\n" + "="*60)
        else:
            print("Failed to scrape any site.")
        
        print(f"\n" + "="*60)
        print(f"EXECUTION SUMMARY:")
        print(f"Query: '{query}'")
        print(f"Sites scraped: {len(results) if results else 0}/{num_sites}")
        print(f"Total execution time: {execution_time:.2f} seconds")
        print(f"="*60)
    
    else:
        print("Invalid choice. Please run the script again.")
