#!/usr/bin/env python3
"""
Compute an independent impact factor for CS journals using the Semantic
Scholar API.

Unlike the official JCR impact factor, this computation:
  - Uses Semantic Scholar as data source (broader coverage than Web of Science)
  - Includes citations from conference papers (not only journal-to-journal)

For a given citation year Y, the formula follows the same 2-year window as JCR:
    IF_Y = citations_in_Y_to_papers_published_in_(Y-2)_or_(Y-1)
           -----------------------------------------------------
           number_of_papers_published_in_(Y-2)_or_(Y-1)

Journals are loaded from a JSON file (e.g. se.json). Output files are named
after the JSON file's stem: if-se.md and results-se.json.
"""

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = "https://api.semanticscholar.org/graph/v1"
ALL_YEARS = [2023, 2024, 2025]
CACHE_PATH = ".semanticscholar-cache.sqlite3"


def load_journals(journals_file: str) -> dict[str, dict]:
    """Load journal definitions from a JSON file."""
    with open(journals_file, encoding="utf-8") as fh:
        return json.load(fh)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

RETRY_DELAYS = [10, 30, 60]  # seconds between retries


class RequestCache:
    """Persistent cache for Semantic Scholar API GET responses."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS request_cache (
                cache_key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                params_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    @staticmethod
    def _cache_key(url: str, params: dict) -> str:
        payload = json.dumps(
            {"url": url, "params": params},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, url: str, params: dict) -> Optional[dict]:
        cache_key = self._cache_key(url, params)
        row = self.conn.execute(
            "SELECT response_json FROM request_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(self, url: str, params: dict, response: dict) -> None:
        cache_key = self._cache_key(url, params)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO request_cache
                (cache_key, url, params_json, response_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                cache_key,
                url,
                json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
                json.dumps(response, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _get(
    url: str,
    params: dict,
    api_key: Optional[str] = None,
    cache: Optional[RequestCache] = None,
    sleep_after: float = 0.0,
) -> dict:
    """Send a GET request with basic retry / rate-limit handling.

    Sleeps *sleep_after* seconds after a real network call; cache hits skip the
    sleep entirely so cached runs finish without unnecessary delays.
    """
    if cache is not None:
        cached_response = cache.get(url, params)
        if cached_response is not None:
            return cached_response

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
            data = resp.json()
            if cache is not None:
                cache.set(url, params, data)
            if sleep_after > 0:
                time.sleep(sleep_after)
            return data
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


def fetch_papers(
    journal_key: str,
    year: int,
    journals: dict[str, dict],
    api_key: Optional[str] = None,
    cache: Optional[RequestCache] = None,
) -> list[dict]:
    """
    Fetch all papers published in *journal_key* during *year* using the
    Semantic Scholar bulk paper-search endpoint. Results are filtered to keep
    only papers whose recorded venue matches the journal.
    """
    venue_names = journals[journal_key]["venue_names"]
    papers: list[dict] = []
    token: Optional[str] = None
    limit = 1000

    print(f"    Fetching {journal_key} papers for {year} …", flush=True)

    while True:
        params = {
            "fields": "paperId,title,year,venue,publicationVenue",
            "venue": ",".join(venue_names),
            "year": str(year),
            "limit": limit,
        }
        if token:
            params["token"] = token

        data = _get(f"{API_BASE}/paper/search/bulk", params, api_key, cache, sleep_after=1.0)

        batch = data.get("data") or []
        for paper in batch:
            if paper.get("year") == year and _venue_match(paper, venue_names):
                papers.append(paper)

        token = data.get("token")
        if not batch or not token:
            break

    print(f"      → {len(papers)} papers matched", flush=True)
    return papers


def count_citations_in_year(
    paper_id: str,
    target_year: int,
    api_key: Optional[str] = None,
    cache: Optional[RequestCache] = None,
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
        data = _get(f"{API_BASE}/paper/{paper_id}/citations", params, api_key, cache, sleep_after=0.5)

        batch = data.get("data") or []
        for item in batch:
            citing = item.get("citingPaper") or {}
            if citing.get("year") == target_year:
                count += 1

        if len(batch) < limit:
            break
        offset += limit

    return count


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def publication_years(citation_year: int) -> list[int]:
    """Return the two publication years that contribute to the given IF year."""
    return [citation_year - 2, citation_year - 1]


def compute_impact_factor(
    journal_key: str,
    citation_year: int,
    journals: dict[str, dict],
    api_key: Optional[str] = None,
    cache: Optional[RequestCache] = None,
) -> dict:
    """Compute the impact factor for *journal_key* in *citation_year*."""
    display = journals[journal_key]["display"]
    pub_years = publication_years(citation_year)
    print(f"\n{'=' * 68}")
    print(f"  {journal_key}  —  {display}")
    print(f"{'=' * 68}", flush=True)

    # Step 1: collect papers published in the two-year window
    all_papers: list[dict] = []
    for year in pub_years:
        year_papers = fetch_papers(journal_key, year, journals, api_key, cache)
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
    print(f"\n  Total unique papers ({pub_years[0]}–{pub_years[-1]}): {n_papers}", flush=True)

    if n_papers == 0:
        print("  [warning] no papers found — cannot compute IF", flush=True)
        return {
            "journal": journal_key,
            "journal_name": display,
            "citation_year": citation_year,
            "publication_years": pub_years,
            "papers_in_window": 0,
            "citations_in_year": 0,
            "impact_factor": None,
        }

    # Step 2: count citations from citation_year to each paper
    print(f"\n  Counting citations in {citation_year} (including conferences) …", flush=True)
    total_citations = 0

    for i, paper in enumerate(unique_papers, start=1):
        pid = paper["paperId"]
        title_snippet = (paper.get("title") or "")[:60]
        print(f"    [{i}/{n_papers}] {title_snippet} …", end=" ", flush=True)
        cits = count_citations_in_year(pid, citation_year, api_key, cache)
        print(cits, flush=True)
        total_citations += cits

    impact_factor = round(total_citations / n_papers, 4) if n_papers > 0 else None

    result = {
        "journal": journal_key,
        "journal_name": display,
        "citation_year": citation_year,
        "publication_years": pub_years,
        "papers_in_window": n_papers,
        "citations_in_year": total_citations,
        "impact_factor": impact_factor,
    }

    print(f"\n  RESULT  →  IF {citation_year} = {impact_factor}  "
           f"({total_citations} citations / {n_papers} papers)", flush=True)
    return result


def format_summary_markdown(results: list[dict], citation_year: int) -> str:
    """Render a Markdown summary for the computed impact factors."""
    pub_years = publication_years(citation_year)
    lines = [
        f"# Independent Impact Factor {citation_year}",
        "",
        "- Data source: Semantic Scholar API",
        f"- Publication window: {pub_years[0]}-{pub_years[-1]}",
        f"- Citation year: {citation_year}",
        f"- Formula: citations_{citation_year} / papers_{pub_years[0]}_{pub_years[-1]}",
        "",
        f"| Journal | Papers ({pub_years[0]}-{pub_years[-1]}) | Citations ({citation_year}) | IF {citation_year} |",
        "| --- | ---: | ---: | ---: |",
    ]
    for result in results:
        if_str = (
            f"{result['impact_factor']:.4f}"
            if result["impact_factor"] is not None
            else "N/A"
        )
        lines.append(
            f"| {result['journal']} | {result['papers_in_window']} | "
            f"{result['citations_in_year']} | {if_str} |"
        )
    lines.append("")
    return "\n".join(lines)


def _if_str(impact_factor: Optional[float]) -> str:
    """Format an impact factor for console or Markdown output."""
    return f"{impact_factor:.4f}" if impact_factor is not None else "N/A"


def format_all_years_summary_markdown(results_by_year: dict[int, list[dict]]) -> str:
    """Render a Markdown summary covering all configured citation years."""
    years = sorted(results_by_year)
    journal_order = list(next(iter(results_by_year.values())))
    header = " | ".join(["Journal"] + [f"IF {year}" for year in years])
    separator = " | ".join(["---"] + ["---:" for _ in years])

    lines = [
        "# Independent Impact Factor Summary",
        "",
        "- Data source: Semantic Scholar API",
        f"- Citation years: {', '.join(str(year) for year in years)}",
        "- Formula: each IF_Y uses citations in Y to papers published in Y-2 and Y-1",
        "",
        f"| {header} |",
        f"| {separator} |",
    ]

    for journal_result in journal_order:
        journal = journal_result["journal"]
        row = [journal]
        for year in years:
            result = next(r for r in results_by_year[year] if r["journal"] == journal)
            row.append(_if_str(result["impact_factor"]))
        lines.append(f"| {' | '.join(row)} |")

    lines.append("")
    return "\n".join(lines)


def print_summary(results: list[dict], citation_year: int) -> None:
    """Print the single-year summary table."""
    print(f"\n\n{'=' * 68}")
    print(f"SUMMARY — {citation_year} Independent Impact Factors")
    print(f"{'=' * 68}")
    header = f"{'Journal':<20}  {'Papers':>7}  {'Citations':>10}  {f'IF {citation_year}':>10}"
    print(header)
    print("-" * len(header))
    for result in results:
        print(
            f"{result['journal']:<20}  {result['papers_in_window']:>7}  "
            f"{result['citations_in_year']:>10}  {_if_str(result['impact_factor']):>10}"
        )


def print_all_years_summary(results_by_year: dict[int, list[dict]]) -> None:
    """Print the multi-year summary table."""
    years = sorted(results_by_year)
    journal_order = [result["journal"] for result in next(iter(results_by_year.values()))]

    print(f"\n\n{'=' * 68}")
    print("SUMMARY — Independent Impact Factors")
    print(f"{'=' * 68}")
    header = f"{'Journal':<20}" + "".join(f"  {f'IF {year}':>10}" for year in years)
    print(header)
    print("-" * len(header))

    for journal in journal_order:
        row = f"{journal:<20}"
        for year in years:
            result = next(r for r in results_by_year[year] if r["journal"] == journal)
            row += f"  {_if_str(result['impact_factor']):>10}"
        print(row)


def compute_year_results(
    citation_year: int,
    journal_keys: list[str],
    journals: dict[str, dict],
    api_key: Optional[str] = None,
    cache: Optional[RequestCache] = None,
) -> list[dict]:
    """Compute impact factors for all selected journals in one citation year."""
    pub_years = publication_years(citation_year)

    print(f"\nIndependent Impact Factor — {citation_year}")
    print("Data source : Semantic Scholar API")
    print(f"Window      : papers published in {pub_years[0]}-{pub_years[-1]}")
    print(f"Citations   : all citing papers (journals + conferences) in {citation_year}")
    print(f"Formula     : citations_{citation_year} / papers_{pub_years[0]}_{pub_years[-1]}")

    results: list[dict] = []
    for journal_key in journal_keys:
        results.append(compute_impact_factor(journal_key, citation_year, journals, api_key, cache))
    return results


def write_single_year_outputs(results: list[dict], citation_year: int, prefix: str) -> None:
    """Write the single-year JSON and Markdown outputs."""
    summary_path = f"if-{prefix}.md"
    results_path = f"results-{prefix}.json"

    with open(results_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write(format_summary_markdown(results, citation_year))

    print(f"\nSummary written to {summary_path}")
    print(f"Results written to {results_path}")


def write_all_years_outputs(results_by_year: dict[int, list[dict]], prefix: str) -> None:
    """Write the combined multi-year JSON and Markdown outputs."""
    summary_path = f"if-{prefix}.md"
    results_path = f"results-{prefix}.json"

    with open(results_path, "w", encoding="utf-8") as fh:
        json.dump(results_by_year, fh, indent=2, ensure_ascii=False)
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write(format_all_years_summary_markdown(results_by_year))

    print(f"\nSummary written to {summary_path}")
    print(f"Results written to {results_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute the independent impact factor for a given year for "
                    "CS journals using the Semantic Scholar API "
                    "(conferences included)."
    )
    parser.add_argument(
        "year",
        type=int,
        nargs="?",
        help="Citation year used for the impact factor computation.",
    )
    parser.add_argument(
        "--journals-file",
        metavar="FILE",
        required=True,
        help="JSON file defining the journals to process (e.g. se.json). "
             "Output files are named after the file stem: if-<stem>.md and results-<stem>.json.",
    )
    parser.add_argument(
        "--journals",
        nargs="+",
        default=None,
        help="Subset of journal keys from the journals file to process (default: all).",
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        default=None,
        help="Semantic Scholar API key (optional but increases rate limits).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Compute impact factors for 2023, 2024, and 2025 and write a combined summary.",
    )
    parser.add_argument(
        "--cache-path",
        default=CACHE_PATH,
        help=(
            "SQLite file used to cache API responses so interrupted runs can resume "
            f"(default: {CACHE_PATH})."
        ),
    )
    args = parser.parse_args()
    if args.all and args.year is not None:
        parser.error("year cannot be used together with --all")
    if not args.all and args.year is None:
        parser.error("year is required unless --all is used")

    journals = load_journals(args.journals_file)
    prefix = Path(args.journals_file).stem

    journal_keys = args.journals if args.journals is not None else list(journals.keys())
    unknown = [k for k in journal_keys if k not in journals]
    if unknown:
        parser.error(f"unknown journal keys: {', '.join(unknown)}")

    cache = RequestCache(args.cache_path)
    try:
        print(f"Using request cache: {args.cache_path}", flush=True)
        print(f"Journals file      : {args.journals_file} (prefix: {prefix})", flush=True)

        if args.all:
            results_by_year: dict[int, list[dict]] = {}
            for year in ALL_YEARS:
                results_by_year[year] = compute_year_results(
                    year, journal_keys, journals, args.api_key, cache
                )
            print_all_years_summary(results_by_year)
            write_all_years_outputs(results_by_year, prefix)
            return

        if args.year < 2:
            raise SystemExit("year must be at least 2")

        results = compute_year_results(args.year, journal_keys, journals, args.api_key, cache)
        print_summary(results, args.year)
        write_single_year_outputs(results, args.year, prefix)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
