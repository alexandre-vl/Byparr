from __future__ import annotations

import logging
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from src.consts import LOG_LEVEL, VERSION
from src.endpoints import router
from src.middlewares import LogRequest
from src.utils import logger

# Configure root logger to ensure all debug logs are shown
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(levelname)s - %(name)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True
)

# Make sure all loggers show debug messages
for log_name in ['uvicorn', 'uvicorn.error', 'uvicorn.access', 'fastapi']:
    logging.getLogger(log_name).setLevel(LOG_LEVEL)
    # Prevent duplicate log messages
    logging.getLogger(log_name).propagate = False

logger.propagate = False
logger.info("Using version %s", VERSION)

app = FastAPI(debug=LOG_LEVEL == logging.DEBUG, log_level=LOG_LEVEL)
app.add_middleware(GZipMiddleware)
app.add_middleware(LogRequest)

app.include_router(router=router)


if __name__ == "__main__":
    # Configure Uvicorn with explicit log configuration
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8191, 
        log_level=logging.getLevelName(LOG_LEVEL).lower(),
        log_config=None  # Disable Uvicorn's default logging config
    )  # noqa: S104
