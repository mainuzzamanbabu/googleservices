from duckduckgo_search import DDGS
import trafilatura
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import time

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

def get_domain(url):
    return urlparse(url).netloc.lower().replace('www.', '')

def extract_body_content(html):
    soup = BeautifulSoup(html, "lxml")
    body = soup.body
    return body.get_text(separator="\n", strip=True) if body else ""

def extract_amazon_details(html):
    soup = BeautifulSoup(html, "lxml")
    result = {}
    title = soup.find(id="productTitle")
    if title:
        result["title"] = title.get_text(strip=True)
    bullets = soup.select("#feature-bullets ul li span")
    if bullets:
        result["features"] = [b.get_text(strip=True) for b in bullets if b.get_text(strip=True)]
    desc = soup.find(id="productDescription")
    if desc:
        result["description"] = desc.get_text(strip=True)
    specs = {}
    for table_id in ["productDetails_techSpec_section_1", "productDetails_detailBullets_sections1"]:
        table = soup.find(id=table_id)
        if table:
            for row in table.find_all("tr"):
                th = row.find("th")
                td = row.find("td")
                if th and td:
                    specs[th.get_text(strip=True)] = td.get_text(strip=True)
    if specs:
        result["specs"] = specs
    return result

def try_scrape(url):
    # Try trafilatura
    downloaded = trafilatura.fetch_url(url)
    if downloaded:
        extracted = trafilatura.extract(downloaded)
        if extracted and len(extracted.strip()) > 30 and 'continue shopping' not in extracted.lower():
            return {"url": url, "method": "trafilatura", "content": extracted}
    # Try requests + bs4 body
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if resp.ok:
            body = extract_body_content(resp.text)
            if body and len(body.strip()) > 30 and 'continue shopping' not in body.lower():
                # If Amazon, extract structured info
                if "amazon." in url:
                    details = extract_amazon_details(resp.text)
                    if details:
                        return {"url": url, "method": "bs4+amazon", "content": details}
                return {"url": url, "method": "bs4", "content": body}
    except Exception:
        pass
    # Can't scrape normally
    return None

def try_playwright_scrape(url):
    if not PLAYWRIGHT_AVAILABLE:
        print(f"Playwright not installed. Can't scrape JS-heavy site: {url}")
        return None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, timeout=25000)
            time.sleep(4)
            html = page.content()
            if "amazon." in url:
                details = extract_amazon_details(html)
                if details:
                    return {"url": url, "method": "playwright+amazon", "content": details}
            else:
                body = extract_body_content(html)
                if body and len(body.strip()) > 30:
                    return {"url": url, "method": "playwright", "content": body}
        except Exception as e:
            print(f"Playwright error: {e}")
        finally:
            browser.close()
    return None

def scrape_top_sites(query, max_results=10):
    """
    Scrapes up to 2 unique top sites for the given search query, using Playwright only if necessary.
    Returns a list of dictionaries with url, method, and content keys.
    """
    # Get search results
    with DDGS() as ddgs:
        results = [r for r in ddgs.text(query, max_results=max_results)]
    # Remove duplicate domains (only first of each)
    seen_domains = set()
    filtered_results = []
    for result in results:
        domain = get_domain(result['href'])
        if domain not in seen_domains:
            filtered_results.append(result['href'])
            seen_domains.add(domain)
    # Try scraping the top 2 sites
    normal_scraped = []
    failed_js_needed = []
    for url in filtered_results[:2]:
        scraped = try_scrape(url)
        if scraped:
            normal_scraped.append(scraped)
        else:
            failed_js_needed.append(url)
        if len(normal_scraped) == 2:
            break
    # If less than 2, try more up to top 5 unique domains
    i = 2
    while len(normal_scraped) < 2 and i < min(len(filtered_results), 5):
        url = filtered_results[i]
        scraped = try_scrape(url)
        if scraped and get_domain(url) not in [get_domain(x['url']) for x in normal_scraped]:
            normal_scraped.append(scraped)
        else:
            failed_js_needed.append(url)
        i += 1
    # If still less than 2, try Playwright *only for the URLs that failed and not already done*
    if len(normal_scraped) < 2 and PLAYWRIGHT_AVAILABLE:
        for url in failed_js_needed:
            if get_domain(url) not in [get_domain(x['url']) for x in normal_scraped]:
                scraped = try_playwright_scrape(url)
                if scraped:
                    normal_scraped.append(scraped)
                if len(normal_scraped) == 2:
                    break
    return normal_scraped

if __name__ == "__main__":
    query = input("Enter your search query: ").strip()
    results = scrape_top_sites(query)
    if results:
        for s in results:
            print("\n" + "="*60)
            print(f"URL: {s['url']}")
            print(f"Method: {s['method']}")
            content = s['content']
            if isinstance(content, dict):
                for k, v in content.items():
                    print(f"{k.capitalize()}: {v}\n")
            else:
                print(f"Content: {content[:1000]}...\n")
    else:
        print("\nNot enough high-quality data found from top unique sites.")


