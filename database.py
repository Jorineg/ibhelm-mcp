"""
Database utilities for IBHelm MCP Server.
- Connection pool management
- Query validation and execution
- Smart truncation
- TOON format conversion
- RLS context management
"""

import logging
import re
import time
import asyncpg
from typing import Any, Literal
from contextvars import ContextVar

from config import (
    DATABASE_URL, MAX_RESPONSE_CHARS, MAX_CELL_CHARS, 
    CELL_PREVIEW_CHARS, MIN_ROWS_FOR_PREVIEW
)

logger = logging.getLogger("ibhelm.mcp.database")

# Context variable for current user email (set per-request)
_current_user_email: ContextVar[str | None] = ContextVar('current_user_email', default=None)


# =============================================================================
# Connection Pool
# =============================================================================
_pool = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the database connection pool."""
    global _pool
    if _pool is None:
        logger.info("Creating database connection pool")
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5, command_timeout=30)
        logger.info("Database pool created (min=1, max=5)")
    return _pool


# =============================================================================
# RLS User Context
# =============================================================================

def set_user_context(email: str | None):
    """Set the current user email for RLS policies (call at start of request)."""
    _current_user_email.set(email)
    if email:
        logger.debug(f"User context set: {email}")


def get_user_context() -> str | None:
    """Get the current user email."""
    return _current_user_email.get()


async def _set_rls_context(conn: asyncpg.Connection, user_email: str | None):
    """Set session variables for RLS policies before executing queries."""
    if user_email:
        # Use set_config with is_local=true for transaction-scoped setting
        await conn.execute(
            "SELECT set_config('app.user_email', $1, true)",
            user_email
        )
        logger.debug(f"RLS context set for: {user_email}")


# =============================================================================
# Query Validation
# =============================================================================
HELPFUL_ERRORS = {
    "relation": "Table not found. Use get_schema() to see available tables.",
    "column": "Column not found. Use get_schema(schema, table) to see columns.",
    "permission denied": "Permission denied. This is a read-only connection.",
    "syntax error": "SQL syntax error. Check your query syntax.",
    "canceling statement": "Query timeout (30s limit). Add more specific WHERE conditions or LIMIT.",
}


def enhance_error(error_msg: str) -> str:
    """Add helpful hints to error messages."""
    error_lower = error_msg.lower()
    for key, hint in HELPFUL_ERRORS.items():
        if key in error_lower:
            return f"{error_msg}\n\n💡 Hint: {hint}"
    return error_msg


def strip_sql_comments(query: str) -> str:
    """Strip SQL comments (-- and /* */) from query."""
    # Remove single-line comments (-- ...)
    query = re.sub(r'--[^\n]*', '', query)
    # Remove multi-line comments (/* ... */)
    query = re.sub(r'/\*.*?\*/', '', query, flags=re.DOTALL)
    return query.strip()


def validate_query(query: str) -> tuple[bool, str]:
    """Validate that a query is safe to execute (SELECT only)."""
    clean_query = strip_sql_comments(query)
    query_upper = clean_query.upper().strip()
    
    if not query_upper.startswith(("SELECT", "WITH")):
        return False, "❌ Only SELECT queries allowed.\n\n💡 Start with SELECT or WITH (for CTEs)."
    
    dangerous = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "GRANT", "REVOKE", "EXECUTE", "COPY"]
    for kw in dangerous:
        if f" {kw} " in f" {query_upper} " or query_upper.startswith(f"{kw} "):
            return False, f"❌ {kw} statements not allowed.\n\n💡 This is a read-only connection."
    return True, ""


# =============================================================================
# Smart Truncation
# =============================================================================
def truncate_cell(value: Any, max_chars: int = MAX_CELL_CHARS, preview_chars: int = CELL_PREVIEW_CHARS) -> tuple[Any, bool]:
    """Truncate a single cell value if too long. Returns (value, was_truncated)."""
    if value is None:
        return None, False
    
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value, False
        half = preview_chars
        truncated = f"{value[:half]}…[{len(value) - 2*half} chars]…{value[-half:]}"
        return truncated, True
    
    str_val = str(value)
    if len(str_val) <= max_chars:
        return value, False
    
    half = preview_chars
    return f"{str_val[:half]}…[{len(str_val) - 2*half} chars]…{str_val[-half:]}", True


def estimate_row_chars(row: dict) -> int:
    """Estimate character count for a row."""
    total = 0
    for v in row.values():
        if v is None:
            total += 1
        elif isinstance(v, str):
            total += len(v)
        else:
            total += len(str(v))
    return total


def smart_truncate(rows: list[dict], max_total_chars: int = MAX_RESPONSE_CHARS, 
                   max_cell_chars: int = MAX_CELL_CHARS, force_full: bool = False) -> tuple[list[dict], dict]:
    """
    Smart truncation based on total character count.
    
    Returns: (possibly_truncated_rows, metadata)
    
    Strategy:
    1. If force_full=True, return all rows with cell truncation only
    2. Estimate total size
    3. If small enough, return all
    4. Otherwise, show first N + last N rows, with cell truncation
    """
    if not rows:
        return [], {"truncated": False, "total_rows": 0, "total_chars": 0}
    
    total_rows = len(rows)
    
    # Always truncate individual cells first
    cell_truncated = False
    processed_rows = []
    total_chars = 0
    
    for row in rows:
        new_row = {}
        for k, v in row.items():
            truncated_v, was_truncated = truncate_cell(v, max_cell_chars)
            new_row[k] = truncated_v
            if was_truncated:
                cell_truncated = True
        processed_rows.append(new_row)
        total_chars += estimate_row_chars(new_row)
    
    meta = {
        "total_rows": total_rows,
        "total_chars_approx": total_chars,
        "cells_truncated": cell_truncated,
    }
    
    if force_full:
        meta["truncated"] = False
        meta["rows_shown"] = total_rows
        return processed_rows, meta
    
    if total_chars <= max_total_chars:
        meta["truncated"] = False
        meta["rows_shown"] = total_rows
        return processed_rows, meta
    
    if total_rows <= MIN_ROWS_FOR_PREVIEW * 2:
        meta["truncated"] = False
        meta["rows_shown"] = total_rows
        return processed_rows, meta
    
    # Calculate how many rows we can show
    avg_row_chars = total_chars / total_rows
    max_rows = max(MIN_ROWS_FOR_PREVIEW * 2, int(max_total_chars / avg_row_chars))
    show_each = max(MIN_ROWS_FOR_PREVIEW, max_rows // 2)
    
    if show_each * 2 >= total_rows:
        meta["truncated"] = False
        meta["rows_shown"] = total_rows
        return processed_rows, meta
    
    # Take first N and last N
    first = processed_rows[:show_each]
    last = processed_rows[-show_each:]
    omitted = total_rows - (show_each * 2)
    
    meta["truncated"] = True
    meta["rows_shown"] = show_each * 2
    meta["rows_omitted"] = omitted
    meta["preview"] = f"first {show_each} + last {show_each} of {total_rows}"
    
    return first + last, meta


# =============================================================================
# TOON Format
# =============================================================================
def to_toon(rows: list[dict]) -> str:
    """Convert rows to TOON format (Token-Oriented Object Notation).
    
    Format: rows[count]{field1,field2,...}:
              value1,value2,...
    """
    if not rows:
        return "rows[0]{}: (empty)"
    
    fields = list(rows[0].keys())
    header = f"rows[{len(rows)}]{{{','.join(fields)}}}:"
    
    lines = [header]
    for row in rows:
        cells = []
        for f in fields:
            v = row.get(f)
            if v is None:
                cells.append("∅")
            elif isinstance(v, str):
                v = v.replace('\n', '↵').replace('\t', '→').replace('\r', '')
                if ',' in v or '"' in v:
                    v = '"' + v.replace('"', '""') + '"'
                cells.append(v)
            elif isinstance(v, bool):
                cells.append("T" if v else "F")
            else:
                cells.append(str(v))
        lines.append("  " + ",".join(cells))
    
    return "\n".join(lines)


def compute_column_stats(rows: list[dict]) -> dict:
    """Compute basic statistics for each column."""
    if not rows:
        return {}
    
    stats = {}
    for col in rows[0].keys():
        values = [r.get(col) for r in rows if r.get(col) is not None]
        non_null = len(values)
        
        col_stats = {"non_null": non_null, "null": len(rows) - non_null}
        
        numeric = [v for v in values if isinstance(v, (int, float))]
        if numeric:
            col_stats.update({"min": min(numeric), "max": max(numeric)})
        
        strings = [v for v in values if isinstance(v, str)]
        if strings:
            unique = len(set(strings))
            col_stats["unique"] = unique
            if unique <= 5:
                col_stats["sample_values"] = list(set(strings))[:5]
        
        stats[col] = col_stats
    return stats


# =============================================================================
# Core Query Execution
# =============================================================================
async def execute_query(
    query: str,
    format: Literal["json", "toon"] = "toon",
    include_stats: bool = False,
    limit: int | None = None,
    full_output: bool = False,
    user_email: str | None = None
) -> dict:
    """Execute query with smart truncation, TOON format, and RLS context.
    
    The user_email is used to set RLS context for email visibility policies.
    If not provided, falls back to the context variable set via set_user_context().
    """
    query_preview = query[:100].replace('\n', ' ') + ('...' if len(query) > 100 else '')
    logger.debug(f"Executing query: {query_preview}")
    
    is_valid, error = validate_query(query)
    if not is_valid:
        logger.warning(f"Query validation failed: {error}")
        return {"error": error}
    
    # Auto-add LIMIT if not present and not forcing full
    if not full_output and limit and 'LIMIT' not in query.upper():
        query = query.rstrip().rstrip(';') + f" LIMIT {min(limit, 1000)}"
    
    # Get user email from parameter or context variable
    effective_email = user_email or get_user_context()
    
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SET statement_timeout = '30s'")
            # Set RLS context for email visibility
            await _set_rls_context(conn, effective_email)
            
            start_time = time.time()
            results = await conn.fetch(query)
            query_time_ms = round((time.time() - start_time) * 1000, 2)
            logger.info(f"Query executed: {len(results)} rows in {query_time_ms}ms")
            
            # Convert to dicts
            rows = []
            for row in results:
                row_dict = {}
                for key, value in dict(row).items():
                    if hasattr(value, 'isoformat'):
                        row_dict[key] = value.isoformat()
                    elif isinstance(value, (bytes, bytearray)):
                        row_dict[key] = f"<{len(value)} bytes>"
                    else:
                        row_dict[key] = value
                rows.append(row_dict)
            
            # Smart truncation
            truncated_rows, trunc_meta = smart_truncate(rows, force_full=full_output)
            
            # Build metadata
            meta = {"query_time_ms": query_time_ms}
            meta.update(trunc_meta)
            
            # Optional statistics
            if include_stats and truncated_rows:
                meta["columns"] = compute_column_stats(truncated_rows)
            
            # Format output
            if format == "toon":
                return {"data": to_toon(truncated_rows), "meta": meta}
            else:
                return {"rows": truncated_rows, "meta": meta}
                
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {"error": enhance_error(str(e))}

