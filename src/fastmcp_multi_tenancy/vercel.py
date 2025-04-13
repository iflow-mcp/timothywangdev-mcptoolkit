"""
Vercel deployment helper for FastMCP multi-tenant servers.
"""

import logging
import os
from typing import Any, Optional

import fastapi
from fastapi import FastAPI, APIRouter

from .server import FastMCPMultiTenant

logger = logging.getLogger(__name__)

def create_vercel_app(
    name: str,
    instructions: Optional[str] = None,
    redis_url: Optional[str] = None,
    debug: bool = False,
    **settings: Any,
) -> FastAPI:
    """
    Create a FastAPI app for Vercel deployment.
    
    Args:
        name: Server name
        instructions: Server instructions
        redis_url: Redis URL (defaults to REDIS_URL environment variable)
        debug: Enable debug mode
        **settings: Additional settings to pass to FastMCPMultiTenant
        
    Returns:
        FastAPI app ready for Vercel deployment
    """
    # Configure logging based on debug setting
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Get Redis URL from environment if not provided
    if redis_url is None:
        redis_url = os.environ.get("REDIS_URL")
        if redis_url is None:
            raise ValueError("Redis URL must be provided or set in REDIS_URL environment variable")
    
    # Create the server
    server = FastMCPMultiTenant(
        name=name,
        instructions=instructions,
        redis_url=redis_url,
        debug=debug,
        log_level="DEBUG" if debug else "INFO",  # Pass log level to server
        **settings,
    )
    
    # Create FastAPI app
    app = FastAPI(
        title=name,
        description=instructions or "",
        debug=debug,
    )
    
    # Attach server instance to app for easy access
    app.state.server = server
    
    # Create a router for our endpoints
    router = APIRouter()
    
    # Add the router to the app with a prefix for entity IDs
    app.include_router(router, prefix="/{entity_id}")
    
    # Set up SSE transport
    @app.on_event("startup")
    async def setup_sse():
        await server._sse_transport.setup_fastapi(app)
    
    # Add health check endpoint
    @router.get("/health")
    async def health_check(entity_id: str):
        return {"status": "ok", "server": name, "entity_id": entity_id}
    
    # Add startup and shutdown handlers
    @app.on_event("startup")
    async def startup():
        """Startup event handler."""
        logger.info(f"Starting {name} server")
        if debug:
            logger.debug("Debug mode enabled - verbose logging is active")
    
    @app.on_event("shutdown")
    async def shutdown():
        """Shutdown event handler."""
        logger.info(f"Shutting down {name} server")
        if hasattr(server, "_sse_transport"):
            await server._sse_transport.close()
        if hasattr(server, "_storage"):
            await server._storage.close()
    
    return app 