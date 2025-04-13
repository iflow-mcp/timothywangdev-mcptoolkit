"""
FastMCP Multi-Tenant - A serverless, multi-tenant implementation of MCP servers.

This module provides a version of FastMCP that's designed to work with Vercel
serverless functions with fluid compute mode enabled.
"""

from __future__ import annotations as _annotations

import inspect
import json
import logging
import re
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
)
from itertools import chain
from typing import Any, Callable, Dict, Generic, List, Literal, Optional, TypeVar
from uuid import UUID

import anyio
import fastapi
import pydantic_core
from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel, Field
from pydantic.networks import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp.types import (
    AnyFunction,
    EmbeddedResource,
    GetPromptResult,
    ImageContent,
    TextContent,
    Prompt as MCPPrompt,
    PromptArgument as MCPPromptArgument,
    Resource as MCPResource,
    ResourceTemplate as MCPResourceTemplate,
    Tool as MCPTool,
    ResourceContents,
)
from mcp.server.lowlevel.server import LifespanResultT, Server as MCPServer, lifespan as default_lifespan
from mcp.shared.context import LifespanContextT, RequestContext
from mcp.server.fastmcp.prompts import Prompt, PromptManager
from mcp.server.fastmcp.resources import FunctionResource, Resource, ResourceManager
from mcp.server.fastmcp.tools import ToolManager
from mcp.server.fastmcp.utilities.logging import configure_logging, get_logger
from mcp.server.fastmcp.utilities.types import Image

from .context import Context
from .exceptions import ConfigurationError, ResourceError
from .redis_storage import RedisSessionStorage
from .session import MultiTenantServerSession
from .vercel_sse import VercelSseServerTransport

logger = get_logger(__name__)


class Settings(BaseSettings, Generic[LifespanResultT]):
    """
    FastMCP multi-tenant server settings.
    
    All settings can be configured via environment variables with the prefix FASTMCP_MT_
    """
    
    model_config = SettingsConfigDict(
        env_prefix="FASTMCP_MT_",
        env_file=".env",
        extra="ignore",
    )
    
    # Server settings
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "ERROR"
    
    # Redis settings
    redis_url: str = "redis://localhost:6379/0"
    
    # HTTP settings (mainly for local development)
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Resource settings
    warn_on_duplicate_resources: bool = True
    
    # Tool settings
    warn_on_duplicate_tools: bool = True
    
    # Prompt settings
    warn_on_duplicate_prompts: bool = True
    
    # Dependencies
    dependencies: List[str] = Field(
        default_factory=list,
        description="List of dependencies to install in the server environment",
    )
    
    # Lifespan
    lifespan: Optional[
        Callable[["FastMCPMultiTenant"], AbstractAsyncContextManager[LifespanResultT]]
    ] = Field(None, description="Lifespan context manager")


def lifespan_wrapper(
    app: FastMCPMultiTenant,
    lifespan: Callable[["FastMCPMultiTenant"], AbstractAsyncContextManager[LifespanResultT]],
) -> Callable[[MCPServer[LifespanResultT]], AbstractAsyncContextManager[object]]:
    """Wrap the lifespan context manager for use with the MCP server."""
    
    @asynccontextmanager
    async def wrap(s: MCPServer[LifespanResultT]) -> AsyncIterator[object]:
        async with lifespan(app) as context:
            yield context
    
    return wrap


class FastMCPMultiTenant:
    """
    FastMCP Multi-Tenant Server
    
    This class provides a serverless-compatible implementation of the FastMCP server
    designed for multi-tenant usage on Vercel with fluid compute mode enabled.
    """
    
    def __init__(
        self, 
        name: str | None = None, 
        instructions: str | None = None, 
        **settings: Any
    ):
        """
        Initialize a new FastMCPMultiTenant server.
        
        Args:
            name: Server name
            instructions: Server instructions
            **settings: Additional settings
        """
        self._settings = Settings(**settings)
        
        # Store server metadata directly
        self._name = name or "FastMCP Multi-Tenant"
        self._instructions = instructions
        self.version = "0.1.0"  # Could be extracted from package
        
        self._tool_manager = ToolManager(
            warn_on_duplicate_tools=self._settings.warn_on_duplicate_tools
        )
        
        self._resource_manager = ResourceManager(
            warn_on_duplicate_resources=self._settings.warn_on_duplicate_resources
        )
        
        self._prompt_manager = PromptManager(
            warn_on_duplicate_prompts=self._settings.warn_on_duplicate_prompts
        )
        
        self.dependencies = self._settings.dependencies
        
        # Storage for session data
        self._storage = RedisSessionStorage(self._settings.redis_url)
        
        # Create SSE transport
        self._sse_transport = VercelSseServerTransport(
            endpoint_base="/messages/",
            redis_url=self._settings.redis_url,
            lifespan=lifespan_wrapper(self, self._settings.lifespan or default_lifespan)
        )
        
        # Configure logging
        configure_logging(self._settings.log_level)
    
    @property
    def name(self) -> str:
        """Get the server name."""
        return self._name
    
    @property
    def instructions(self) -> str | None:
        """Get the server instructions."""
        return self._instructions
    
    async def list_tools(self) -> List[MCPTool]:
        """
        List all available tools.
        
        Returns:
            List of tools
        """
        tools = self._tool_manager.list_tools()
        return [
            MCPTool(
                name=info.name,
                description=info.description,
                inputSchema=info.parameters,
            )
            for info in tools
        ]
    
    async def call_tool(
        self, name: str, arguments: Dict[str, Any], context: Context
    ) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        """
        Call a tool by name with arguments.
        
        Args:
            name: Tool name
            arguments: Tool arguments
            context: Optional context object (injected by request handler)
            
        Returns:
            Tool result
        """
        logger.debug(f"server.call_tool {name} with arguments {arguments} and context={context}")
        result = await self._tool_manager.call_tool(name, arguments, context=context)
        return _convert_to_content(result)
    
    async def list_resources(self) -> List[MCPResource]:
        """
        List all available resources.
        
        Returns:
            List of resources
        """
        resources = self._resource_manager.list_resources()
        return [
            MCPResource(
                uri=resource.uri,
                name=resource.name or "",
                description=resource.description,
                mimeType=resource.mime_type,
            )
            for resource in resources
        ]
    
    async def list_resource_templates(self) -> List[MCPResourceTemplate]:
        """
        List all available resource templates.
        
        Returns:
            List of resource templates
        """
        templates = self._resource_manager.list_templates()
        return [
            MCPResourceTemplate(
                uriTemplate=template.uri_template,
                name=template.name,
                description=template.description,
            )
            for template in templates
        ]
    
    async def read_resource(self, uri: AnyUrl | str) -> Iterable[ResourceContents]:
        """
        Read a resource by URI.
        
        Args:
            uri: Resource URI
            
        Returns:
            Resource contents
        """
        resource = await self._resource_manager.get_resource(uri)
        if not resource:
            raise ResourceError(f"Unknown resource: {uri}")
        
        try:
            content = await resource.read()
            return [ResourceContents(content=content, mime_type=resource.mime_type)]
        except Exception as e:
            logger.error(f"Error reading resource {uri}: {e}")
            raise ResourceError(str(e))
    
    def add_tool(
        self,
        fn: AnyFunction,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """
        Add a tool to the server.
        
        Args:
            fn: Tool function
            name: Tool name (defaults to function name)
            description: Tool description (defaults to function docstring)
        """
        self._tool_manager.add_tool(fn, name, description)
    
    def tool(
        self, name: str | None = None, description: str | None = None
    ) -> Callable[[AnyFunction], AnyFunction]:
        """
        Decorator to add a tool to the server.
        
        Example:
        ```python
        @server.tool()
        def my_tool(x: int, ctx: Context) -> str:
            # Use context for logging, etc.
            ctx.info(f"Processing {x}")
            # Access entity ID
            entity_id = ctx.entity_id
            return str(x)
        ```
        
        Args:
            name: Tool name (defaults to function name)
            description: Tool description (defaults to function docstring)
            
        Returns:
            Decorator function
        """
        
        def decorator(fn: AnyFunction) -> AnyFunction:
            self.add_tool(fn, name, description)
            return fn
        
        return decorator
    
    def add_resource(self, resource: Resource) -> None:
        """
        Add a resource to the server.
        
        Args:
            resource: Resource object
        """
        self._resource_manager.add_resource(resource)
    
    def resource(
        self,
        uri: str,
        name: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
    ) -> Callable[[AnyFunction], AnyFunction]:
        """
        Decorator to add a resource to the server.
        
        Example:
        ```python
        @server.resource("resource://data", mime_type="application/json")
        def get_data(ctx: Context) -> str:
            # Access entity ID to customize response
            entity_id = ctx.entity_id
            return json.dumps({"entity": entity_id, "data": "value"})
        ```
        
        Args:
            uri: Resource URI
            name: Resource name
            description: Resource description
            mime_type: Resource MIME type
            
        Returns:
            Decorator function
        """
        
        def decorator(fn: AnyFunction) -> AnyFunction:
            resource = FunctionResource(
                uri=uri,
                fn=fn,
                name=name,
                description=description,
                mime_type=mime_type,
            )
            self.add_resource(resource)
            return fn
        
        return decorator
    
    def add_prompt(self, prompt: Prompt) -> None:
        """
        Add a prompt to the server.
        
        Args:
            prompt: Prompt object
        """
        self._prompt_manager.add_prompt(prompt)
    
    def prompt(
        self, name: str | None = None, description: str | None = None
    ) -> Callable[[AnyFunction], AnyFunction]:
        """
        Decorator to add a prompt to the server.
        
        Example:
        ```python
        @server.prompt("greeting")
        def greeting_prompt(name: str, ctx: Context) -> str:
            # Customize greeting based on entity
            entity_id = ctx.entity_id
            return f"Hello, {name}! Welcome to {entity_id}!"
        ```
        
        Args:
            name: Prompt name
            description: Prompt description
            
        Returns:
            Decorator function
        """
        
        def decorator(fn: AnyFunction) -> AnyFunction:
            prompt = Prompt.from_function(
                fn,
                name=name,
                description=description,
            )
            self.add_prompt(prompt)
            return fn
        
        return decorator
    
    async def list_prompts(self) -> list[MCPPrompt]:
        """List all available prompts."""
        prompts = self._prompt_manager.list_prompts()
        return [
            MCPPrompt(
                name=prompt.name,
                description=prompt.description,
                arguments=[
                    MCPPromptArgument(
                        name=arg.name,
                        description=arg.description,
                        required=arg.required,
                    )
                    for arg in (prompt.arguments or [])
                ],
            )
            for prompt in prompts
        ]
    
    async def get_prompt(
        self, name: str, arguments: Dict[str, Any] | None = None, context: Optional[Context] = None
    ) -> GetPromptResult:
        """Get a prompt by name with arguments."""
        try:
            messages = await self._prompt_manager.render_prompt(name, arguments)

            return GetPromptResult(messages=pydantic_core.to_jsonable_python(messages))
        except Exception as e:
            logger.error(f"Error getting prompt {name}: {e}")
            raise ValueError(str(e))
    
    def get_context(self, request_context: Optional[RequestContext] = None, entity_id: Optional[str] = None) -> Context:
        """
        Get a context object for the current request.
        
        Args:
            request_context: Optional request context
            entity_id: Optional entity ID for multi-tenancy
            
        Returns:
            A Context object
        """
        context = Context(request_context=request_context, fastmcp=self, entity_id=entity_id)
        return context
    
    def create_fastapi_app(self) -> FastAPI:
        """Create a FastAPI app for this server."""
        app = FastAPI(
            title=self.name,
            description=self.instructions or "",
            debug=self._settings.debug,
        )

        # Create a router for our endpoints
        router = APIRouter()

        # Add the router to the app with a prefix for entity IDs
        app.include_router(router, prefix="/{entity_id}")

        # Set up SSE transport
        @app.on_event("startup")
        async def setup_sse():
            await self._sse_transport.setup_fastapi(app)

        # Add health check endpoint
        @router.get("/health")
        async def health_check(entity_id: str):
            return {"status": "ok", "server": self.name, "entity_id": entity_id}

        # Add startup and shutdown handlers
        @app.on_event("startup")
        async def startup():
            """Startup event handler."""
            logger.info(f"Starting {self.name} server")

        @app.on_event("shutdown")
        async def shutdown():
            """Shutdown event handler."""
            logger.info(f"Shutting down {self.name} server")
            if hasattr(self, "_sse_transport"):
                await self._sse_transport.close()
            if hasattr(self, "_storage"):
                await self._storage.close()

        return app

    def get_handler_map(self) -> Dict[str, Callable]:
        """
        Get a map of handler methods that can be registered with an MCP server.
        
        Returns:
            Dictionary mapping handler names to handler methods
        """
        return {
            "list_tools": self.list_tools,
            "call_tool": self.call_tool,
            "list_resources": self.list_resources,
            "read_resource": self.read_resource,
            "list_prompts": self.list_prompts,
            "get_prompt": self.get_prompt,
            "list_resource_templates": self.list_resource_templates,
        }


def _convert_to_content(
    result: Any,
) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Convert a result to a sequence of content objects."""
    if result is None:
        return []

    if isinstance(result, (TextContent, ImageContent, EmbeddedResource)):
        return [result]

    if isinstance(result, Image):
        return [result.to_image_content()]

    if isinstance(result, (list, tuple)):
        return list(chain.from_iterable(_convert_to_content(item) for item in result))

    if not isinstance(result, str):
        try:
            result = json.dumps(pydantic_core.to_jsonable_python(result))
        except Exception:
            result = str(result)

    return [TextContent(type="text", text=result)]