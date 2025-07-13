"""
quick_scrape.py
Run:  python quick_scrape.py "Motorola Razr+ (2025)"
Or import `quick_scrape.single_query` from another program.
"""

import json
import argparse
import time
from typing import List, Dict, Any

# --- import the main scraper -------------------------------------------------
# If your big file is named `smart_scraper.py`, adjust the line below.
from test import scrape_multiple_sites_parallel


def single_query(query: str,
                 max_sites: int = 2,
                 max_total_time: int = 60) -> List[Dict[str, Any]]:
    """
    Wrapper you can call from any other script.
    Returns the list produced by scrape_multiple_sites_parallel().
    """
    start = time.time()
    results = scrape_multiple_sites_parallel(
        query=query,
        max_sites=max_sites,
        max_total_time=max_total_time,
    )
    elapsed = time.time() - start

    # Pretty print if run interactively
    if __name__ == "__main__":
        print("\n" + "=" * 60)
        print(f"EXECUTION SUMMARY for '{query}':")
        print(f"Sites scraped: {len(results) if results else 0}/{max_sites}")
        print(f"Total execution time: {elapsed:.2f}s")
        print("=" * 60)
        if results:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            print("No sites scraped.")

    return results


def _cli() -> None:
    """CLI entry‑point."""
    parser = argparse.ArgumentParser(
        description="Quick one‑shot scraper wrapper."
    )
    parser.add_argument(
        "query",
        type=str,
        help="Search query / product name"
    )
    parser.add_argument(
        "--sites",
        type=int,
        default=2,
        help="How many distinct sites to return (default: 2)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Hard per‑query timeout in seconds (default: 60)"
    )
    args = parser.parse_args()
    single_query(args.query, max_sites=args.sites, max_total_time=args.timeout)


if __name__ == "__main__":
    _cli()


# python searxngfinaluse.py "Redmi Note 13 pro plus"
