#!/usr/bin/env python3
"""
collect_jcr_if.py

Fetch Journal Citation Report (JCR) Impact Factor values for specified journals
for given years (e.g., 2023, 2024, 2025). This script queries Wikipedia pages
for each journal and parses the infobox for Impact factor entries. Wikipedia is
used as the primary online source; the script is extensible to other sources.

Usage:
    python3 collect_jcr_if.py --years 2023 2024 2025

Outputs:
    jcr_impact_factors.json  -- JSON mapping journal -> year -> impact factor (or null)

Dependencies:
    requests, beautifulsoup4

Install: pip install requests beautifulsoup4
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

# User agent to identify requests
HEADERS = {
    "User-Agent": "collect-jcr-if/1.0 (+https://github.com/)"
}

# Mapping of friendly names to Wikipedia page titles (primary source)
JOURNALS = {
    "IEEE TSE": "IEEE_Transactions_on_Software_Engineering",
    "ACM TOSEM": "ACM_Transactions_on_Software_Engineering_and_Methodology",
    "Springer EMSE": "Empirical_Software_Engineering",
    "JSS": "Journal_of_Systems_and_Software",
    "IST": "Information_and_Software_Technology",
}

# Additional publisher/journal pages to try as fallbacks (may contain year-tagged impact factors)
ADDITIONAL_SOURCES = {
    "IEEE TSE": [
        "https://www.computer.org/csdl/journal/ts",
        "https://ieeexplore.ieee.org/xpl/RecentIssue.jsp?punumber=32",
    ],
    "ACM TOSEM": [
        "https://dl.acm.org/journal/tosem",
    ],
    "Springer EMSE": [
        "https://www.springer.com/journal/10664",
    ],
    "JSS": [
        "https://www.journals.elsevier.com/journal-of-systems-and-software",
    ],
    "IST": [
        "https://www.journals.elsevier.com/information-and-software-technology",
    ],
}

WIKIPEDIA_BASE = "https://en.wikipedia.org/wiki/"

# Regex patterns
# Match something like: 5.123 (2023), 2023: 5.123, Impact factor 5.123
NUM_RE = r"\d+(?:\.\d+)?"
PAIR_RE = re.compile(rf"(?P<value>{NUM_RE})\s*(?:\((?P<year>\d{{4}})\))")
YEAR_LABEL_RE = re.compile(r"(?P<year>20\d{2})\s*[:\-]\s*(?P<value>" + NUM_RE + r")")


def fetch_wikipedia_html(title: str) -> Optional[str]:
    url = WIKIPEDIA_BASE + title
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return None


def fetch_wikipedia_raw(title: str) -> Optional[str]:
    """Fetch raw wikitext for a Wikipedia page."""
    url = f"https://en.wikipedia.org/w/index.php?title={title}&action=raw"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"Error fetching raw wikitext {url}: {e}", file=sys.stderr)
        return None


def fetch_url_text(url: str) -> Optional[str]:
    """Fetch a generic URL and return its text content (HTML) or None on error."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return None


def parse_wikitext_impact_factors(raw: str) -> Dict[int, float]:
    """Parse wikitext for common infobox parameters like impact_factor and impact_year.

    Returns mapping year->impact factor. If a year is not available, uses 0 for 'latest'.
    """
    results: Dict[int, float] = {}

    # Pattern: | impact_factor = 6.123
    for m in re.finditer(r"\|\s*impact_factor\s*=\s*([0-9]+(?:\.[0-9]+)?)", raw, re.I):
        try:
            val = float(m.group(1))
        except Exception:
            continue
        # Try to find an impact_year parameter nearby (after the impact_factor)
        window = raw[m.end(): m.end() + 300]
        yr = re.search(r"\|\s*impact_year\s*=\s*(20\d{2})", window, re.I)
        if yr:
            results[int(yr.group(1))] = val
        else:
            # look backward for an impact_year parameter
            back = raw[max(0, m.start() - 300): m.start()]
            yr2 = re.search(r"\|\s*impact_year\s*=\s*(20\d{2})", back, re.I)
            if yr2:
                results[int(yr2.group(1))] = val
            else:
                results[0] = val

    # Pattern: | impact_factor_2023 = 6.123
    for m in re.finditer(r"\|\s*impact_factor[_-]?(?P<y>20\d{2})\s*=\s*([0-9]+(?:\.[0-9]+)?)", raw, re.I):
        try:
            y = int(m.group("y"))
            val = float(m.group(2))
            results[y] = val
        except Exception:
            continue

    # Some pages use | impact = 6.123 and | impact_year = 2023
    for m in re.finditer(r"\|\s*impact\s*=\s*([0-9]+(?:\.[0-9]+)?)", raw, re.I):
        try:
            val = float(m.group(1))
        except Exception:
            continue
        window = raw[m.end(): m.end() + 300]
        yr = re.search(r"\|\s*impact_year\s*=\s*(20\d{2})", window, re.I)
        if yr:
            results[int(yr.group(1))] = val
        else:
            results.setdefault(0, val)

    return results


def parse_html_impact_factors(html: str) -> Dict[int, float]:
    """Parse the entire HTML page for impact factor mentions (not only infobox).

    Returns mapping year->impact factor; uses 0 as key for 'latest' when no year found.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    results: Dict[int, float] = {}

    # Find explicit patterns like '4.123 (2023)'
    for m in PAIR_RE.finditer(text):
        try:
            year = int(m.group("year"))
            val = float(m.group("value"))
            results[year] = val
        except Exception:
            continue

    # Find patterns like '2023: 4.123' anywhere
    for m in YEAR_LABEL_RE.finditer(text):
        try:
            year = int(m.group("year"))
            val = float(m.group("value"))
            results[year] = val
        except Exception:
            continue

    # Look for occurrences of the phrase 'Impact factor' and inspect nearby text
    for match in re.finditer(r"Impact factor|Impact Factor", text):
        start = match.end()
        window = text[start: start + 300]
        # try explicit patterns inside the window
        m1 = PAIR_RE.search(window)
        if m1:
            try:
                results[int(m1.group("year"))] = float(m1.group("value"))
                continue
            except Exception:
                pass
        m2 = YEAR_LABEL_RE.search(window)
        if m2:
            try:
                results[int(m2.group("year"))] = float(m2.group("value"))
                continue
            except Exception:
                pass
        # fallback: take first numeric value and look for a year in parentheses
        lone = re.search(NUM_RE, window)
        if lone:
            try:
                val = float(lone.group(0))
            except Exception:
                continue
            yr = re.search(r"\((20\d{2})\)", window)
            if yr:
                try:
                    results[int(yr.group(1))] = val
                except Exception:
                    results.setdefault(0, val)
            else:
                results.setdefault(0, val)

    return results


def collect(queries: Dict[str, str], years: List[int], fallback_latest: bool = False) -> Dict[str, Dict[int, Optional[float]]]:
    """Collect impact factors for each journal. If fallback_latest is True, use the 'latest' value (key 0)
    to fill years that are missing; otherwise only set years explicitly found.
    """
    out: Dict[str, Dict[int, Optional[float]]] = {}
    for name, page in queries.items():
        print(f"Fetching {name} -> {page}...", file=sys.stderr)
        html = fetch_wikipedia_html(page)
        raw = fetch_wikipedia_raw(page)

        found: Dict[int, float] = {}
        if raw:
            try:
                found.update(parse_wikitext_impact_factors(raw))
            except Exception as e:
                print(f"Error parsing wikitext for {page}: {e}", file=sys.stderr)
        if html:
            try:
                html_found = parse_html_impact_factors(html)
                # prefer explicit yeared entries; supplement missing ones from HTML
                for k, v in html_found.items():
                    if k not in found:
                        found[k] = v
            except Exception as e:
                print(f"Error parsing HTML for {page}: {e}", file=sys.stderr)

        # Try additional known publisher/journal pages for this journal
        for url in ADDITIONAL_SOURCES.get(name, []):
            txt = fetch_url_text(url)
            if not txt:
                continue
            try:
                add_found = parse_html_impact_factors(txt)
                for k, v in add_found.items():
                    if k not in found:
                        found[k] = v
            except Exception as e:
                print(f"Error parsing additional source {url}: {e}", file=sys.stderr)

        mapping: Dict[int, Optional[float]] = {y: None for y in years}
        for y in years:
            if y in found:
                mapping[y] = found[y]

        # Optionally use latest (0) as fallback for missing years
        if fallback_latest and 0 in found:
            for y in years:
                if mapping[y] is None:
                    mapping[y] = found[0]

        out[name] = mapping
    return out


def save_json(data: dict, path: str = "jcr_impact_factors.json") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_args():
    p = argparse.ArgumentParser(description="Collect JCR Impact Factors for specified journals from the web (Wikipedia).")
    p.add_argument("--years", nargs="+", type=int, default=[2023, 2024, 2025], help="Years to collect (default: 2023 2024 2025)")
    p.add_argument("--output", default="jcr_impact_factors.json", help="Output JSON file")
    p.add_argument("--use-latest-fallback", dest="use_latest_fallback", action="store_true", help="If set, use the latest available impact factor to fill missing years")
    return p.parse_args()


def main():
    args = parse_args()
    years = args.years
    print(f"Collecting impact factors for years: {years}", file=sys.stderr)
    data = collect(JOURNALS, years, fallback_latest=args.use_latest_fallback)

    # Normalize output: str keys, years as strings for JSON readability
    normalized = {j: {str(y): (data[j][y] if y in data[j] else None) for y in years} for j in data}

    save_json(normalized, args.output)
    print(f"Saved results to {args.output}")
    print(json.dumps(normalized, indent=2))


if __name__ == "__main__":
    main()
