import requests
from bs4 import BeautifulSoup
import time
import random
from urllib.parse import urljoin, urlparse
import json
from dataclasses import dataclass
from typing import List, Dict, Optional
import re
from readability import Document
import trafilatura
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ScrapedContent:
    url: str
    title: str
    content: str
    status_code: int
    success: bool
    error_message: Optional[str] = None
    word_count: int = 0
    
class AdvancedWebScraper:
    def __init__(self):
        self.session = requests.Session()
        # Rotate user agents to avoid detection
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        ]
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })
    
    def search_duckduckgo(self, query: str, num_results: int = 10) -> List[str]:
        """
        Search DuckDuckGo and return list of URLs
        """
        try:
            # DuckDuckGo instant answers API
            search_url = "https://html.duckduckgo.com/html/"
            params = {
                'q': query,
                'b': '',  # Start from beginning
                'kl': 'us-en',  # Language
                'df': '',  # Date filter
                's': '0',   # Start position
            }
            
            headers = {
                'User-Agent': random.choice(self.user_agents)
            }
            
            response = self.session.get(search_url, params=params, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract URLs from search results
            urls = []
            result_links = soup.find_all('a', {'class': 'result__a'})
            
            for link in result_links[:num_results]:
                href = link.get('href')
                if href and href.startswith('http'):
                    urls.append(href)
            
            logger.info(f"Found {len(urls)} URLs from DuckDuckGo search")
            return urls
            
        except Exception as e:
            logger.error(f"Error searching DuckDuckGo: {str(e)}")
            return []
    
    def is_valid_response(self, response: requests.Response) -> bool:
        """
        Check if response is valid for scraping
        """
        if response.status_code != 200:
            return False
        
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' not in content_type:
            return False
        
        # Check if content is not empty
        if len(response.content) < 100:
            return False
        
        return True
    
    def extract_content_trafilatura(self, html: str, url: str) -> Optional[str]:
        """
        Extract main content using trafilatura (best for news articles and blogs)
        """
        try:
            extracted = trafilatura.extract(html, include_comments=False, 
                                          include_tables=True, include_images=False)
            return extracted
        except:
            return None
    
    def extract_content_readability(self, html: str, url: str) -> Optional[str]:
        """
        Extract main content using readability (Mozilla's algorithm)
        """
        try:
            doc = Document(html)
            soup = BeautifulSoup(doc.content(), 'html.parser')
            return soup.get_text(strip=True, separator=' ')
        except:
            return None
    
    def extract_content_manual(self, soup: BeautifulSoup, url: str) -> str:
        """
        Manual content extraction with advanced filtering
        """
        # Remove unwanted elements
        unwanted_tags = [
            'nav', 'header', 'footer', 'aside', 'script', 'style', 
            'noscript', 'iframe', 'form', 'button', 'input',
            'advertisement', 'ad', 'sidebar', 'menu'
        ]
        
        unwanted_classes = [
            'nav', 'navbar', 'navigation', 'header', 'footer', 'sidebar',
            'menu', 'ad', 'advertisement', 'ads', 'social', 'share',
            'comment', 'comments', 'related', 'recommended', 'popup',
            'modal', 'cookie', 'subscribe', 'newsletter'
        ]
        
        unwanted_ids = [
            'header', 'footer', 'nav', 'navbar', 'sidebar', 'menu',
            'advertisement', 'ads', 'social', 'comments'
        ]
        
        # Remove by tag name
        for tag in unwanted_tags:
            for element in soup.find_all(tag):
                element.decompose()
        
        # Remove by class name (partial matching)
        for class_name in unwanted_classes:
            for element in soup.find_all(class_=re.compile(class_name, re.I)):
                element.decompose()
        
        # Remove by ID (partial matching)
        for id_name in unwanted_ids:
            for element in soup.find_all(id=re.compile(id_name, re.I)):
                element.decompose()
        
        # Find main content containers
        main_content_selectors = [
            'main', 'article', '[role="main"]', '.main-content',
            '.content', '.post-content', '.entry-content', '.article-body',
            '.story-body', '.article-content', '#content', '#main'
        ]
        
        content_text = ""
        
        # Try to find main content container
        for selector in main_content_selectors:
            main_container = soup.select_one(selector)
            if main_container:
                content_text = main_container.get_text(strip=True, separator=' ')
                if len(content_text) > 100:  # Minimum content length
                    break
        
        # Fallback: extract from body if main content not found
        if not content_text or len(content_text) < 100:
            body = soup.find('body')
            if body:
                content_text = body.get_text(strip=True, separator=' ')
        
        # Clean up the text
        content_text = re.sub(r'\s+', ' ', content_text)  # Multiple spaces to single
        content_text = re.sub(r'\n+', '\n', content_text)  # Multiple newlines to single
        
        return content_text.strip()
    
    def scrape_url(self, url: str) -> ScrapedContent:
        """
        Scrape a single URL with advanced content extraction
        """
        try:
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Referer': 'https://www.google.com/',
            }
            
            # Add random delay to avoid being blocked
            time.sleep(random.uniform(1, 3))
            
            logger.info(f"Scraping: {url}")
            response = self.session.get(url, headers=headers, timeout=30)
            
            if not self.is_valid_response(response):
                return ScrapedContent(
                    url=url,
                    title="",
                    content="",
                    status_code=response.status_code,
                    success=False,
                    error_message=f"Invalid response: {response.status_code}"
                )
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract title
            title_tag = soup.find('title')
            title = title_tag.get_text(strip=True) if title_tag else "No title found"
            
            # Try multiple content extraction methods
            content = None
            
            # Method 1: Trafilatura (best for articles)
            content = self.extract_content_trafilatura(response.text, url)
            
            # Method 2: Readability (Mozilla's algorithm)
            if not content or len(content) < 100:
                content = self.extract_content_readability(response.text, url)
            
            # Method 3: Manual extraction
            if not content or len(content) < 100:
                content = self.extract_content_manual(soup, url)
            
            if not content:
                content = "Failed to extract meaningful content"
            
            word_count = len(content.split())
            
            return ScrapedContent(
                url=url,
                title=title,
                content=content,
                status_code=response.status_code,
                success=True,
                word_count=word_count
            )
            
        except requests.RequestException as e:
            logger.error(f"Request error for {url}: {str(e)}")
            return ScrapedContent(
                url=url,
                title="",
                content="",
                status_code=0,
                success=False,
                error_message=f"Request error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Unexpected error for {url}: {str(e)}")
            return ScrapedContent(
                url=url,
                title="",
                content="",
                status_code=0,
                success=False,
                error_message=f"Unexpected error: {str(e)}"
            )
    
    def scrape_search_results(self, query: str, num_results: int = 10) -> List[ScrapedContent]:
        """
        Main function: Search DuckDuckGo and scrape results
        """
        logger.info(f"Starting search and scrape for: '{query}'")
        
        # Step 1: Search DuckDuckGo
        urls = self.search_duckduckgo(query, num_results)
        
        if not urls:
            logger.warning("No URLs found from search")
            return []
        
        # Step 2: Scrape each URL
        results = []
        for i, url in enumerate(urls, 1):
            logger.info(f"Processing {i}/{len(urls)}: {url}")
            result = self.scrape_url(url)
            results.append(result)
            
            # Log result summary
            if result.success:
                logger.info(f"✓ Success - {result.word_count} words extracted")
            else:
                logger.warning(f"✗ Failed - {result.error_message}")
        
        return results
    
    def save_results(self, results: List[ScrapedContent], filename: str = "scraping_results.json"):
        """
        Save results to JSON file
        """
        data = []
        for result in results:
            data.append({
                'url': result.url,
                'title': result.title,
                'content': result.content,
                'status_code': result.status_code,
                'success': result.success,
                'error_message': result.error_message,
                'word_count': result.word_count
            })
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Results saved to {filename}")

# Example usage
if __name__ == "__main__":
    scraper = AdvancedWebScraper()
    
    # Search query
    query = "artificial intelligence latest developments 2024"
    
    # Scrape search results
    results = scraper.scrape_search_results(query, num_results=10)
    
    # Display results summary
    successful_scrapes = [r for r in results if r.success]
    failed_scrapes = [r for r in results if not r.success]
    
    print(f"\n📊 SCRAPING SUMMARY")
    print(f"{'='*50}")
    print(f"Query: {query}")
    print(f"Total URLs processed: {len(results)}")
    print(f"Successful scrapes: {len(successful_scrapes)}")
    print(f"Failed scrapes: {len(failed_scrapes)}")
    
    if successful_scrapes:
        total_words = sum(r.word_count for r in successful_scrapes)
        print(f"Total words extracted: {total_words:,}")
        print(f"Average words per page: {total_words // len(successful_scrapes):,}")
    
    print(f"\n📄 DETAILED RESULTS")
    print(f"{'='*50}")
    
    for i, result in enumerate(results, 1):
        status = "✅ SUCCESS" if result.success else "❌ FAILED"
        print(f"{i}. {status}")
        print(f"   URL: {result.url}")
        print(f"   Title: {result.title[:100]}...")
        
        if result.success:
            print(f"   Words: {result.word_count:,}")
            print(f"   Content preview: {result.content[:200]}...")
        else:
            print(f"   Error: {result.error_message}")
        print()
    
    # Save results
    scraper.save_results(results)
    
    # Save only successful results to separate file
    if successful_scrapes:
        scraper.save_results(successful_scrapes, "successful_scrapes.json")