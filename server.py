"""
IBHelm MCP Server - Read-only database access via OAuth 2.1

Features:
- Compact schema retrieval with foreign key references
- Smart truncation (char-based, not just row-based)
- TOON format by default (token-efficient)
- Query metadata (timing, row counts)
- Helpful error messages

Structure:
- config.py: Configuration and constants
- auth.py: OAuth and JWT verification
- database.py: Connection pool, query execution, formatting
- tools/: Individual tool modules
"""

import os
from fastmcp import FastMCP

from auth import create_auth_provider
from tools import register_all_tools


# =============================================================================
# MCP Server
# =============================================================================
mcp = FastMCP(
    name="IBHelm Database Reader",
    instructions="""Read-only database access for IBHelm (Teamwork tasks, Missive emails, Craft docs, files).

**🚀 Quickstart - mv_unified_items (Master View):**
Search everything in one query! Combines tasks, emails, files, craft docs.
Columns: id, type, name, project, status, creator, assignees, sort_date, search_text, labels, tags
```sql
SELECT type, name, project, creator, sort_date 
FROM mv_unified_items 
WHERE search_text ILIKE '%keyword%' 
ORDER BY sort_date DESC LIMIT 20
```

**Useful Functions:**
- `search_projects_autocomplete('text')` → Find projects by name
- `search_persons_autocomplete('text')` → Find people
- `get_sync_status()` → Check data freshness per source

**Query Tips:**
- Use ILIKE for case-insensitive search (better index usage than LOWER())
- Filter by indexed columns: id, *_id foreign keys, created_at, email
- Use LIMIT to avoid large result sets
- Complex JOINs, CTEs, subqueries, array_agg all work well""",
    auth=create_auth_provider(),
)

# Register all tools
register_all_tools(mcp)


# =============================================================================
# Run Server
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting IBHelm MCP Server on {host}:{port}")
    mcp.run(transport="streamable-http", host=host, port=port)
