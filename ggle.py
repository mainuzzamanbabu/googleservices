import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pytrends.request import TrendReq
import requests
from bs4 import BeautifulSoup
import time
import json
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

class GoogleTrendsSearchAnalyzer:
    def __init__(self):
        # Initialize Google Trends
        self.pytrends = TrendReq(hl='en-US', tz=360)
        
    def get_trending_searches(self, country='united_states'):
        """
        Get current trending searches for a specific country
        """
        try:
            trending_searches = self.pytrends.trending_searches(pn=country)
            return trending_searches[0].tolist()
        except Exception as e:
            print(f"Error getting trending searches: {e}")
            return []
    
    def get_interest_over_time(self, keywords, timeframe='today 12-m', geo='US'):
        """
        Get interest over time for specific keywords
        timeframe options: 'now 1-H', 'now 4-H', 'now 1-d', 'now 7-d', 'today 1-m', 'today 3-m', 'today 12-m', 'today 5-y', 'all'
        """
        try:
            # Build payload
            self.pytrends.build_payload(keywords, cat=0, timeframe=timeframe, geo=geo, gprop='')
            
            # Get interest over time
            interest_df = self.pytrends.interest_over_time()
            
            if not interest_df.empty:
                # Remove 'isPartial' column if it exists
                if 'isPartial' in interest_df.columns:
                    interest_df = interest_df.drop('isPartial', axis=1)
                
                return interest_df
            else:
                print("No data found for the given keywords")
                return pd.DataFrame()
                
        except Exception as e:
            print(f"Error getting interest over time: {e}")
            return pd.DataFrame()
    
    def get_related_queries(self, keyword, timeframe='today 12-m', geo='US'):
        """
        Get related queries for a keyword
        """
        try:
            self.pytrends.build_payload([keyword], timeframe=timeframe, geo=geo)
            related_queries = self.pytrends.related_queries()
            
            return {
                'rising': related_queries[keyword]['rising'],
                'top': related_queries[keyword]['top']
            }
        except Exception as e:
            print(f"Error getting related queries: {e}")
            return {'rising': None, 'top': None}
    
    def get_interest_by_region(self, keyword, timeframe='today 12-m', geo='US'):
        """
        Get interest by region/location
        """
        try:
            self.pytrends.build_payload([keyword], timeframe=timeframe, geo=geo)
            region_df = self.pytrends.interest_by_region(resolution='COUNTRY', inc_low_vol=True, inc_geo_code=False)
            return region_df.sort_values(by=keyword, ascending=False)
        except Exception as e:
            print(f"Error getting interest by region: {e}")
            return pd.DataFrame()
    
    def get_suggestions(self, keyword):
        """
        Get keyword suggestions
        """
        try:
            suggestions = self.pytrends.suggestions(keyword=keyword)
            return [item['title'] for item in suggestions]
        except Exception as e:
            print(f"Error getting suggestions: {e}")
            return []
    
    def compare_keywords(self, keywords, timeframe='today 12-m', geo='US'):
        """
        Compare multiple keywords
        """
        try:
            self.pytrends.build_payload(keywords, timeframe=timeframe, geo=geo)
            comparison_df = self.pytrends.interest_over_time()
            
            if 'isPartial' in comparison_df.columns:
                comparison_df = comparison_df.drop('isPartial', axis=1)
            
            return comparison_df
        except Exception as e:
            print(f"Error comparing keywords: {e}")
            return pd.DataFrame()
    
    def plot_trends(self, df, title="Google Trends Analysis"):
        """
        Plot trends data
        """
        if df.empty:
            print("No data to plot")
            return
        
        plt.figure(figsize=(12, 6))
        for column in df.columns:
            plt.plot(df.index, df[column], label=column, linewidth=2)
        
        plt.title(title, fontsize=16, fontweight='bold')
        plt.xlabel('Date', fontsize=12)
        plt.ylabel('Interest Score', fontsize=12)
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.show()
    
    def get_comprehensive_analysis(self, keyword, timeframe='today 12-m', geo='US'):
        """
        Get comprehensive analysis for a keyword
        """
        print(f"🔍 Comprehensive Analysis for: '{keyword}'")
        print("=" * 50)
        
        # 1. Interest over time
        print("📈 Getting interest over time...")
        interest_df = self.get_interest_over_time([keyword], timeframe, geo)
        
        # 2. Related queries
        print("🔗 Getting related queries...")
        related = self.get_related_queries(keyword, timeframe, geo)
        
        # 3. Interest by region
        print("🌍 Getting interest by region...")
        region_df = self.get_interest_by_region(keyword, timeframe, geo)
        
        # 4. Suggestions
        print("💡 Getting keyword suggestions...")
        suggestions = self.get_suggestions(keyword)
        
        # Compile results
        analysis = {
            'keyword': keyword,
            'timeframe': timeframe,
            'geo': geo,
            'interest_over_time': interest_df,
            'related_queries': related,
            'interest_by_region': region_df,
            'suggestions': suggestions,
            'summary': {
                'peak_interest': interest_df[keyword].max() if not interest_df.empty else 0,
                'average_interest': interest_df[keyword].mean() if not interest_df.empty else 0,
                'top_regions': region_df.head(5).index.tolist() if not region_df.empty else [],
                'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        }
        
        return analysis
    
    def export_analysis(self, analysis, filename=None):
        """
        Export analysis to Excel file
        """
        if not filename:
            filename = f"google_trends_analysis_{analysis['keyword']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        try:
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                # Interest over time
                if not analysis['interest_over_time'].empty:
                    analysis['interest_over_time'].to_excel(writer, sheet_name='Interest_Over_Time')
                
                # Related queries
                if analysis['related_queries']['top'] is not None:
                    analysis['related_queries']['top'].to_excel(writer, sheet_name='Related_Top')
                if analysis['related_queries']['rising'] is not None:
                    analysis['related_queries']['rising'].to_excel(writer, sheet_name='Related_Rising')
                
                # Interest by region
                if not analysis['interest_by_region'].empty:
                    analysis['interest_by_region'].to_excel(writer, sheet_name='Interest_By_Region')
                
                # Suggestions
                if analysis['suggestions']:
                    pd.DataFrame(analysis['suggestions'], columns=['Suggestions']).to_excel(writer, sheet_name='Suggestions')
                
                # Summary
                summary_df = pd.DataFrame([analysis['summary']])
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            print(f"✅ Analysis exported to: {filename}")
            return filename
            
        except Exception as e:
            print(f"❌ Error exporting analysis: {e}")
            return None


# Business Intelligence Functions
class GoogleSearchBusinessIntel:
    def __init__(self):
        self.trends_analyzer = GoogleTrendsSearchAnalyzer()
    
    def market_research(self, product_keywords, competitor_keywords, timeframe='today 12-m'):
        """
        Comprehensive market research
        """
        print("🏢 MARKET RESEARCH ANALYSIS")
        print("=" * 40)
        
        # Compare product keywords
        print("📊 Analyzing product keywords...")
        product_trends = self.trends_analyzer.compare_keywords(product_keywords, timeframe)
        
        # Compare competitor keywords
        print("🏆 Analyzing competitor keywords...")
        competitor_trends = self.trends_analyzer.compare_keywords(competitor_keywords, timeframe)
        
        # Get related queries for each product
        related_data = {}
        for keyword in product_keywords:
            print(f"🔍 Getting related queries for: {keyword}")
            related_data[keyword] = self.trends_analyzer.get_related_queries(keyword, timeframe)
        
        return {
            'product_trends': product_trends,
            'competitor_trends': competitor_trends,
            'related_queries': related_data,
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def seasonal_analysis(self, keywords, years=2):
        """
        Analyze seasonal patterns
        """
        timeframe = f'today {years*12}-m'  # Convert years to months
        
        print(f"📅 SEASONAL ANALYSIS ({years} years)")
        print("=" * 40)
        
        seasonal_data = {}
        for keyword in keywords:
            print(f"📈 Analyzing seasonal patterns for: {keyword}")
            trends = self.trends_analyzer.get_interest_over_time([keyword], timeframe)
            if not trends.empty:
                trends['month'] = trends.index.month
                trends['year'] = trends.index.year
                seasonal_data[keyword] = trends
        
        return seasonal_data
    
    def content_strategy(self, main_keyword, timeframe='today 12-m'):
        """
        Generate content strategy insights
        """
        print("📝 CONTENT STRATEGY ANALYSIS")
        print("=" * 40)
        
        # Get comprehensive analysis
        analysis = self.trends_analyzer.get_comprehensive_analysis(main_keyword, timeframe)
        
        # Get suggestions for content ideas
        suggestions = self.trends_analyzer.get_suggestions(main_keyword)
        
        # Identify trending related topics
        related = analysis['related_queries']
        
        content_ideas = []
        if related['rising'] is not None and not related['rising'].empty:
            content_ideas.extend(related['rising']['query'].tolist())
        if related['top'] is not None and not related['top'].empty:
            content_ideas.extend(related['top']['query'].tolist())
        
        return {
            'main_analysis': analysis,
            'content_ideas': list(set(content_ideas)),  # Remove duplicates
            'keyword_suggestions': suggestions
        }


# Usage Examples and Demo
def demo_analysis():
    """
    Demonstration of the Google Trends analysis capabilities
    """
    analyzer = GoogleTrendsSearchAnalyzer()
    business_intel = GoogleSearchBusinessIntel()
    
    print("🚀 GOOGLE TRENDS & SEARCH ANALYSIS DEMO")
    print("=" * 50)
    
    # Example 1: Basic keyword analysis
    print("\n1️⃣ BASIC KEYWORD ANALYSIS")
    keyword = "artificial intelligence"
    analysis = analyzer.get_comprehensive_analysis(keyword)
    
    print(f"📊 Peak Interest: {analysis['summary']['peak_interest']}")
    print(f"📊 Average Interest: {analysis['summary']['average_interest']:.2f}")
    print(f"🌍 Top Regions: {', '.join(analysis['summary']['top_regions'][:3])}")
    
    # Example 2: Keyword comparison
    print("\n2️⃣ KEYWORD COMPARISON")
    keywords = ["machine learning", "deep learning", "neural networks"]
    comparison = analyzer.compare_keywords(keywords)
    if not comparison.empty:
        print(f"📈 Comparison data shape: {comparison.shape}")
        print("📊 Latest values:")
        print(comparison.tail(1))
    
    # Example 3: Market research
    print("\n3️⃣ MARKET RESEARCH EXAMPLE")
    product_keywords = ["chatgpt", "claude ai"]
    competitor_keywords = ["google bard", "bing chat"]
    market_research = business_intel.market_research(product_keywords, competitor_keywords)
    
    print("✅ Market research completed!")
    
    return analysis, comparison, market_research


if __name__ == "__main__":
    # Required packages to install:
    # pip install pytrends pandas matplotlib seaborn requests beautifulsoup4 openpyxl
    
    print("📋 GOOGLE TRENDS & SEARCH ANALYZER")
    print("=" * 50)
    print("This tool provides comprehensive Google Trends analysis including:")
    print("• Interest over time analysis")
    print("• Related queries discovery")
    print("• Regional interest mapping")
    print("• Keyword suggestions")
    print("• Market research capabilities")
    print("• Seasonal pattern analysis")
    print("• Content strategy insights")
    print("\nUncomment the demo_analysis() call below to run examples!")
    
    # Uncomment to run demo
    # demo_analysis()