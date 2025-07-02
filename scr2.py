from duckduckgo_search import DDGS
import trafilatura

# Define your search query
query = "example search"

# Search DuckDuckGo and get the first 10 results
with DDGS() as ddgs:
    results = [r for r in ddgs.text(query, max_results=10)]

# Extract URLs from the search results
urls = [result['href'] for result in results]

# Scrape main content from each URL one by one
for url in urls:
    # Fetch the webpage
    downloaded = trafilatura.fetch_url(url)
    if downloaded:
        # Extract the main content, ignoring navbars, footers, etc.
        extracted = trafilatura.extract(downloaded)
        if extracted:
            print(f"Content from {url}:\n{extracted}\n")
        else:
            print(f"Failed to extract content from {url}")
    else:
        print(f"Failed to fetch {url}")