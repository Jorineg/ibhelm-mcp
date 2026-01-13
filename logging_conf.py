"""Logging configuration for MCP Server."""
import logging

import config

logger = logging.getLogger("ibhelm.mcp")
logger.setLevel(getattr(logging, config.LOG_LEVEL))

_betterstack_initialized = False

def setup_betterstack():
    """Call this AFTER FastMCP is created."""
    global _betterstack_initialized
    if _betterstack_initialized or not config.BETTERSTACK_SOURCE_TOKEN:
        return
    
    from logtail import LogtailHandler
    handler_kwargs = {"source_token": config.BETTERSTACK_SOURCE_TOKEN}
    if config.BETTERSTACK_INGEST_HOST:
        handler_kwargs["host"] = config.BETTERSTACK_INGEST_HOST
    
    handler = LogtailHandler(**handler_kwargs)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    
    for name in ['FastMCP', 'uvicorn', 'uvicorn.error', 'uvicorn.access', 'ibhelm.mcp', 'mcp']:
        logging.getLogger(name).addHandler(handler)
    
    _betterstack_initialized = True
    print("[logging] Betterstack logging enabled")

