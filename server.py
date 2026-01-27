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

from auth import create_auth_provider, DCRScopeMiddleware
from tools import register_all_tools

# =============================================================================
# MCP Server (create BEFORE logging setup)
# =============================================================================
mcp = FastMCP(
    name="IBHelm Database Reader",
    instructions="""Read-only database access for IBHelm (Teamwork tasks, Missive emails, Craft docs, files).

Use the query_database tool to execute SQL queries - it includes the full database schema in its description.""",
    auth=create_auth_provider(),
)

register_all_tools(mcp)

# NOW setup logging (after MCP creation)
from logging_conf import setup_betterstack, logger
setup_betterstack()

# =============================================================================
# ASGI App with DCR scope middleware
# =============================================================================
# Wrap with middleware to auto-assign default scopes during DCR (fixes Cursor MCP client)
app = DCRScopeMiddleware(mcp.http_app())

# =============================================================================
# Run Server
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting IBHelm MCP Server on {host}:{port}")
    # Use uvicorn directly for the app with middleware
    import uvicorn
    uvicorn.run(app, host=host, port=port)
