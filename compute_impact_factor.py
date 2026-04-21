#!/usr/bin/env python3
"""
Compute the 2024 independent impact factor for CS journals using the
Semantic Scholar API.

Unlike the official JCR impact factor, this computation:
  - Uses Semantic Scholar as data source (broader coverage than Web of Science)
  - Includes citations from conference papers (not only journal-to-journal)

Formula (same 2-year window as JCR):
    IF_2024 = citations_2024_to_papers_2022_2023 / papers_published_2022_2023

Journals computed:
  - IEEE TSE  (IEEE Transactions on Software Engineering)
  - ACM TOSEM (ACM Transactions on Software Engineering and Methodology)
  - Springer EMSE (Empirical Software Engineering)
"""

import argparse
import json
import sys
import time
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = "https://api.semanticscholar.org/graph/v1"

CITATION_YEAR = 2024
PUBLICATION_YEARS = [CITATION_YEAR - 2, CITATION_YEAR - 1]

# Each journal entry may list several name variants that Semantic Scholar uses
# in the `venue` / `publicationVenue.name` fields.
JOURNALS: dict[str, dict] = {
    "IEEE TSE": {
        "display": "IEEE Transactions on Software Engineering",
        "venue_names": [
            "IEEE Transactions on Software Engineering",
            "IEEE Trans. Software Eng.",
            "IEEE Trans. Softw. Eng.",
        ],
    },
    "ACM TOSEM": {
        "display": "ACM Transactions on Software Engineering and Methodology",
        "venue_names": [
            "ACM Transactions on Software Engineering and Methodology",
            "ACM Trans. Softw. Eng. Methodol.",
            "ACM Trans. Software Eng. Methodol.",
            "TOSEM",
        ],
    },
    "Springer EMSE": {
        "display": "Empirical Software Engineering",
        "venue_names": [
            "Empirical Software Engineering",
            "Empir. Software Eng.",
            "Empir. Softw. Eng.",
        ],
    },
}

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

RETRY_DELAYS = [10, 30, 60]  # seconds between retries


def _get(url: str, params: dict, api_key: Optional[str] = None) -> dict:
    """Send a GET request with basic retry / rate-limit handling."""
    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key

    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=60)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                print(f"    [rate-limited] sleeping {wait}s …", flush=True)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == len(RETRY_DELAYS):
                raise
            print(f"    [warning] request failed ({exc}); retrying …", flush=True)
    return {}


# ---------------------------------------------------------------------------
# Semantic Scholar helpers
# ---------------------------------------------------------------------------


def _venue_match(paper: dict, venue_names: list[str]) -> bool:
    """Return True when the paper's venue matches one of the target names."""
    candidates: list[str] = []

    raw_venue = (paper.get("venue") or "").strip()
    if raw_venue:
        candidates.append(raw_venue)

    pub_venue = paper.get("publicationVenue") or {}
    pub_venue_name = (pub_venue.get("name") or "").strip()
    if pub_venue_name:
        candidates.append(pub_venue_name)

    for candidate in candidates:
        cand_lower = candidate.lower()
        for target in venue_names:
            if target.lower() in cand_lower or cand_lower in target.lower():
                return True
    return False


def fetch_papers(journal_key: str, year: int, api_key: Optional[str] = None) -> list[dict]:
    """
    Fetch all papers published in *journal_key* during *year* using the
    Semantic Scholar paper-search endpoint.  Results are filtered to keep
    only papers whose recorded venue matches the journal.
    """
    venue_names = JOURNALS[journal_key]["venue_names"]
    primary_name = JOURNALS[journal_key]["display"]
    papers: list[dict] = []
    offset = 0
    limit = 100

    print(f"    Fetching {journal_key} papers for {year} …", flush=True)

    while True:
        params = {
            "query": primary_name,
            "fields": "paperId,title,year,venue,publicationVenue",
            "year": str(year),
            "offset": offset,
            "limit": limit,
        }
        data = _get(f"{API_BASE}/paper/search", params, api_key)

        batch = data.get("data") or []
        for paper in batch:
            if paper.get("year") == year and _venue_match(paper, venue_names):
                papers.append(paper)

        total = data.get("total", 0)
        fetched_so_far = offset + len(batch)
        if fetched_so_far >= total or not batch:
            break

        offset += limit
        time.sleep(1)  # be a good citizen

    print(f"      → {len(papers)} papers matched", flush=True)
    return papers


def count_citations_in_year(
    paper_id: str, target_year: int, api_key: Optional[str] = None
) -> int:
    """
    Return the number of papers that cite *paper_id* and were published in
    *target_year*.  This includes citations from conference papers.
    """
    count = 0
    offset = 0
    limit = 1000

    while True:
        params = {
            "fields": "year",
            "offset": offset,
            "limit": limit,
        }
        data = _get(f"{API_BASE}/paper/{paper_id}/citations", params, api_key)

        batch = data.get("data") or []
        for item in batch:
            citing = item.get("citingPaper") or {}
            if citing.get("year") == target_year:
                count += 1

        if len(batch) < limit:
            break
        offset += limit
        time.sleep(0.5)

    return count


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_impact_factor(journal_key: str, api_key: Optional[str] = None) -> dict:
    """Compute the 2024 impact factor for *journal_key*."""
    display = JOURNALS[journal_key]["display"]
    print(f"\n{'=' * 68}")
    print(f"  {journal_key}  —  {display}")
    print(f"{'=' * 68}", flush=True)

    # Step 1: collect papers published in the two-year window
    all_papers: list[dict] = []
    for year in PUBLICATION_YEARS:
        year_papers = fetch_papers(journal_key, year, api_key)
        all_papers.extend(year_papers)

    # Deduplicate by paperId (in case the same paper appears in multiple pages)
    seen: set[str] = set()
    unique_papers: list[dict] = []
    for p in all_papers:
        pid = p["paperId"]
        if pid not in seen:
            seen.add(pid)
            unique_papers.append(p)

    n_papers = len(unique_papers)
    print(f"\n  Total unique papers ({PUBLICATION_YEARS[0]}–{PUBLICATION_YEARS[-1]}): {n_papers}", flush=True)

    if n_papers == 0:
        print("  [warning] no papers found — cannot compute IF", flush=True)
        return {
            "journal": journal_key,
            "journal_name": display,
            "papers_in_window": 0,
            "citations_in_2024": 0,
            "impact_factor_2024": None,
        }

    # Step 2: count citations from CITATION_YEAR to each paper
    print(f"\n  Counting citations in {CITATION_YEAR} (including conferences) …", flush=True)
    total_citations = 0

    for i, paper in enumerate(unique_papers, start=1):
        pid = paper["paperId"]
        title_snippet = (paper.get("title") or "")[:60]
        print(f"    [{i}/{n_papers}] {title_snippet} …", end=" ", flush=True)
        cits = count_citations_in_year(pid, CITATION_YEAR, api_key)
        print(cits, flush=True)
        total_citations += cits
        time.sleep(0.3)

    impact_factor = round(total_citations / n_papers, 4) if n_papers > 0 else None

    result = {
        "journal": journal_key,
        "journal_name": display,
        "papers_in_window": n_papers,
        "citations_in_2024": total_citations,
        "impact_factor_2024": impact_factor,
    }

    print(f"\n  RESULT  →  IF 2024 = {impact_factor}  "
          f"({total_citations} citations / {n_papers} papers)", flush=True)
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute the 2024 independent impact factor for CS journals "
                    "using the Semantic Scholar API (conferences included)."
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        default=None,
        help="Semantic Scholar API key (optional but increases rate limits).",
    )
    parser.add_argument(
        "--journals",
        nargs="+",
        choices=list(JOURNALS.keys()),
        default=list(JOURNALS.keys()),
        help="Which journals to process (default: all three).",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        default="results.json",
        help="Path for the JSON results file (default: results.json).",
    )
    args = parser.parse_args()

    print("Independent Impact Factor — 2024")
    print("Data source : Semantic Scholar API")
    print("Window      : papers published in 2022–2023")
    print("Citations   : all citing papers (journals + conferences) in 2024")
    print("Formula     : citations_2024 / papers_2022_2023")

    results: list[dict] = []
    for jkey in args.journals:
        result = compute_impact_factor(jkey, args.api_key)
        results.append(result)

    # Summary table
    print(f"\n\n{'=' * 68}")
    print("SUMMARY — 2024 Independent Impact Factors")
    print(f"{'=' * 68}")
    header = f"{'Journal':<20}  {'Papers':>7}  {'Citations':>10}  {'IF 2024':>10}"
    print(header)
    print("-" * len(header))
    for r in results:
        if_str = f"{r['impact_factor_2024']:.4f}" if r["impact_factor_2024"] is not None else "N/A"
        print(
            f"{r['journal']:<20}  {r['papers_in_window']:>7}  "
            f"{r['citations_in_2024']:>10}  {if_str:>10}"
        )

    # Persist results
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
