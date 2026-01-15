"""
Direct SQL query tool with embedded schema.
"""

import logging
import psycopg2
from typing import Literal
from pydantic import Field
from mcp.server.fastmcp import Context

from config import DATABASE_URL, abbrev_type
from database import execute_query, set_user_context

logger = logging.getLogger("ibhelm.mcp.tools")


def _fetch_schema_sync() -> str:
    """Fetch schema using sync psycopg2 (doesn't pollute async pool)."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Get columns
        cur.execute("""
            SELECT t.table_schema, t.table_name, c.column_name, c.data_type, c.udt_name,
                   c.character_maximum_length
            FROM information_schema.tables t
            JOIN information_schema.columns c ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE t.table_schema IN ('public', 'teamwork', 'missive') AND t.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY t.table_schema, t.table_name, c.ordinal_position
        """)
        columns = cur.fetchall()
        
        # Get PKs
        cur.execute("""
            SELECT tc.table_schema, tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema IN ('public', 'teamwork', 'missive')
        """)
        pk_set = {(r[0], r[1], r[2]) for r in cur.fetchall()}
        
        # Get FKs
        cur.execute("""
            SELECT tc.table_schema, tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema IN ('public', 'teamwork', 'missive')
        """)
        fk_map = {(r[0], r[1], r[2]): f"{r[3]}.{r[4]}" for r in cur.fetchall()}
        
        # Composite PKs
        cur.execute("""
            SELECT tc.table_schema, tc.table_name, array_agg(kcu.column_name ORDER BY kcu.ordinal_position)
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema IN ('public', 'teamwork', 'missive')
            GROUP BY tc.table_schema, tc.table_name HAVING COUNT(*) > 1
        """)
        cpk_map = {(r[0], r[1]): r[2] for r in cur.fetchall()}
        
        conn.close()
        
        # Build compact output
        output = []
        current_schema = current_table = None
        table_cols = []
        
        for col in columns:
            s, t, col_name, data_type, udt_name, char_max = col
            
            if s != current_schema:
                if current_table and table_cols:
                    cpk = cpk_map.get((current_schema, current_table))
                    line = f"**{current_table}**: " + ", ".join(table_cols)
                    if cpk:
                        line += f" [pk: {', '.join(cpk)}]"
                    output.append(line)
                if current_schema:
                    output.append("")
                output.append(f"# {s}")
                output.append("")
                current_schema, current_table, table_cols = s, None, []
            
            if t != current_table:
                if current_table and table_cols:
                    cpk = cpk_map.get((current_schema, current_table))
                    line = f"**{current_table}**: " + ", ".join(table_cols)
                    if cpk:
                        line += f" [pk: {', '.join(cpk)}]"
                    output.append(line)
                current_table, table_cols = t, []
            
            col_type = abbrev_type(data_type, udt_name)
            if char_max:
                col_type += f"({char_max})"
            
            col_str = f"{col_name} {col_type}"
            if (s, t, col_name) in pk_set and (s, t) not in cpk_map:
                col_str += " pk"
            fk_ref = fk_map.get((s, t, col_name))
            if fk_ref:
                col_str += f" (→{fk_ref})"
            table_cols.append(col_str)
        
        if current_table and table_cols:
            cpk = cpk_map.get((current_schema, current_table))
            line = f"**{current_table}**: " + ", ".join(table_cols)
            if cpk:
                line += f" [pk: {', '.join(cpk)}]"
            output.append(line)
        
        return "\n".join(output)
    except Exception as e:
        return f"Schema loading failed: {e}"


def register_query_tools(mcp):
    """Register the query_database tool with embedded schema in docstring."""
    
    schema = _fetch_schema_sync()
    
    async def query_database(
        query: str = Field(description="SQL SELECT query. Only SELECT/WITH statements allowed."),
        format: Literal["json", "toon"] = Field(default="toon", description="Output format - 'json' or 'toon' (compact tabular, default)."),
        include_stats: bool = Field(default=False, description="Include column statistics (unique counts, min/max, etc.)"),
        limit: int | None = Field(default=None, description="Override LIMIT in query (max 1000). Applied if query has no LIMIT."),
        full_output: bool = Field(default=False, description="If True, disable truncation (return all rows). Use carefully!"),
        ctx: Context = None
    ) -> dict:
        query_preview = query[:80].replace('\n', ' ') + ('...' if len(query) > 80 else '')
        
        # Extract user email from MCP context for RLS
        user_email = None
        if ctx:
            try:
                # Try to get claims from access token
                if hasattr(ctx, 'access_token') and ctx.access_token:
                    claims = getattr(ctx.access_token, 'claims', {}) or {}
                    user_email = claims.get('email')
                # Or try request_context
                elif hasattr(ctx, 'request_context') and ctx.request_context:
                    access_token = getattr(ctx.request_context, 'access_token', None)
                    if access_token:
                        claims = getattr(access_token, 'claims', {}) or {}
                        user_email = claims.get('email')
            except Exception as e:
                logger.debug(f"Could not extract user email from context: {e}")
        
        if user_email:
            set_user_context(user_email)
            logger.info(f"query_database (user={user_email}): {query_preview}")
        else:
            logger.info(f"query_database (no user context): {query_preview}")
        
        return await execute_query(query, format=format, include_stats=include_stats, 
                                    limit=limit, full_output=full_output)
    
    query_database.__doc__ = f"""Execute a READ-ONLY SQL query against the IBHelm database.
    
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

---
## Full Database Schema

{schema}
        """
    
    mcp.tool()(query_database)

