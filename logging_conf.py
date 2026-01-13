"""Logging configuration for MCP Server."""
import logging
from logtail import LogtailHandler

import config

# App-specific logger
logger = logging.getLogger("ibhelm.mcp")
logger.setLevel(getattr(logging, config.LOG_LEVEL))

# Add Betterstack handler to SPECIFIC loggers (not root - breaks uvicorn)
if config.BETTERSTACK_SOURCE_TOKEN:
    try:
        handler_kwargs = {"source_token": config.BETTERSTACK_SOURCE_TOKEN}
        if config.BETTERSTACK_INGEST_HOST:
            handler_kwargs["host"] = config.BETTERSTACK_INGEST_HOST
        
        betterstack_handler = LogtailHandler(**handler_kwargs)
        betterstack_handler.setLevel(logging.DEBUG)
        betterstack_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        
        # Add to specific loggers instead of root
        for logger_name in ['FastMCP', 'uvicorn', 'uvicorn.error', 'uvicorn.access', 'ibhelm.mcp', 'mcp']:
            logging.getLogger(logger_name).addHandler(betterstack_handler)
        
        host_info = config.BETTERSTACK_INGEST_HOST or "default"
        logger.info(f"Betterstack logging enabled (host: {host_info})")
    except Exception as e:
        logger.warning(f"Failed to initialize Betterstack logging: {e}")

