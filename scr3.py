from duckduckgo_search import DDGS
import trafilatura
import time
import requests
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
import json
import csv
from datetime import datetime, timedelta
import logging
import re
from collections import Counter
import statistics

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraping.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class ScrapingResult:
    url: str
    title: str
    search_rank: int
    fetch_time: float
    extraction_time: float
    total_time: float
    success: bool
    content_length: int
    word_count: int
    paragraph_count: int
    link_count: int
    image_count: int
    content: str
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    http_status: Optional[int] = None
    content_type: Optional[str] = None
    server_header: Optional[str] = None
    response_size: Optional[int] = None
    redirect_count: int = 0
    is_blocked: bool = False
    block_reason: Optional[str] = None
    robots_txt_allowed: Optional[bool] = None
    ssl_error: bool = False
    timeout_error: bool = False
    connection_error: bool = False

@dataclass
class ScrapingSession:
    query: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_urls: int = 0
    successful_scrapes: int = 0
    failed_scrapes: int = 0
    blocked_sites: int = 0
    timeout_errors: int = 0
    connection_errors: int = 0
    ssl_errors: int = 0
    total_words_extracted: int = 0
    average_fetch_time: float = 0.0
    fastest_site: Optional[str] = None
    slowest_site: Optional[str] = None
    results: List[ScrapingResult] = None
    
    def __post_init__(self):
        if self.results is None:
            self.results = []

class EnhancedWebScraper:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })
        
        # Common blocking indicators
        self.blocking_indicators = [
            'access denied', 'blocked', 'forbidden', '403', 'captcha',
            'cloudflare', 'bot protection', 'rate limit', 'too many requests',
            'suspicious activity', 'verification required', 'human verification'
        ]
        
        # Content quality indicators
        self.quality_indicators = {
            'high': ['article', 'blog', 'news', 'review', 'guide', 'tutorial'],
            'medium': ['forum', 'discussion', 'comment', 'wiki'],
            'low': ['advertisement', 'popup', 'redirect', 'error']
        }
    
    def check_robots_txt(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt"""
        try:
            parsed_url = urlparse(url)
            robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
            
            response = self.session.get(robots_url, timeout=5)
            if response.status_code == 200:
                robots_content = response.text.lower()
                user_agent_section = False
                
                for line in robots_content.split('\n'):
                    line = line.strip()
                    if line.startswith('user-agent:'):
                        agent = line.split(':', 1)[1].strip()
                        user_agent_section = agent == '*' or 'mozilla' in agent
                    elif user_agent_section and line.startswith('disallow:'):
                        disallow_path = line.split(':', 1)[1].strip()
                        if disallow_path == '/' or parsed_url.path.startswith(disallow_path):
                            return False
                return True
        except:
            pass
        return None  # Unknown
    
    def detect_blocking(self, content: str, response_headers: dict, status_code: int) -> Tuple[bool, Optional[str]]:
        """Detect if the site is blocking the scraper"""
        content_lower = content.lower() if content else ""
        
        # Check HTTP status codes
        if status_code in [403, 429, 503]:
            return True, f"HTTP {status_code} error"
        
        # Check content for blocking indicators
        for indicator in self.blocking_indicators:
            if indicator in content_lower:
                return True, f"Content contains: {indicator}"
        
        # Check headers for blocking
        server = response_headers.get('server', '').lower()
        if 'cloudflare' in server and len(content) < 1000:
            return True, "Cloudflare protection detected"
        
        # Check for minimal content (likely blocked)
        if len(content) < 100 and status_code == 200:
            return True, "Minimal content returned"
        
        return False, None
    
    def analyze_content_quality(self, content: str) -> Dict[str, int]:
        """Analyze the quality and characteristics of extracted content"""
        if not content:
            return {'paragraphs': 0, 'links': 0, 'images': 0, 'words': 0}
        
        # Count paragraphs (rough estimate)
        paragraphs = len([p for p in content.split('\n\n') if len(p.strip()) > 50])
        
        # Count words
        words = len(content.split())
        
        # Count potential links and images (in extracted text)
        links = content.count('http://') + content.count('https://')
        images = content.lower().count('image') + content.lower().count('photo') + content.lower().count('picture')
        
        return {
            'paragraphs': paragraphs,
            'links': links,
            'images': images,
            'words': words
        }
    
    def fetch_with_retries(self, url: str) -> Tuple[Optional[str], Dict]:
        """Fetch URL with retry logic and detailed error tracking"""
        metadata = {
            'http_status': None,
            'content_type': None,
            'server_header': None,
            'response_size': None,
            'redirect_count': 0,
            'ssl_error': False,
            'timeout_error': False,
            'connection_error': False,
            'error_message': None
        }
        
        for attempt in range(self.max_retries):
            try:
                # Add small delay between retries
                if attempt > 0:
                    time.sleep(2 ** attempt)  # Exponential backoff
                
                response = self.session.get(
                    url, 
                    timeout=self.timeout,
                    allow_redirects=True,
                    stream=True
                )
                
                # Collect metadata
                metadata['http_status'] = response.status_code
                metadata['content_type'] = response.headers.get('content-type', '')
                metadata['server_header'] = response.headers.get('server', '')
                metadata['redirect_count'] = len(response.history)
                
                # Check content type
                if 'text/html' not in metadata['content_type'].lower():
                    metadata['error_message'] = f"Non-HTML content: {metadata['content_type']}"
                    return None, metadata
                
                # Get content
                content = response.text
                metadata['response_size'] = len(content)
                
                # Check for blocking
                is_blocked, block_reason = self.detect_blocking(
                    content, response.headers, response.status_code
                )
                
                if is_blocked:
                    metadata['error_message'] = f"Blocked: {block_reason}"
                    return None, metadata
                
                return content, metadata
                
            except requests.exceptions.SSLError as e:
                metadata['ssl_error'] = True
                metadata['error_message'] = f"SSL Error: {str(e)}"
                logger.warning(f"SSL error for {url}: {str(e)}")
                
            except requests.exceptions.Timeout as e:
                metadata['timeout_error'] = True
                metadata['error_message'] = f"Timeout: {str(e)}"
                logger.warning(f"Timeout for {url}: {str(e)}")
                
            except requests.exceptions.ConnectionError as e:
                metadata['connection_error'] = True
                metadata['error_message'] = f"Connection Error: {str(e)}"
                logger.warning(f"Connection error for {url}: {str(e)}")
                
            except Exception as e:
                metadata['error_message'] = f"Unexpected error: {str(e)}"
                logger.error(f"Unexpected error for {url}: {str(e)}")
        
        return None, metadata
    
    def scrape_url(self, url: str, rank: int, title: str) -> ScrapingResult:
        """Scrape a single URL with comprehensive tracking"""
        start_time = time.time()
        
        logger.info(f"Scraping #{rank}: {url}")
        
        # Check robots.txt
        robots_allowed = self.check_robots_txt(url)
        
        # Fetch the webpage
        fetch_start = time.time()
        downloaded, metadata = self.fetch_with_retries(url)
        fetch_time = time.time() - fetch_start
        
        if not downloaded:
            return ScrapingResult(
                url=url,
                title=title,
                search_rank=rank,
                fetch_time=fetch_time,
                extraction_time=0.0,
                total_time=time.time() - start_time,
                success=False,
                content_length=0,
                word_count=0,
                paragraph_count=0,
                link_count=0,
                image_count=0,
                content="",
                error_type=self._classify_error(metadata),
                error_message=metadata.get('error_message'),
                http_status=metadata.get('http_status'),
                content_type=metadata.get('content_type'),
                server_header=metadata.get('server_header'),
                response_size=metadata.get('response_size'),
                redirect_count=metadata.get('redirect_count', 0),
                is_blocked=True,
                block_reason=metadata.get('error_message'),
                robots_txt_allowed=robots_allowed,
                ssl_error=metadata.get('ssl_error', False),
                timeout_error=metadata.get('timeout_error', False),
                connection_error=metadata.get('connection_error', False)
            )
        
        # Extract the main content
        extraction_start = time.time()
        extracted = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            include_images=False,
            include_formatting=False
        )
        extraction_time = time.time() - extraction_start
        
        if not extracted:
            return ScrapingResult(
                url=url,
                title=title,
                search_rank=rank,
                fetch_time=fetch_time,
                extraction_time=extraction_time,
                total_time=time.time() - start_time,
                success=False,
                content_length=0,
                word_count=0,
                paragraph_count=0,
                link_count=0,
                image_count=0,
                content="",
                error_type="EXTRACTION_FAILED",
                error_message="Trafilatura failed to extract content",
                http_status=metadata.get('http_status'),
                content_type=metadata.get('content_type'),
                server_header=metadata.get('server_header'),
                response_size=metadata.get('response_size'),
                redirect_count=metadata.get('redirect_count', 0),
                is_blocked=False,
                robots_txt_allowed=robots_allowed
            )
        
        # Analyze content
        content_analysis = self.analyze_content_quality(extracted)
        
        return ScrapingResult(
            url=url,
            title=title,
            search_rank=rank,
            fetch_time=fetch_time,
            extraction_time=extraction_time,
            total_time=time.time() - start_time,
            success=True,
            content_length=len(extracted),
            word_count=content_analysis['words'],
            paragraph_count=content_analysis['paragraphs'],
            link_count=content_analysis['links'],
            image_count=content_analysis['images'],
            content=extracted,
            http_status=metadata.get('http_status'),
            content_type=metadata.get('content_type'),
            server_header=metadata.get('server_header'),
            response_size=metadata.get('response_size'),
            redirect_count=metadata.get('redirect_count', 0),
            is_blocked=False,
            robots_txt_allowed=robots_allowed
        )
    
    def _classify_error(self, metadata: Dict) -> str:
        """Classify the type of error"""
        if metadata.get('ssl_error'):
            return "SSL_ERROR"
        elif metadata.get('timeout_error'):
            return "TIMEOUT_ERROR"
        elif metadata.get('connection_error'):
            return "CONNECTION_ERROR"
        elif metadata.get('http_status') == 403:
            return "FORBIDDEN"
        elif metadata.get('http_status') == 404:
            return "NOT_FOUND"
        elif metadata.get('http_status') == 429:
            return "RATE_LIMITED"
        elif metadata.get('http_status') == 503:
            return "SERVICE_UNAVAILABLE"
        elif 'blocked' in metadata.get('error_message', '').lower():
            return "BLOCKED"
        else:
            return "UNKNOWN_ERROR"
    
    def scrape_search_results(self, query: str, max_results: int = 10) -> ScrapingSession:
        """Main function to scrape search results with comprehensive analytics"""
        session = ScrapingSession(
            query=query,
            start_time=datetime.now(),
            total_urls=max_results
        )
        
        logger.info(f"Starting search and scrape session for: '{query}'")
        
        try:
            # Search DuckDuckGo
            with DDGS() as ddgs:
                search_results = [r for r in ddgs.text(query, max_results=max_results)]
            
            if not search_results:
                logger.warning("No search results found")
                session.end_time = datetime.now()
                return session
            
            # Process each URL
            for i, result in enumerate(search_results, 1):
                url = result['href']
                title = result.get('title', 'No title')
                
                scrape_result = self.scrape_url(url, i, title)
                session.results.append(scrape_result)
                
                # Update session statistics
                if scrape_result.success:
                    session.successful_scrapes += 1
                    session.total_words_extracted += scrape_result.word_count
                    logger.info(f"✅ Success - {scrape_result.word_count} words extracted in {scrape_result.total_time:.2f}s")
                else:
                    session.failed_scrapes += 1
                    if scrape_result.is_blocked:
                        session.blocked_sites += 1
                    if scrape_result.timeout_error:
                        session.timeout_errors += 1
                    if scrape_result.connection_error:
                        session.connection_errors += 1
                    if scrape_result.ssl_error:
                        session.ssl_errors += 1
                    
                    logger.warning(f"❌ Failed - {scrape_result.error_type}: {scrape_result.error_message}")
                
                # Add small delay between requests
                time.sleep(1)
        
        except Exception as e:
            logger.error(f"Search failed: {str(e)}")
        
        # Calculate final statistics
        session.end_time = datetime.now()
        if session.results:
            fetch_times = [r.total_time for r in session.results if r.success]
            if fetch_times:
                session.average_fetch_time = statistics.mean(fetch_times)
                fastest = min(session.results, key=lambda x: x.total_time if x.success else float('inf'))
                slowest = max(session.results, key=lambda x: x.total_time if x.success else 0)
                if fastest.success:
                    session.fastest_site = fastest.url
                if slowest.success:
                    session.slowest_site = slowest.url
        
        return session
    
    def print_detailed_report(self, session: ScrapingSession):
        """Print comprehensive scraping report"""
        duration = (session.end_time - session.start_time).total_seconds()
        
        print(f"\n{'='*80}")
        print(f"📊 COMPREHENSIVE SCRAPING REPORT")
        print(f"{'='*80}")
        print(f"🔍 Query: {session.query}")
        print(f"⏰ Duration: {duration:.2f} seconds")
        print(f"📈 Total URLs: {session.total_urls}")
        print(f"✅ Successful: {session.successful_scrapes}")
        print(f"❌ Failed: {session.failed_scrapes}")
        print(f"🚫 Blocked: {session.blocked_sites}")
        print(f"⏱️  Timeouts: {session.timeout_errors}")
        print(f"🔗 Connection Errors: {session.connection_errors}")
        print(f"🔒 SSL Errors: {session.ssl_errors}")
        print(f"📝 Total Words: {session.total_words_extracted:,}")
        
        if session.average_fetch_time > 0:
            print(f"⚡ Average Fetch Time: {session.average_fetch_time:.2f}s")
        if session.fastest_site:
            print(f"🏃 Fastest Site: {session.fastest_site}")
        if session.slowest_site:
            print(f"🐌 Slowest Site: {session.slowest_site}")
        
        print(f"\n{'='*80}")
        print(f"📋 DETAILED RESULTS")
        print(f"{'='*80}")
        
        for result in session.results:
            status = "✅" if result.success else "❌"
            print(f"\n{status} #{result.search_rank}: {result.title[:60]}...")
            print(f"   🔗 URL: {result.url}")
            print(f"   ⏰ Fetch: {result.fetch_time:.2f}s | Extract: {result.extraction_time:.2f}s | Total: {result.total_time:.2f}s")
            
            if result.success:
                print(f"   📊 Words: {result.word_count:,} | Paragraphs: {result.paragraph_count} | Links: {result.link_count}")
                print(f"   📄 Content Length: {result.content_length:,} chars")
                if result.http_status:
                    print(f"   🌐 HTTP: {result.http_status} | Type: {result.content_type}")
                if result.robots_txt_allowed is not None:
                    robots_status = "✅ Allowed" if result.robots_txt_allowed else "❌ Blocked"
                    print(f"   🤖 Robots.txt: {robots_status}")
            else:
                print(f"   ❌ Error: {result.error_type}")
                print(f"   💬 Message: {result.error_message}")
                if result.http_status:
                    print(f"   🌐 HTTP Status: {result.http_status}")
                if result.is_blocked:
                    print(f"   🚫 Blocked: {result.block_reason}")
        
        # Error summary
        error_types = Counter([r.error_type for r in session.results if not r.success and r.error_type])
        if error_types:
            print(f"\n{'='*80}")
            print(f"📊 ERROR BREAKDOWN")
            print(f"{'='*80}")
            for error_type, count in error_types.most_common():
                print(f"   {error_type}: {count}")
    
    def save_results(self, session: ScrapingSession, formats: List[str] = ['json', 'csv']):
        """Save results in multiple formats"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"scraping_results_{timestamp}"
        
        if 'json' in formats:
            json_file = f"{base_filename}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'session_info': asdict(session),
                    'results': [asdict(result) for result in session.results]
                }, f, indent=2, ensure_ascii=False, default=str)
            logger.info(f"Results saved to {json_file}")
        
        if 'csv' in formats:
            csv_file = f"{base_filename}.csv"
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                if session.results:
                    writer = csv.DictWriter(f, fieldnames=asdict(session.results[0]).keys())
                    writer.writeheader()
                    for result in session.results:
                        writer.writerow(asdict(result))
            logger.info(f"Results saved to {csv_file}")

# Example usage
if __name__ == "__main__":
    # Initialize the enhanced scraper
    scraper = EnhancedWebScraper(timeout=30, max_retries=2)
    
    # Define your search query
    query = "Best Earbud in BD 2025"
    
    # Run the comprehensive scraping session
    session = scraper.scrape_search_results(query, max_results=10)
    
    # Print detailed report
    scraper.print_detailed_report(session)
    
    # Save results
    scraper.save_results(session, formats=['json', 'csv'])
    
    # Print summary statistics
    if session.successful_scrapes > 0:
        success_rate = (session.successful_scrapes / session.total_urls) * 100
        avg_words = session.total_words_extracted / session.successful_scrapes
        print(f"\n🎯 SUCCESS RATE: {success_rate:.1f}%")
        print(f"📊 AVERAGE WORDS PER SUCCESSFUL SCRAPE: {avg_words:.0f}")