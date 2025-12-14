"""
MCP Tools for IBHelm Database Reader.
"""

from tools.schema import register_schema_tools
from tools.query import register_query_tools
from tools.search import register_search_tools
from tools.project import register_project_tools
from tools.python_exec import register_python_tools


def register_all_tools(mcp):
    """Register all tools with the MCP server."""
    register_schema_tools(mcp)
    register_query_tools(mcp)
    register_search_tools(mcp)
    register_project_tools(mcp)
    register_python_tools(mcp)

