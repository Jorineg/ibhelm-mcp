"""Logging configuration for MCP Server."""
import logging
import sys
from logtail import LogtailHandler

import config


def setup_logging():
    """Configure logging for the application."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.LOG_LEVEL))
    root_logger.handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, config.LOG_LEVEL))
    console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # Betterstack handler (if configured)
    if config.BETTERSTACK_SOURCE_TOKEN:
        try:
            handler_kwargs = {"source_token": config.BETTERSTACK_SOURCE_TOKEN}
            if config.BETTERSTACK_INGEST_HOST:
                handler_kwargs["host"] = config.BETTERSTACK_INGEST_HOST
            
            betterstack_handler = LogtailHandler(**handler_kwargs)
            betterstack_handler.setLevel(logging.DEBUG)
            betterstack_handler.setFormatter(console_formatter)
            root_logger.addHandler(betterstack_handler)
            
            host_info = config.BETTERSTACK_INGEST_HOST or "default (in.logs.betterstack.com)"
            root_logger.info(f"Betterstack logging enabled (host: {host_info})")
        except Exception as e:
            root_logger.warning(f"Failed to initialize Betterstack logging: {e}")
    else:
        root_logger.info("Betterstack logging not configured (BETTERSTACK_SOURCE_TOKEN not set)")
    
    # Suppress noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    return root_logger


logger = setup_logging()

