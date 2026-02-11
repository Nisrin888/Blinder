"""Structured query engine for tabular (pipe-delimited) blinded data.

Instead of feeding raw chunks to the LLM and hoping it can parse tabular data,
this module extracts answers directly via Python — the LLM only gets the
pre-computed result to format as natural language.

Supports all entity categories (PII, PHI, PCI, legal, HR, finance).

Query types handled:
  - Point lookup:    "What is [PERSON_884]'s age?"     → grep row, return column
  - Multi-field:     "Give me [PERSON_884]'s details"  → grep row, return all columns
  - Reverse lookup:  "Who lives at [ADDRESS_123]?"     → search by value, return entity
  - Comparison:      "Compare [PERSON_1] and [PERSON_2]" → find both rows, side-by-side
  - Count:           "How many people are over 60?"    → compute across all rows
  - Extrema:         "Who is the oldest?"              → sort column, return top
  - Average/Stats:   "What's the average age?"         → math across column
  - Filtered list:   "List everyone in New York"       → filter by column value
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Matches any vault pseudonym: [PERSON_1], [SSN_3], [CREDIT_CARD_12], etc.
_PSEUDONYM_RE = re.compile(r"\[([A-Z][A-Z0-9_]*_\d+)\]")

SEPARATOR = " | "

# Query intent patterns
_COUNT_PATTERNS = re.compile(
    r"\b(how many|count|total number|number of)\b", re.IGNORECASE
)
_AVG_PATTERNS = re.compile(
    r"\b(average|mean|avg)\b", re.IGNORECASE
)
_SUM_PATTERNS = re.compile(
    r"\b(sum|total(?! number))\b", re.IGNORECASE
)
_EXTREMA_MAX_PATTERNS = re.compile(
    r"\b(oldest|highest|maximum|max|most|largest|biggest|top)\b", re.IGNORECASE
)
_EXTREMA_MIN_PATTERNS = re.compile(
    r"\b(youngest|lowest|minimum|min|least|smallest|bottom)\b", re.IGNORECASE
)
_COMPARE_PATTERNS = re.compile(
    r"\b(compare|difference between|versus|vs)\b", re.IGNORECASE
)
_FILTER_PATTERNS = re.compile(
    r"\b(list all|show all|list everyone|show everyone|all .+ (with|in|from|over|under|above|below))\b",
    re.IGNORECASE,
)

# Numeric column heuristic — column names that typically hold numbers
_NUMERIC_COLUMN_HINTS = re.compile(
    r"\b(age|salary|income|amount|balance|score|rating|count|total|price|cost|"
    r"weight|height|years?|months?|days?|number|quantity|rate|percentage|zip)\b",
    re.IGNORECASE,
)


@dataclass
class TabularData:
    """Parsed tabular document: header + data rows."""
    header: list[str]
    rows: list[list[str]]
    header_raw: str = ""

    @property
    def num_columns(self) -> int:
        return len(self.header)

    @property
    def num_rows(self) -> int:
        return len(self.rows)


@dataclass
class QueryResult:
    """Result of a structured tabular query."""
    success: bool
    context: str  # formatted context to hand to the LLM
    query_type: str = "unknown"
    details: str = ""


def is_tabular(text: str) -> bool:
    """Check if blinded text is pipe-delimited tabular data."""
    lines = text.split("\n", 5)
    pipe_lines = sum(1 for line in lines if line.count(SEPARATOR) >= 2)
    return pipe_lines >= 2


def parse_tabular(text: str) -> TabularData | None:
    """Parse pipe-delimited blinded text into structured form."""
    lines = text.split("\n")
    non_empty = [line for line in lines if line.strip()]
    if len(non_empty) < 2:
        return None

    header_raw = non_empty[0]
    header = [col.strip() for col in header_raw.split(SEPARATOR)]
    rows = []
    for line in non_empty[1:]:
        cells = [cell.strip() for cell in line.split(SEPARATOR)]
        # Pad or trim to match header length
        if len(cells) < len(header):
            cells.extend([""] * (len(header) - len(cells)))
        elif len(cells) > len(header):
            cells = cells[:len(header)]
        rows.append(cells)

    return TabularData(header=header, rows=rows, header_raw=header_raw)


def try_tabular_query(blinded_query: str, blinded_documents: list[str]) -> QueryResult | None:
    """Attempt to answer a query via structured extraction from tabular data.

    Returns a QueryResult with pre-computed context if successful,
    or None if the query can't be handled structurally (fall back to RAG).
    """
    # Find tabular documents
    tables: list[TabularData] = []
    for doc_text in blinded_documents:
        if is_tabular(doc_text):
            parsed = parse_tabular(doc_text)
            if parsed and parsed.num_rows > 0:
                tables.append(parsed)

    if not tables:
        return None  # no tabular data, fall back to RAG

    # Extract pseudonyms from the query
    pseudonyms = _PSEUDONYM_RE.findall(blinded_query)
    pseudo_set = {f"[{p}]" for p in pseudonyms}

    # Detect query intent and dispatch
    if _COMPARE_PATTERNS.search(blinded_query) and len(pseudo_set) >= 2:
        return _handle_comparison(blinded_query, tables, pseudo_set)

    if pseudo_set:
        if len(pseudo_set) == 1:
            return _handle_point_lookup(blinded_query, tables, list(pseudo_set)[0])
        # Multiple pseudonyms but not a compare — treat as multi-entity lookup
        return _handle_multi_lookup(blinded_query, tables, pseudo_set)

    if _COUNT_PATTERNS.search(blinded_query):
        return _handle_count(blinded_query, tables)

    if _AVG_PATTERNS.search(blinded_query):
        return _handle_average(blinded_query, tables)

    if _SUM_PATTERNS.search(blinded_query):
        return _handle_sum(blinded_query, tables)

    if _EXTREMA_MAX_PATTERNS.search(blinded_query):
        return _handle_extrema(blinded_query, tables, direction="max")

    if _EXTREMA_MIN_PATTERNS.search(blinded_query):
        return _handle_extrema(blinded_query, tables, direction="min")

    if _FILTER_PATTERNS.search(blinded_query):
        return _handle_filter(blinded_query, tables)

    # Reverse lookup: query contains a non-entity pseudonym value
    # (e.g., [ADDRESS_123] without a PERSON pseudonym)
    if _PSEUDONYM_RE.search(blinded_query):
        return _handle_reverse_lookup(blinded_query, tables)

    return None  # can't handle structurally, fall back to RAG


# ---------------------------------------------------------------------------
# Query handlers
# ---------------------------------------------------------------------------

def _find_rows_with_value(tables: list[TabularData], value: str) -> list[tuple[TabularData, list[str]]]:
    """Find all rows across all tables containing the given value."""
    results = []
    for table in tables:
        for row in table.rows:
            if any(value in cell for cell in row):
                results.append((table, row))
    return results


def _format_row(header: list[str], row: list[str]) -> str:
    """Format a row as key-value pairs."""
    pairs = []
    for col, val in zip(header, row):
        if val.strip():
            pairs.append(f"  - {col}: {val}")
    return "\n".join(pairs)


def _find_column(header: list[str], query: str) -> int | None:
    """Try to match a column name from the query text."""
    query_lower = query.lower()
    # Direct match: column name appears in query
    for i, col in enumerate(header):
        if col.lower() in query_lower:
            return i
    return None


def _find_numeric_column(header: list[str], query: str) -> int | None:
    """Find the numeric column most relevant to the query."""
    # First try direct column name match
    idx = _find_column(header, query)
    if idx is not None:
        return idx
    # Fall back to first numeric-looking column
    for i, col in enumerate(header):
        if _NUMERIC_COLUMN_HINTS.search(col):
            return i
    return None


def _get_numeric_values(table: TabularData, col_idx: int) -> list[tuple[float, list[str]]]:
    """Extract numeric values from a column, paired with their rows."""
    results = []
    for row in table.rows:
        try:
            val = float(row[col_idx].replace(",", "").replace("$", "").strip())
            results.append((val, row))
        except (ValueError, IndexError):
            continue
    return results


def _handle_point_lookup(
    query: str, tables: list[TabularData], pseudonym: str
) -> QueryResult:
    """Find a specific entity's data."""
    matches = _find_rows_with_value(tables, pseudonym)
    if not matches:
        return QueryResult(
            success=False,
            context=f"No data found for {pseudonym} in the documents.",
            query_type="point_lookup",
        )

    parts = []
    for table, row in matches:
        parts.append(f"Data for {pseudonym}:\n{_format_row(table.header, row)}")

    context = "\n\n".join(parts)
    logger.info("Point lookup: found %d rows for %s", len(matches), pseudonym)
    return QueryResult(
        success=True,
        context=context,
        query_type="point_lookup",
        details=f"Found {len(matches)} row(s) for {pseudonym}",
    )


def _handle_multi_lookup(
    query: str, tables: list[TabularData], pseudo_set: set[str]
) -> QueryResult:
    """Find data for multiple entities."""
    parts = []
    for pseudo in sorted(pseudo_set):
        matches = _find_rows_with_value(tables, pseudo)
        if matches:
            for table, row in matches:
                parts.append(f"Data for {pseudo}:\n{_format_row(table.header, row)}")
        else:
            parts.append(f"No data found for {pseudo}.")

    context = "\n\n".join(parts)
    return QueryResult(success=True, context=context, query_type="multi_lookup")


def _handle_comparison(
    query: str, tables: list[TabularData], pseudo_set: set[str]
) -> QueryResult:
    """Compare two or more entities side by side."""
    parts = ["Comparison:"]
    for pseudo in sorted(pseudo_set):
        matches = _find_rows_with_value(tables, pseudo)
        if matches:
            table, row = matches[0]
            parts.append(f"\n{pseudo}:\n{_format_row(table.header, row)}")
        else:
            parts.append(f"\n{pseudo}: No data found.")

    context = "\n".join(parts)
    return QueryResult(success=True, context=context, query_type="comparison")


def _handle_reverse_lookup(
    query: str, tables: list[TabularData]
) -> QueryResult:
    """Find which entity has a specific value (e.g., 'Who lives at [ADDRESS_123]?')."""
    pseudonyms = _PSEUDONYM_RE.findall(query)
    results = []
    for pseudo in pseudonyms:
        full = f"[{pseudo}]"
        matches = _find_rows_with_value(tables, full)
        for table, row in matches:
            results.append(f"Row containing {full}:\n{_format_row(table.header, row)}")

    if not results:
        return QueryResult(success=False, context="No matching rows found.", query_type="reverse_lookup")

    context = "\n\n".join(results)
    return QueryResult(success=True, context=context, query_type="reverse_lookup")


def _handle_count(query: str, tables: list[TabularData]) -> QueryResult:
    """Count rows matching a condition."""
    for table in tables:
        col_idx = _find_numeric_column(table.header, query)
        if col_idx is None:
            # Count total rows
            context = f"Total rows in the dataset: {table.num_rows}"
            return QueryResult(success=True, context=context, query_type="count")

        col_name = table.header[col_idx]
        numeric_vals = _get_numeric_values(table, col_idx)

        # Try to extract a threshold from the query (e.g., "over 60")
        threshold_match = re.search(r"(over|above|greater than|more than|>)\s*(\d+(?:\.\d+)?)", query, re.IGNORECASE)
        if threshold_match:
            threshold = float(threshold_match.group(2))
            count = sum(1 for val, _ in numeric_vals if val > threshold)
            context = (
                f"ANALYSIS METHOD: Scanned {table.num_rows} rows in the dataset. "
                f"Parsed the '{col_name}' column as numeric values across "
                f"{len(numeric_vals)} valid rows (non-numeric entries excluded). "
                f"Applied filter: {col_name} > {threshold}.\n\n"
                f"RESULT: {count} out of {len(numeric_vals)} rows have "
                f"{col_name} greater than {threshold}."
            )
            return QueryResult(success=True, context=context, query_type="count")

        threshold_match = re.search(r"(under|below|less than|fewer than|<)\s*(\d+(?:\.\d+)?)", query, re.IGNORECASE)
        if threshold_match:
            threshold = float(threshold_match.group(2))
            count = sum(1 for val, _ in numeric_vals if val < threshold)
            context = (
                f"ANALYSIS METHOD: Scanned {table.num_rows} rows in the dataset. "
                f"Parsed the '{col_name}' column as numeric values across "
                f"{len(numeric_vals)} valid rows (non-numeric entries excluded). "
                f"Applied filter: {col_name} < {threshold}.\n\n"
                f"RESULT: {count} out of {len(numeric_vals)} rows have "
                f"{col_name} less than {threshold}."
            )
            return QueryResult(success=True, context=context, query_type="count")

        # No threshold — just count all rows
        context = (
            f"ANALYSIS METHOD: Scanned {table.num_rows} rows in the dataset. "
            f"Counted rows with valid '{col_name}' data.\n\n"
            f"RESULT: {len(numeric_vals)} rows have valid {col_name} data "
            f"(out of {table.num_rows} total rows)."
        )
        return QueryResult(success=True, context=context, query_type="count")

    return QueryResult(success=False, context="No tabular data to count.", query_type="count")


def _handle_average(query: str, tables: list[TabularData]) -> QueryResult:
    """Compute average of a numeric column."""
    for table in tables:
        col_idx = _find_numeric_column(table.header, query)
        if col_idx is None:
            continue

        col_name = table.header[col_idx]
        numeric_vals = _get_numeric_values(table, col_idx)
        if not numeric_vals:
            continue

        values = [v for v, _ in numeric_vals]
        avg = sum(values) / len(values)
        context = (
            f"ANALYSIS METHOD: Extracted numeric values from the '{col_name}' column "
            f"across {len(values)} valid rows (out of {table.num_rows} total). "
            f"Computed the arithmetic mean: sum of all values / count.\n\n"
            f"RESULT: Average {col_name} = {avg:.2f} "
            f"(min: {min(values):.2f}, max: {max(values):.2f}, "
            f"computed from {len(values)} rows)."
        )
        return QueryResult(success=True, context=context, query_type="average")

    return QueryResult(success=False, context="Could not find a numeric column to average.", query_type="average")


def _handle_sum(query: str, tables: list[TabularData]) -> QueryResult:
    """Compute sum of a numeric column."""
    for table in tables:
        col_idx = _find_numeric_column(table.header, query)
        if col_idx is None:
            continue

        col_name = table.header[col_idx]
        numeric_vals = _get_numeric_values(table, col_idx)
        if not numeric_vals:
            continue

        values = [v for v, _ in numeric_vals]
        total = sum(values)
        context = (
            f"ANALYSIS METHOD: Extracted numeric values from the '{col_name}' column "
            f"across {len(values)} valid rows (out of {table.num_rows} total). "
            f"Summed all values.\n\n"
            f"RESULT: Sum of {col_name} = {total:.2f} "
            f"(from {len(values)} rows)."
        )
        return QueryResult(success=True, context=context, query_type="sum")

    return QueryResult(success=False, context="Could not find a numeric column to sum.", query_type="sum")


def _handle_extrema(
    query: str, tables: list[TabularData], direction: str = "max"
) -> QueryResult:
    """Find the row with the highest/lowest value in a numeric column."""
    for table in tables:
        col_idx = _find_numeric_column(table.header, query)
        if col_idx is None:
            continue

        col_name = table.header[col_idx]
        numeric_vals = _get_numeric_values(table, col_idx)
        if not numeric_vals:
            continue

        if direction == "max":
            best_val, best_row = max(numeric_vals, key=lambda x: x[0])
            label = "highest"
        else:
            best_val, best_row = min(numeric_vals, key=lambda x: x[0])
            label = "lowest"

        context = (
            f"ANALYSIS METHOD: Extracted numeric values from the '{col_name}' column "
            f"across {len(numeric_vals)} valid rows (out of {table.num_rows} total). "
            f"Sorted by {col_name} to find the {label} value.\n\n"
            f"RESULT: Row with {label} {col_name} ({best_val}):\n"
            f"{_format_row(table.header, best_row)}"
        )
        return QueryResult(success=True, context=context, query_type="extrema")

    return QueryResult(success=False, context="Could not find a numeric column.", query_type="extrema")


def _handle_filter(query: str, tables: list[TabularData]) -> QueryResult:
    """Filter rows by a condition and return matching rows."""
    # Try to find a threshold filter (e.g., "all people over 60")
    for table in tables:
        col_idx = _find_numeric_column(table.header, query)
        if col_idx is None:
            continue

        col_name = table.header[col_idx]
        numeric_vals = _get_numeric_values(table, col_idx)

        threshold_match = re.search(r"(over|above|greater than|more than|>)\s*(\d+(?:\.\d+)?)", query, re.IGNORECASE)
        if threshold_match:
            threshold = float(threshold_match.group(2))
            matches = [(v, r) for v, r in numeric_vals if v > threshold]
        else:
            threshold_match = re.search(r"(under|below|less than|<)\s*(\d+(?:\.\d+)?)", query, re.IGNORECASE)
            if threshold_match:
                threshold = float(threshold_match.group(2))
                matches = [(v, r) for v, r in numeric_vals if v < threshold]
            else:
                continue

        if not matches:
            context = f"No rows found matching the filter on {col_name}."
            return QueryResult(success=True, context=context, query_type="filter")

        # Cap at 20 rows to not overwhelm the LLM
        display_matches = matches[:20]
        parts = [
            f"ANALYSIS METHOD: Scanned {table.num_rows} rows in the dataset. "
            f"Parsed the '{col_name}' column as numeric values across "
            f"{len(numeric_vals)} valid rows. Applied filter to find matching rows.\n\n"
            f"RESULT: Found {len(matches)} rows matching filter on {col_name}:\n"
        ]
        for val, row in display_matches:
            parts.append(_format_row(table.header, row))
            parts.append("")  # blank line between rows

        if len(matches) > 20:
            parts.append(f"... and {len(matches) - 20} more rows.")

        context = "\n".join(parts)
        return QueryResult(success=True, context=context, query_type="filter")

    return None  # couldn't handle, fall back to RAG
