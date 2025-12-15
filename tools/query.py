"""
Direct SQL query tool with dynamic docstring injection.
"""

from typing import Literal
from pydantic import Field

from database import execute_query

# Base docstring template - {schema} will be injected at registration time
QUERY_DOCSTRING_TEMPLATE = """Execute a READ-ONLY SQL query against the IBHelm database.
    
    Returns:
        - rows/data: Query results (format depends on 'format' param)
        - meta: Execution metadata (time, row count, truncation info)
        - error: Error message if query failed (with helpful hints)
    
**Query Tips:**
- Use ILIKE for case-insensitive search (better index usage)
- Filter by indexed columns: id, *_id foreign keys, created_at, email
- Use LIMIT to avoid large result sets
- For text search, prefer: column ILIKE '%term%' over LOWER(column) LIKE '%term%'
- Complex JOINs (5+ tables), CTEs, subqueries, array_agg all work well

**Views & Functions (query like tables):**
- `mv_unified_items`: Master view - tasks/emails/files/craft unified (59k+ rows)
  Columns: id, type, name, project, status, creator, sort_date, search_text, etc.
- `project_overview`: Projects with counts
- `search_projects_autocomplete('text')`: Find projects by name
- `search_persons_autocomplete('text')`: Find people
- `get_sync_status()`: Check data freshness
    
    **Example Queries:**
    ```sql
    -- Search EVERYTHING for "Jörg"
    SELECT type, name, project, creator, sort_date 
    FROM mv_unified_items 
    WHERE search_text ILIKE '%Jörg%'
    ORDER BY sort_date DESC LIMIT 20
    
    -- Emails with attachments > 10MB
    SELECT m.subject, a.filename, a.size 
    FROM missive.messages m
    JOIN missive.attachments a ON m.id = a.message_id
    WHERE a.size > 10000000
    ORDER BY a.size DESC LIMIT 20
    ```
        """


def register_query_tools(mcp, schema_text: str | None = None):
    """Register the query_database tool with optional dynamic docstring injection."""
    
    async def query_database(
        query: str = Field(description="SQL SELECT query. Only SELECT/WITH statements allowed."),
        format: Literal["json", "toon"] = Field(default="toon", description="Output format - 'json' or 'toon' (compact tabular, default)."),
        include_stats: bool = Field(default=False, description="Include column statistics (unique counts, min/max, etc.)"),
        limit: int | None = Field(default=None, description="Override LIMIT in query (max 1000). Applied if query has no LIMIT."),
        full_output: bool = Field(default=False, description="If True, disable truncation (return all rows). Use carefully!")
    ) -> dict:
        return await execute_query(query, format=format, include_stats=include_stats, 
                                    limit=limit, full_output=full_output)
    
    # Inject dynamic content into docstring before registration
    query_database.__doc__ = QUERY_DOCSTRING_TEMPLATE
    
    # Register the tool with modified docstring
    mcp.tool()(query_database)

