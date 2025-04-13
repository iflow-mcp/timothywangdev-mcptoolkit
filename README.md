# FastMCP Multi-Tenancy

A serverless, multi-tenant implementation of MCP servers designed to run on Vercel with fluid compute mode enabled.

## Overview

This library extends the FastMCP server implementation to support:

1. **Serverless execution** on Vercel with fluid compute mode
2. **Multi-tenancy** where multiple users can connect to the same endpoint
3. **State persistence** using Redis for session management
4. **API compatibility** with the standard FastMCP implementation

## Requirements

- Python 3.9+
- Redis instance (for session state persistence)
- Vercel account (for deployment)

## Installation

```bash
pip install mcp-python-sdk
```

## Quick Start

Create a new Vercel serverless function:

```python
# api/index.py
import os
from mcp.server.fastmcp_multi_tenancy.vercel import create_vercel_app

# Get Redis URL from environment variable
redis_url = os.environ.get("REDIS_URL")

# Create the FastAPI app
app = create_vercel_app(
    name="My MCP Server",
    instructions="A multi-tenant MCP server on Vercel",
    redis_url=redis_url,
)

# Add your tools
@app.server.tool()
def hello(name: str) -> str:
    return f"Hello, {name}!"

# Add resources
@app.server.resource("resource://data", mime_type="application/json")
def get_data():
    return '{"message": "This is sample data"}'

# Add prompts
@app.server.prompt("greeting")
def greeting_prompt(name: str) -> str:
    return f"Welcome to our multi-tenant MCP server, {name}!"
```

## Deployment to Vercel

1. Set up your Vercel project
2. Enable fluid compute mode in your Vercel project settings
3. Add the Redis URL as an environment variable (`REDIS_URL`)
4. Deploy your project

```bash
vercel deploy
```

## Architecture

The FastMCP multi-tenancy implementation uses:

1. **Redis storage** for session state persistence
2. **Vercel-compatible SSE** for server-sent events that work in serverless environments
3. **FastAPI** for handling HTTP requests

The key components are:

- `FastMCPMultiTenant` - The main server class
- `VercelSseServerTransport` - SSE implementation for Vercel
- `RedisSessionStorage` - Redis-backed storage for sessions
- `MultiTenantServerSession` - Session implementation with Redis persistence

## API Compatibility

This implementation maintains API compatibility with the standard FastMCP server:

```python
# Standard FastMCP
from mcp.server.fastmcp import FastMCP
server = FastMCP(name="Standard Server")

# Multi-tenant FastMCP
from mcp.server.fastmcp_multi_tenancy import FastMCPMultiTenant
server = FastMCPMultiTenant(name="Multi-tenant Server", redis_url="redis://...")
```

The same tool, resource, and prompt decorators work with both implementations.

## Redis Configuration

The Redis instance is used to store:

- Session state
- Message queues
- Client capabilities

You can use any Redis provider (Redis Cloud, Upstash, etc.) as long as it provides a standard Redis URL.

## Local Development

For local development, run:

```python
import asyncio
from mcp.server.fastmcp_multi_tenancy import FastMCPMultiTenant

server = FastMCPMultiTenant(
    name="Local Development Server",
    redis_url="redis://localhost:6379/0",
)

app = server.create_fastapi_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Limitations

- Long-running operations should be designed to be resumable, as serverless functions have execution time limits
- The fluid compute mode on Vercel helps with maintaining connections but has its own limitations
- Redis storage adds some latency compared to in-memory storage

## License

Same as the MCP Python SDK. 