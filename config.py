"""
Configuration and constants for IBHelm MCP Server.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Environment Configuration
# =============================================================================
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://api.ibhelm.de")
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET")
DATABASE_URL = os.environ.get("DATABASE_URL")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8080")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")

# Direct bearer tokens for API access (comma-separated, token:client_id format)
# Example: MCP_BEARER_TOKENS=abc123:ai-agent,xyz789:service-bot
MCP_BEARER_TOKENS = os.environ.get("MCP_BEARER_TOKENS", "")

# Logging
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
BETTERSTACK_SOURCE_TOKEN = os.environ.get("BETTERSTACK_SOURCE_TOKEN")
BETTERSTACK_INGEST_HOST = os.environ.get("BETTERSTACK_INGEST_HOST")

# Validate required env vars
if not all([OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, DATABASE_URL]):
    raise ValueError("Missing required environment variables: OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, DATABASE_URL")

# =============================================================================
# Truncation Settings
# =============================================================================
MAX_RESPONSE_CHARS = 8000      # Total char budget for response
MAX_CELL_CHARS = 200           # Max chars per cell before truncation
CELL_PREVIEW_CHARS = 80        # Show this many chars from start/end when truncating cell
MIN_ROWS_FOR_PREVIEW = 3       # Min rows to show even for huge cells

# =============================================================================
# Type Abbreviations for Compact Schema
# =============================================================================
TYPE_ABBREV = {
    'integer': 'int', 'bigint': 'bigint', 'smallint': 'smallint',
    'numeric': 'decimal', 'real': 'float', 'double precision': 'double',
    'boolean': 'bool', 'character varying': 'varchar', 'character': 'char',
    'text': 'text', 'uuid': 'uuid', 'date': 'date',
    'timestamp without time zone': 'ts', 'timestamp with time zone': 'tstz',
    'json': 'json', 'jsonb': 'jsonb', 'bytea': 'bytes',
    'ARRAY': 'array', 'USER-DEFINED': 'enum',
}


def abbrev_type(pg_type: str, udt_name: str = None) -> str:
    """Convert PostgreSQL type to abbreviated form."""
    if pg_type == 'ARRAY' and udt_name:
        base = udt_name.lstrip('_')
        return f"{TYPE_ABBREV.get(base, base)}[]"
    if pg_type == 'USER-DEFINED' and udt_name:
        return udt_name
    return TYPE_ABBREV.get(pg_type, pg_type)

