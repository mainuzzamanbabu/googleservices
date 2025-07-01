"""
Fetch & summarise top Google results using SerpAPI (100 free calls/day).
Usage:  python google_fetch.py "your search phrase"
"""
import os, sys, textwrap, requests, tldextract
from bs4 import BeautifulSoup
from readability import Document
from serpapi  import GoogleSearch

API_KEY = os.getenv("SERPAPI_API_KEY")
if not API_KEY:
    sys.exit("❌  Set SERPAPI_API_KEY env-var first")

def strip_html(url: str) -> str:
    html = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}).text
    doc  = Document(html)
    soup = BeautifulSoup(doc.summary(), "lxml")
    return soup.get_text(" ", strip=True)

def google_search(query: str, k: int = 4):
    params = {"engine":"google","q":query,"api_key":API_KEY,"num":k}
    results = GoogleSearch(params).get_dict()
    return [item["link"] for item in results.get("organic_results", [])[:k]]

def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python google_fetch.py \"search phrase\"")
    query = " ".join(sys.argv[1:])
    for i, url in enumerate(google_search(query), 1):
        try:
            text = strip_html(url)[:800] + "…"
            host = tldextract.extract(url).registered_domain
            print(f"\n{i}. {host} – {url}\n" + textwrap.fill(text, 100))
        except Exception as e:
            print(f"\n{i}. ⚠️  Skipped {url} ({e})")
if __name__ == "__main__":
    main()
