# Method 1: Using Google Custom Search API (Recommended)
import requests
import json
from bs4 import BeautifulSoup
import time

class WebSearchExtractor:
    def __init__(self, api_key=None, search_engine_id=None):
        self.api_key = api_key
        self.search_engine_id = search_engine_id
    
    def google_custom_search(self, query, num_results=4):
        """
        Uses Google Custom Search API to get search results
        You need to get API key from Google Cloud Console and create a Custom Search Engine
        """
        if not self.api_key or not self.search_engine_id:
            print("Please set up Google Custom Search API credentials")
            return []
        
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            'key': self.api_key,
            'cx': self.search_engine_id,
            'q': query,
            'num': num_results
        }
        
        try:
            response = requests.get(url, params=params)
            data = response.json()
            
            results = []
            if 'items' in data:
                for item in data['items']:
                    results.append({
                        'title': item.get('title', ''),
                        'url': item.get('link', ''),
                        'snippet': item.get('snippet', '')
                    })
            return results
        except Exception as e:
            print(f"Error in Google Custom Search: {e}")
            return []
    
    def extract_page_content(self, url):
        """
        Extracts content from a webpage
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get text content
            text = soup.get_text()
            
            # Clean up text
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            return {
                'url': url,
                'title': soup.title.string if soup.title else 'No title',
                'content': text[:2000],  # First 2000 characters
                'word_count': len(text.split())
            }
        except Exception as e:
            return {
                'url': url,
                'error': str(e),
                'content': None
            }
    
    def search_and_extract(self, query, num_results=4):
        """
        Complete workflow: search and extract content
        """
        print(f"Searching for: {query}")
        
        # Get search results
        search_results = self.google_custom_search(query, num_results)
        
        if not search_results:
            print("No search results found")
            return []
        
        # Extract content from each result
        extracted_data = []
        for i, result in enumerate(search_results, 1):
            print(f"Extracting content from result {i}: {result['url']}")
            content_data = self.extract_page_content(result['url'])
            
            # Combine search result info with extracted content
            combined_data = {
                'rank': i,
                'search_title': result['title'],
                'search_snippet': result['snippet'],
                'url': result['url'],
                'extracted_title': content_data.get('title'),
                'extracted_content': content_data.get('content'),
                'word_count': content_data.get('word_count'),
                'extraction_error': content_data.get('error')
            }
            extracted_data.append(combined_data)
            
            # Be respectful to servers
            time.sleep(1)
        
        return extracted_data


# Method 2: Alternative using DuckDuckGo Search (No API key required)
from duckduckgo_search import DDGS

class DuckDuckGoSearchExtractor:
    def __init__(self):
        self.ddgs = DDGS()
    
    def search_and_extract(self, query, num_results=4):
        """
        Search using DuckDuckGo and extract content
        """
        print(f"Searching DuckDuckGo for: {query}")
        
        try:
            # Get search results
            results = list(self.ddgs.text(query, max_results=num_results))
            
            extracted_data = []
            for i, result in enumerate(results, 1):
                print(f"Extracting content from result {i}: {result['href']}")
                
                # Extract page content
                content_data = self.extract_page_content(result['href'])
                
                combined_data = {
                    'rank': i,
                    'search_title': result['title'],
                    'search_snippet': result['body'],
                    'url': result['href'],
                    'extracted_title': content_data.get('title'),
                    'extracted_content': content_data.get('content'),
                    'word_count': content_data.get('word_count'),
                    'extraction_error': content_data.get('error')
                }
                extracted_data.append(combined_data)
                
                time.sleep(1)
            
            return extracted_data
            
        except Exception as e:
            print(f"Error in DuckDuckGo search: {e}")
            return []
    
    def extract_page_content(self, url):
        """
        Same as above method
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            for script in soup(["script", "style"]):
                script.decompose()
            
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            return {
                'url': url,
                'title': soup.title.string if soup.title else 'No title',
                'content': text[:2000],
                'word_count': len(text.split())
            }
        except Exception as e:
            return {
                'url': url,
                'error': str(e),
                'content': None
            }


# Usage Examples
if __name__ == "__main__":
    # Example 1: Using Google Custom Search (requires API setup)
    print("=== Google Custom Search Example ===")
    google_extractor = WebSearchExtractor(
        api_key="YOUR_GOOGLE_API_KEY",  # Replace with your API key
        search_engine_id="YOUR_SEARCH_ENGINE_ID"  # Replace with your Search Engine ID
    )
    
    # results = google_extractor.search_and_extract("Python web scraping", 3)
    
    # Example 2: Using DuckDuckGo (no API key needed)
    print("=== DuckDuckGo Search Example ===")
    ddg_extractor = DuckDuckGoSearchExtractor()
    
    # Uncomment to run
    # results = ddg_extractor.search_and_extract("machine learning tutorials", 3)
    # 
    # # Display results
    # for result in results:
    #     print(f"\n--- Result {result['rank']} ---")
    #     print(f"Title: {result['search_title']}")
    #     print(f"URL: {result['url']}")
    #     print(f"Snippet: {result['search_snippet'][:100]}...")
    #     if result['extracted_content']:
    #         print(f"Content Preview: {result['extracted_content'][:200]}...")
    #         print(f"Word Count: {result['word_count']}")
    #     else:
    #         print(f"Extraction Error: {result.get('extraction_error', 'Unknown error')}")


# Required packages to install:
# pip install requests beautifulsoup4 duckduckgo-search

# For Google Custom Search API setup:
# 1. Go to Google Cloud Console
# 2. Enable Custom Search API
# 3. Create credentials (API key)
# 4. Create a Custom Search Engine at https://cse.google.com/
# 5. Get the Search Engine ID