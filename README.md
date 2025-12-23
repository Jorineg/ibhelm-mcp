# IBHelm MCP Server

A specialized [Model Context Protocol](https://modelcontextprotocol.io/) server that provides AI models (like Claude in Cursor or Claude Desktop) with secure, read-only access to the IBHelm database.

## 🤖 Purpose

The MCP server acts as the "eyes and ears" for AI assistants, allowing them to:
- **Search Project Data**: Find specific emails, tasks, or files across the entire ecosystem.
- **Analyze Progress**: Generate project summaries, activity dashboards, and status reports.
- **Verify Schema**: Understand the underlying data structure for complex SQL querying.
- **Answer Questions**: Provide factual answers based on company data instead of halluncinating.

## 🛠 Available Tools

| Tool | Capability |
|------|------------|
| `query_database` | Execute read-only SQL queries (SELECT only). |
| `get_schema` | View tables, types, and relationships. |
| `describe_table` | Inspect specific table structures with sample rows. |
| `search_emails` | Unified search across Missive conversations and messages. |
| `search_tasks` | Unified search across Teamwork tasks and tags. |
| `get_project_summary` | Get a high-level overview of project health and statistics. |
| `get_project_dashboard` | A comprehensive view of recent project developments. |
| `run_python` | execute sandboxed python code for complex data analysis. |

## 🚀 Setup

### Environment Variables

Create a `.env` file with the following:

```env
DATABASE_URL=postgresql://readonly_user:pass@host:5432/database
SUPABASE_URL=https://api.ibhelm.de
OAUTH_CLIENT_ID=...
OAUTH_CLIENT_SECRET=...
```

### Docker Deployment

```bash
docker compose up -d
```

## 🔌 Connection

Add the following to your MCP client configuration (e.g., `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ibhelm": {
      "command": "docker",
      "args": ["exec", "-i", "ibhelm-mcp", "python", "server.py"]
    }
  }
}
```

## 🔒 Security

- **Read-Only**: The database user is restricted to `SELECT` operations only.
- **Isolation**: Tools are designed to prevent data leakage and maintain privacy.
- **Truncation**: Responses are automatically truncated to fit within LLM context windows using smart TOON (Token-Oriented Object Notation) formatting.
