# Independent Impact Factor for CS Journals

Computes an independent impact factor for a journal using
the [Semantic Scholar](https://www.semanticscholar.org/) API.

**Key differences from the official JCR impact factor:** 

- The code and data is transparent
- citations from *conference papers* are included (not just journal-to-journal citations), giving a more complete picture of how widely the research is actually cited in the CS community.

## Journals covered

| Key | Journal |
|-----|---------|
| `IEEE TSE` | IEEE Transactions on Software Engineering |
| `ACM TOSEM` | ACM Transactions on Software Engineering and Methodology |
| `Springer EMSE` | Empirical Software Engineering |
| `JSS` | Journal of Systems and Software |
| `IST` | Information and Software Technology |

## Formula

```
IF_Y = citations_in_Y_to_papers_published_in_(Y-2)_or_(Y-1)
       ──────────────────────────────────────────────────────────
       number_of_papers_published_in_(Y-2)_or_(Y-1)
```

This is the same two-year sliding window used by Clarivate/JCR.

## Requirements

- Python 3.9+
- `requests` library

```bash
pip install -r requirements.txt
```

## Usage

The list of journals is defined in a JSON file (e.g. `se.json`).
Output filenames are derived from that file's stem.

```bash
# Run for all journals in se.json for citation year 2024
python compute_impact_factor.py --journals-file se.json 2024

# Run a combined summary for citation years 2023, 2024, and 2025
python compute_impact_factor.py --journals-file se.json --all

# With a Semantic Scholar API key (higher rate limits)
python compute_impact_factor.py --journals-file se.json 2024 --api-key YOUR_KEY

# Run for a subset of journals from the file
python compute_impact_factor.py --journals-file se.json 2024 --journals "IEEE TSE"
```

Results are printed as a summary table and written to:

- `if-{stem}.md` for the Markdown summary
- `results-{stem}.json` for the structured data

For example, `python compute_impact_factor.py --journals-file se.json 2024` writes
`if-se.md` and `results-se.json`.

With `--all`, the same filenames are used but the content covers all years.

## Notes

- The script uses the public Semantic Scholar Graph API v1.
  Request a free API key at https://www.semanticscholar.org/product/api
  to avoid hitting the anonymous rate limit (≈ 1 req/s).
- Semantic Scholar's coverage of older or smaller venues may be incomplete;
  the numbers therefore represent a lower bound.
- Because venue names vary across records, the script accepts several
  spelling variants for each journal and matches them case-insensitively.
