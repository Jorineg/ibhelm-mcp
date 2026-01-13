"""Logging configuration for MCP Server."""
import logging
from logtail import LogtailHandler

import config

# App-specific logger (doesn't interfere with FastMCP)
logger = logging.getLogger("ibhelm.mcp")
logger.setLevel(getattr(logging, config.LOG_LEVEL))

# Add Betterstack handler to root logger (non-destructive)
if config.BETTERSTACK_SOURCE_TOKEN:
    try:
        handler_kwargs = {"source_token": config.BETTERSTACK_SOURCE_TOKEN}
        if config.BETTERSTACK_INGEST_HOST:
            handler_kwargs["host"] = config.BETTERSTACK_INGEST_HOST
        
        betterstack_handler = LogtailHandler(**handler_kwargs)
        betterstack_handler.setLevel(logging.DEBUG)
        betterstack_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        logging.getLogger().addHandler(betterstack_handler)
        
        host_info = config.BETTERSTACK_INGEST_HOST or "default (in.logs.betterstack.com)"
        logger.info(f"Betterstack logging enabled (host: {host_info})")
    except Exception as e:
        logger.warning(f"Failed to initialize Betterstack logging: {e}")

