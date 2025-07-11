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
import concurrent.futures
import threading

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Enhanced blacklist with performance categories
BLACKLIST_DOMAINS = {
    'lenovo.com', 'daraz.com.bd', 'reddit', 'ibm.com', 'oracle.com',
    'salesforce.com', 'microsoft.com', 'adobe.com', 'sap.com',
    'workday.com', 'servicenow.com', 'tableau.com', 'zoom.us',
    'webex.com', 'gotomeeting.com'
}

# Categorize domains by expected performance
FAST_DOMAINS = {
    'wikipedia.org', 'britannica.com', 'techcrunch.com', 'theverge.com',
    'engadget.com', 'amazon.com', 'flipkart.com', 'gsmarena.com',
    'phonearena.com', 'androidauthority.com', 'xda-developers.com',
    'notebookcheck.net', 'anandtech.com', 'tomshardware.com',
    'cnet.com', 'zdnet.com', 'pcworld.com', 'techradar.com'
}

MEDIUM_DOMAINS = {
    'youtube.com', 'github.com', 'stackoverflow.com', 'reddit.com',
    'medium.com', 'forbes.com', 'wired.com', 'arstechnica.com',
    'digitaltrends.com', 'mashable.com', 'venturebeat.com'
}

SLOW_DOMAINS = {
    'linkedin.com', 'twitter.com', 'facebook.com', 'instagram.com',
    'tiktok.com', 'pinterest.com', 'snapchat.com'
}

@contextmanager
def timeout_context(seconds):
    """Ultra-fast timeout context manager"""
    timeout_occurred = threading.Event()
    
    def timeout_handler():
        time.sleep(seconds)
        timeout_occurred.set()
    
    timeout_thread = threading.Thread(target=timeout_handler, daemon=True)
    timeout_thread.start()
    
    try:
        yield timeout_occurred
    finally:
        pass

def get_domain(url):
    return urlparse(url).netloc.lower().replace('www.', '')

def is_blacklisted(url):
    """Check if URL domain is in blacklist"""
    domain = get_domain(url)
    return any(blacklisted in domain for blacklisted in BLACKLIST_DOMAINS)

def get_domain_category(url):
    """Categorize domain by expected performance"""
    domain = get_domain(url)
    if any(fast in domain for fast in FAST_DOMAINS):
        return 'fast'
    elif any(medium in domain for medium in MEDIUM_DOMAINS):
        return 'medium'
    elif any(slow in domain for slow in SLOW_DOMAINS):
        return 'slow'
    else:
        return 'unknown'

def clean_text(text):
    """Optimized text cleaning"""
    if not text:
        return ""
    # Single regex for all cleaning
    text = re.sub(r'\s+', ' ', text.strip())
    text = re.sub(r'(cookie|privacy policy|terms of service|subscribe|newsletter)', '', text, flags=re.IGNORECASE)
    return text

def scrape_searxng_local(query, max_results=12):
    """Optimized SearXNG search with shorter timeout"""
    url = "http://localhost:8888/search"
    data = {"q": query, "format": "json"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    try:
        print(f"⚡ Searching SearXNG for: '{query}'")
        response = requests.post(url, data=data, headers=headers, timeout=8)  # Reduced from 15
        response.raise_for_status()
        search_results = response.json()
        
        if not search_results.get('results'):
            print("No results found in SearXNG response")
            return []
        
        results = []
        seen_domains = set()
        
        # Prioritize results by domain category
        fast_results = []
        medium_results = []
        slow_results = []
        unknown_results = []
        
        for result in search_results['results']:
            result_url = result.get('url', '')
            if not result_url or is_blacklisted(result_url):
                continue
                
            domain = get_domain(result_url)
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            
            result_data = {
                'title': result.get('title', 'No title available'),
                'href': result_url,
                'body': result.get('content', 'No description available')
            }
            
            category = get_domain_category(result_url)
            if category == 'fast':
                fast_results.append(result_data)
            elif category == 'medium':
                medium_results.append(result_data)
            elif category == 'slow':
                slow_results.append(result_data)
            else:
                unknown_results.append(result_data)
        
        # Return prioritized results
        results = fast_results + medium_results + unknown_results + slow_results
        results = results[:max_results]
        
        print(f"Found {len(results)} results (Fast: {len(fast_results)}, Medium: {len(medium_results)}, Unknown: {len(unknown_results)}, Slow: {len(slow_results)})")
        return results
        
    except Exception as e:
        print(f"[SearXNG] Error: {e}")
        return []

def extract_quick_content(html, url):
    """Ultra-fast content extraction focusing on essentials only"""
    soup = BeautifulSoup(html, "lxml")
    domain = get_domain(url)
    
    result = {
        "url": url,
        "domain": domain,
        "title": "",
        "main_content": "",
        "type": "generic"
    }
    
    # Quick title extraction
    title_tag = soup.find('title')
    if title_tag:
        result["title"] = clean_text(title_tag.get_text())
    
    # Quick meta description
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc:
        result["summary"] = clean_text(meta_desc.get('content', ''))
    
    # Site-specific quick extraction
    if "amazon." in url:
        return extract_amazon_quick(soup, url)
    elif "gsmarena.com" in url:
        return extract_gsmarena_quick(soup, url)
    elif "wikipedia.org" in url:
        return extract_wikipedia_quick(soup, url)
    else:
        return extract_generic_quick(soup, url)

def extract_amazon_quick(soup, url):
    """Lightning-fast Amazon extraction"""
    result = {"url": url, "domain": "amazon", "type": "product"}
    
    # Title only
    title = soup.find(id="productTitle")
    if title:
        result["title"] = clean_text(title.get_text())
    
    # Price only
    price_selectors = [".a-price-whole", ".a-price .a-offscreen"]
    for selector in price_selectors:
        price = soup.select_one(selector)
        if price:
            result["price"] = clean_text(price.get_text())
            break
    
    # First 2 features only
    bullets = soup.select("#feature-bullets ul li span")
    if bullets:
        result["key_features"] = [clean_text(b.get_text()) for b in bullets[:2]]
    
    return result

def extract_gsmarena_quick(soup, url):
    """Quick GSM Arena extraction"""
    result = {"url": url, "domain": "gsmarena", "type": "phone_spec"}
    
    # Title
    title = soup.find('h1')
    if title:
        result["title"] = clean_text(title.get_text())
    
    # Key specs only
    specs = {}
    spec_tables = soup.select(".specs-phone-name-title, .specs-brief-accent")
    for spec in spec_tables[:3]:  # Only first 3
        text = clean_text(spec.get_text())
        if text:
            specs[f"spec_{len(specs)}"] = text
    
    result["specs"] = specs
    return result

def extract_wikipedia_quick(soup, url):
    """Quick Wikipedia extraction"""
    result = {"url": url, "domain": "wikipedia", "type": "encyclopedia"}
    
    # Title
    title = soup.find('h1')
    if title:
        result["title"] = clean_text(title.get_text())
    
    # First paragraph only
    first_p = soup.select_one("p")
    if first_p:
        summary = clean_text(first_p.get_text())
        result["summary"] = summary[:400] + "..." if len(summary) > 400 else summary
    
    return result

def extract_generic_quick(soup, url):
    """Lightning-fast generic extraction"""
    result = {"url": url, "domain": get_domain(url), "type": "generic"}
    
    # Title
    title = soup.find('title')
    if title:
        result["title"] = clean_text(title.get_text())
    
    # Quick content - only first substantial paragraph
    content_selectors = ["article p", "main p", ".content p", ".post-content p"]
    for selector in content_selectors:
        paragraphs = soup.select(selector)
        if paragraphs:
            for p in paragraphs:
                text = clean_text(p.get_text())
                if len(text) > 50:  # Substantial content
                    result["main_content"] = text[:500] + "..." if len(text) > 500 else text
                    break
            if result.get("main_content"):
                break
    
    return result

def try_ultra_fast_scrape(url, timeout_seconds=3):
    """Ultra-fast scraping with aggressive timeout"""
    start_time = time.time()
    domain = get_domain(url)
    
    print(f"    ⚡ Starting {domain} (timeout: {timeout_seconds}s)")
    
    try:
        # Single attempt with requests - no fallbacks
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            stream=False  # Don't stream to save time
        )
        
        if response.ok:
            # Use quick extraction
            content = extract_quick_content(response.text, url)
            if content and (content.get("title") or content.get("main_content")):
                elapsed = time.time() - start_time
                print(f"    ✅ {domain} SUCCESS in {elapsed:.2f}s")
                return {"url": url, "method": "ultra_fast", "content": content}
    
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"    ❌ {domain} FAILED in {elapsed:.2f}s: {str(e)[:30]}...")
    
    return None

def try_fast_scrape(url, timeout_seconds=4):
    """Fast scraping with trafilatura fallback"""
    start_time = time.time()
    domain = get_domain(url)
    
    print(f"    🔄 Starting {domain} (timeout: {timeout_seconds}s)")
    
    try:
        # Try requests first
        try:
            response = requests.get(url, timeout=timeout_seconds, headers={"User-Agent": "Mozilla/5.0"})
            if response.ok:
                content = extract_quick_content(response.text, url)
                if content and (content.get("title") or content.get("main_content")):
                    elapsed = time.time() - start_time
                    print(f"    ✅ {domain} SUCCESS with requests in {elapsed:.2f}s")
                    return {"url": url, "method": "fast_requests", "content": content}
        except:
            pass
        
        # Quick trafilatura fallback
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            extracted = trafilatura.extract(downloaded)
            if extracted and len(extracted.strip()) > 30:
                content = {"url": url, "domain": domain, "main_content": extracted[:800]}
                elapsed = time.time() - start_time
                print(f"    ✅ {domain} SUCCESS with trafilatura in {elapsed:.2f}s")
                return {"url": url, "method": "fast_trafilatura", "content": content}
    
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"    ❌ {domain} FAILED in {elapsed:.2f}s: {str(e)[:30]}...")
    
    return None

def scrape_batch_ultra_fast(urls, timeout_per_site=3, batch_name="Ultra Fast", max_sites_needed=2):
    """Ultra-fast batch scraping with immediate termination"""
    print(f"  🚀 {batch_name}: Processing {len(urls)} sites ({timeout_per_site}s each)")
    
    successful_scrapes = []
    batch_start = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(urls), 6)) as executor:
        future_to_url = {
            executor.submit(try_ultra_fast_scrape, url, timeout_per_site): url 
            for url in urls
        }
        
        try:
            for future in concurrent.futures.as_completed(future_to_url, timeout=timeout_per_site + 1):
                url = future_to_url[future]
                try:
                    result = future.result()
                    if result:
                        successful_scrapes.append(result)
                        elapsed = time.time() - batch_start
                        print(f"  ✅ Got {len(successful_scrapes)}/{max_sites_needed} in {elapsed:.2f}s")
                        
                        # IMMEDIATE TERMINATION
                        if len(successful_scrapes) >= max_sites_needed:
                            print(f"  🎯 {batch_name} COMPLETE: {len(successful_scrapes)} sites in {elapsed:.2f}s!")
                            # Cancel all remaining futures
                            for f in future_to_url:
                                f.cancel()
                            return successful_scrapes
                except Exception as e:
                    print(f"  ❌ {get_domain(url)} error: {str(e)[:20]}...")
        
        except concurrent.futures.TimeoutError:
            print(f"  ⏰ {batch_name} batch timeout")
    
    elapsed = time.time() - batch_start
    print(f"  {batch_name} completed: {len(successful_scrapes)}/{len(urls)} in {elapsed:.2f}s")
    return successful_scrapes

def scrape_batch_fast(urls, timeout_per_site=4, batch_name="Fast", max_sites_needed=2):
    """Fast batch scraping with fallback methods"""
    print(f"  🔄 {batch_name}: Processing {len(urls)} sites ({timeout_per_site}s each)")
    
    successful_scrapes = []
    batch_start = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(urls), 4)) as executor:
        future_to_url = {
            executor.submit(try_fast_scrape, url, timeout_per_site): url 
            for url in urls
        }
        
        try:
            for future in concurrent.futures.as_completed(future_to_url, timeout=timeout_per_site + 2):
                url = future_to_url[future]
                try:
                    result = future.result()
                    if result:
                        successful_scrapes.append(result)
                        elapsed = time.time() - batch_start
                        print(f"  ✅ Got {len(successful_scrapes)}/{max_sites_needed} in {elapsed:.2f}s")
                        
                        # IMMEDIATE TERMINATION
                        if len(successful_scrapes) >= max_sites_needed:
                            print(f"  🎯 {batch_name} COMPLETE: {len(successful_scrapes)} sites in {elapsed:.2f}s!")
                            for f in future_to_url:
                                f.cancel()
                            return successful_scrapes
                except Exception as e:
                    print(f"  ❌ {get_domain(url)} error: {str(e)[:20]}...")
        
        except concurrent.futures.TimeoutError:
            print(f"  ⏰ {batch_name} batch timeout")
    
    elapsed = time.time() - batch_start
    print(f"  {batch_name} completed: {len(successful_scrapes)}/{len(urls)} in {elapsed:.2f}s")
    return successful_scrapes

def try_playwright_emergency(url, timeout_seconds=8):
    """Emergency Playwright for difficult sites"""
    if not PLAYWRIGHT_AVAILABLE:
        return None
    
    start_time = time.time()
    domain = get_domain(url)
    
    print(f"    🚨 EMERGENCY: {domain} (timeout: {timeout_seconds}s)")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, timeout=timeout_seconds * 1000)
                time.sleep(1)  # Minimal wait
                
                html = page.content()
                content = extract_quick_content(html, url)
                if content and (content.get("title") or content.get("main_content")):
                    elapsed = time.time() - start_time
                    print(f"    ✅ {domain} EMERGENCY SUCCESS in {elapsed:.2f}s")
                    return {"url": url, "method": "emergency_playwright", "content": content}
            finally:
                browser.close()
    
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"    ❌ {domain} EMERGENCY FAILED in {elapsed:.2f}s: {str(e)[:30]}...")
    
    return None

def scrape_multiple_sites_lightning_fast(query, max_sites=2, max_total_time=20):
    """Lightning-fast multi-site scraping with aggressive optimization"""
    total_start = time.time()
    
    print(f"⚡ LIGHTNING SCRAPER: '{query}' (max {max_total_time}s)")
    print("=" * 60)
    
    # Phase 1: Search (max 8 seconds)
    search_start = time.time()
    results = scrape_searxng_local(query, max_results=15)
    search_time = time.time() - search_start
    
    if not results:
        print("❌ No search results")
        return None
    
    print(f"✅ Search completed in {search_time:.2f}s - Found {len(results)} results")
    
    # Filter and categorize URLs
    urls = [result['href'] for result in results]
    fast_urls = []
    medium_urls = []
    other_urls = []
    
    seen_domains = set()
    for url in urls:
        domain = get_domain(url)
        if domain in seen_domains or is_blacklisted(url):
            continue
        seen_domains.add(domain)
        
        category = get_domain_category(url)
        if category == 'fast':
            fast_urls.append(url)
        elif category == 'medium':
            medium_urls.append(url)
        else:
            other_urls.append(url)
    
    print(f"📊 Categorized: Fast({len(fast_urls)}) Medium({len(medium_urls)}) Other({len(other_urls)})")
    
    successful_scrapes = []
    
    # Phase 2: Ultra-fast scraping (fast domains, 3s timeout)
    if fast_urls and len(successful_scrapes) < max_sites:
        print(f"\n🚀 PHASE 2: Ultra-fast scraping ({len(fast_urls)} fast domains)")
        batch_results = scrape_batch_ultra_fast(fast_urls[:6], timeout_per_site=3, 
                                              batch_name="Ultra Fast", max_sites_needed=max_sites)
        successful_scrapes.extend(batch_results)
        
        if len(successful_scrapes) >= max_sites:
            total_time = time.time() - total_start
            print(f"🎯 LIGHTNING SUCCESS: {len(successful_scrapes)} sites in {total_time:.2f}s!")
            return successful_scrapes[:max_sites]
    
    # Phase 3: Fast scraping (medium domains, 4s timeout)
    if medium_urls and len(successful_scrapes) < max_sites:
        print(f"\n🔄 PHASE 3: Fast scraping ({len(medium_urls)} medium domains)")
        remaining_needed = max_sites - len(successful_scrapes)
        batch_results = scrape_batch_fast(medium_urls[:4], timeout_per_site=4, 
                                        batch_name="Fast", max_sites_needed=remaining_needed)
        successful_scrapes.extend(batch_results)
        
        if len(successful_scrapes) >= max_sites:
            total_time = time.time() - total_start
            print(f"🎯 FAST SUCCESS: {len(successful_scrapes)} sites in {total_time:.2f}s!")
            return successful_scrapes[:max_sites]
    
    # Phase 4: Emergency scraping (other domains, 4s timeout)
    if other_urls and len(successful_scrapes) < max_sites:
        print(f"\n🆘 PHASE 4: Emergency scraping ({len(other_urls)} other domains)")
        remaining_needed = max_sites - len(successful_scrapes)
        batch_results = scrape_batch_fast(other_urls[:4], timeout_per_site=4, 
                                        batch_name="Emergency", max_sites_needed=remaining_needed)
        successful_scrapes.extend(batch_results)
        
        if len(successful_scrapes) >= max_sites:
            total_time = time.time() - total_start
            print(f"🎯 EMERGENCY SUCCESS: {len(successful_scrapes)} sites in {total_time:.2f}s!")
            return successful_scrapes[:max_sites]
    
    # Phase 5: Last resort Playwright (max 15s total time check)
    total_elapsed = time.time() - total_start
    if len(successful_scrapes) < max_sites and total_elapsed < 15 and PLAYWRIGHT_AVAILABLE:
        print(f"\n🚨 PHASE 5: Last resort Playwright")
        remaining_urls = (fast_urls + medium_urls + other_urls)[:3]
        scraped_domains = {get_domain(s['url']) for s in successful_scrapes}
        remaining_urls = [url for url in remaining_urls if get_domain(url) not in scraped_domains]
        
        if remaining_urls:
            for url in remaining_urls[:2]:  # Only try 2 sites
                if len(successful_scrapes) >= max_sites:
                    break
                result = try_playwright_emergency(url, timeout_seconds=8)
                if result:
                    successful_scrapes.append(result)
    
    # Final results
    total_time = time.time() - total_start
    
    if successful_scrapes:
        print(f"\n🎯 FINAL RESULT: {len(successful_scrapes)} sites in {total_time:.2f}s")
        return successful_scrapes[:max_sites]
    else:
        print(f"\n❌ FAILED: No sites scraped in {total_time:.2f}s")
        return None

def scrape_bulk_products_lightning(product_queries, output_csv="lightning_scraping_results.csv", max_sites=2):
    """Lightning-fast bulk scraping optimized for sub-6s performance"""
    print("⚡ LIGHTNING WEB SCRAPER - Ultra-Fast Bulk Processing")
    print("=" * 60)
    
    csv_headers = ['query', 'site_index', 'url', 'method', 'domain', 'content_type', 
                   'scraped_content', 'total_time', 'status', 'timestamp']
    
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_headers)
        writer.writeheader()
        
        total_products = len(product_queries)
        successful_scrapes = 0
        failed_scrapes = 0
        under_6s = 0
        under_15s = 0
        over_15s = 0
        
        for index, query in enumerate(product_queries, 1):
            print(f"\n⚡ Processing {index}/{total_products}: {query}")
            print("-" * 40)
            
            execution_start = time.time()
            
            # Use lightning-fast scraping
            results = scrape_multiple_sites_lightning_fast(query, max_sites=max_sites, max_total_time=20)
            
            execution_time = time.time() - execution_start
            
            # Track performance
            if execution_time <= 6:
                under_6s += 1
                status_emoji = "🚀"
            elif execution_time <= 15:
                under_15s += 1
                status_emoji = "⚡"
            else:
                over_15s += 1
                status_emoji = "🐌"
            
            if results:
                # Remove duplicates
                unique_results = []
                seen_urls = set()
                
                for result in results:
                    url = result['url']
                    if url not in seen_urls:
                        seen_urls.add(url)
                        unique_results.append(result)
                
                # Write results
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
                    csvfile.flush()
                
                successful_scrapes += 1
                print(f"{status_emoji} SUCCESS: {len(unique_results)} sites in {execution_time:.2f}s")
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
                print(f"❌ FAILED: {execution_time:.2f}s")
            
            # Progress update
            success_rate = (successful_scrapes / index) * 100
            print(f"Progress: {index}/{total_products} | Success: {success_rate:.1f}% | "
                  f"Under 6s: {under_6s} | Under 15s: {under_15s} | Over 15s: {over_15s}")
            
            # Minimal delay
            if index < total_products:
                time.sleep(0.5)
    
    print(f"\n⚡ LIGHTNING SCRAPING COMPLETED")
    print(f"=" * 60)
    print(f"Total Products: {total_products}")
    print(f"Successful: {successful_scrapes}")
    print(f"Failed: {failed_scrapes}")
    print(f"Success Rate: {(successful_scrapes/total_products)*100:.1f}%")
    print(f"Performance Distribution:")
    print(f"  🚀 Under 6s: {under_6s} ({(under_6s/total_products)*100:.1f}%)")
    print(f"  ⚡ Under 15s: {under_15s} ({(under_15s/total_products)*100:.1f}%)")
    print(f"  🐌 Over 15s: {over_15s} ({(over_15s/total_products)*100:.1f}%)")
    print(f"Results saved to: {output_csv}")
    print(f"=" * 60)
if __name__ == "__main__":
    # Test with sample queries
    test_queries = [
        "Samsung Galaxy S25 Ultra", "Apple iPhone 16 Pro Max", "Google Pixel 9a", 
        "Google Pixel 9 Pro", "OnePlus 13", "Apple iPhone 16", "Nothing Phone 3a Pro", 
        "Samsung Galaxy S25", "Motorola Razr Ultra (2025)", "Samsung Galaxy S25 Edge", 
        "CMF Phone 2 Pro by Nothing", "Google Pixel 9 Pro Fold", "Apple iPhone 16 Plus", 
        "Google Pixel 9", "Samsung Galaxy Z Flip 6", "Apple MacBook Pro 14 (M4, 2024)", 
        "Lenovo ThinkPad X9 15 Aura Edition (2025)", "Acer Swift Go 14 (2024)", 
        "ASUS Vivobook 16 M1605 (2023)", "Lenovo ThinkPad P1 Gen 7 (2024)", 
        "Microsoft Surface Laptop 7th Edition 15 (2024)", "HP OmniBook Ultra Flip 14 (2024)", 
        "ASUS Zenbook 14 OLED (2024)", "ASUS ROG Strix G16 (2024)", 
        "Lenovo Yoga 7 2-in-1 14 (2024)", "ASUS TUF Gaming A16 Advantage Edition (2023)", 
        "ASUS ROG Zephyrus G16 (2024)", "Samsung Galaxy Book4 (2024)", 
        "MSI Katana A15 AI (2024)", "Apple MacBook Air 13 (M4, 2025)", 
        "LG C4 OLED", "Samsung S90D/S90DD OLED", "Sony Bravia XR A95L QD-OLED", 
        "TCL QM8", "Panasonic Z95A Series 4K OLED", "LG G4 OLED", 
        "Sony Bravia XR X95L Mini-LED", "Hisense U8K", "Samsung QN90D QLED", 
        "Vizio P-Series Quantum X", "LG C3 OLED", "Samsung QN85D QLED", 
        "Sony X95K Mini-LED", "TCL 6-Series", "Hisense U7K", "BMW R1300R", 
        "Ducati Panigale V4", "BMW R12", "Triumph Scrambler 1200 XE", "Yamaha MT-09", 
        "KTM 390 Adventure", "BSA Gold Star 650", "Honda CL500", "Aprilia RS 457", 
        "Indian Scout", "Harley-Davidson Sportster S", "Kawasaki Z900", 
        "Suzuki GSX-S1000", "MV Agusta F3", "Ducati Monster", 
        "Augustinus Bader The Rich Cream", "La Roche-Posay Toleriane Double Repair Face Moisturizer", 
        "Sunday Riley Good Genes All-In-One Lactic Acid Treatment", 
        "SkinCeuticals C E Ferulic Serum", "Tatcha The Dewy Skin Cream", 
        "Paula's Choice Skin Perfecting 2% BHA Liquid Exfoliant", 
        "Drunk Elephant Protini Polypeptide Cream", "The Ordinary Hyaluronic Acid 2% + B5", 
        "Kiehl's Midnight Recovery Concentrate", "Clinique Moisture Surge 100H Auto-Replenishing Hydrator", 
        "Tatcha The Water Cream", "CeraVe Hydrating Facial Cleanser", 
        "Estée Lauder Advanced Night Repair Serum", "Neutrogena Hydro Boost Water Gel", 
        "Lancôme Rénergie H.C.F. Triple Serum", "Levi's 501 Jeans", "Alo Cargo Pants", 
        "Abercrombie & Fitch '90s Straight Jeans", "J.Crew 484 Slim-Fit Chinos", 
        "Bonobos Stretch Weekday Warrior Pant", "Everlane The Way-High Slim-Fit Jean", 
        "Todd Snyder The Italian Pant", "Uniqlo Slim-Fit Jeans", 
        "Theory Slim-Fit Stretch Wool Pants", "Rhone 7-inch Commuter Pant", 
        "Banana Republic Aiden Slim-Fit Pant", "Lululemon ABC Pant Classic", 
        "Patagonia Terrebonne Joggers", "Zara Slim-Fit Trousers", "H&M Slim-Fit Chinos"
    ]
    
    
    print("⚡ LIGHTNING SCRAPER TEST")
    print("Choose option:")
    print("1. Test single query")
    print("2. Test bulk queries")
    
    choice = input("Enter choice: ").strip()
    
    if choice == "1":
        query = input("Enter query: ").strip()
        results = scrape_multiple_sites_lightning_fast(query, max_sites=2)
        if results:
            print(f"\n✅ Results: {len(results)} sites scraped")
            for i, result in enumerate(results, 1):
                print(f"{i}. {result['url']} ({result['method']})")
                content = result['content']
                print(f"   Title: {content.get('title', 'N/A')}")
                print(f"   Domain: {content.get('domain', 'N/A')}")
                print(f"   Type: {content.get('type', 'N/A')}")
                if content.get('main_content'):
                    print(f"   Content: {content['main_content'][:100]}...")
                print()
        else:
            print("\n❌ No results found")
    
    elif choice == "2":
        print("\nBulk scraping options:")
        print("1. Use sample queries")
        print("2. Enter custom queries")
        
        bulk_choice = input("Enter choice: ").strip()
        
        if bulk_choice == "1":
            queries = test_queries
        else:
            print("Enter queries (one per line, empty line to finish):")
            queries = []
            while True:
                query = input().strip()
                if not query:
                    break
                queries.append(query)
        
        if queries:
            output_file = input("Enter output CSV filename (press Enter for default): ").strip()
            if not output_file:
                output_file = "lightning_scraping_results.csv"
            
            max_sites = input("Max sites per query (default 2): ").strip()
            try:
                max_sites = int(max_sites) if max_sites else 2
            except ValueError:
                max_sites = 2
            
            print(f"\n🚀 Starting bulk scraping of {len(queries)} queries...")
            scrape_bulk_products_lightning(queries, output_file, max_sites)
        else:
            print("❌ No queries provided")
    
    else:
        print("❌ Invalid choice")
        
    print("\n⚡ Lightning Scraper session completed!")