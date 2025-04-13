# FastMCP Multi-Tenancy: Technical Design Document

## Introduction

### Purpose
This document outlines the technical design for FastMCP Multi-Tenancy, a specialized implementation of the MCP (Machine Conversation Protocol) server that supports running in serverless environments like Vercel with multiple tenant sessions.

### Scope
This design covers the server-side implementation for FastMCP Multi-Tenancy, focusing on:
- Redis-backed storage for session persistence
- Vercel-compatible SSE transport implementation
- Multi-tenant session management
- Entity ID support for tenant/organization identification
- FastAPI integration

### Background
The original FastMCP implementation was designed for long-running server processes, which doesn't align well with serverless function constraints. This implementation addresses those limitations by making the server stateless across invocations, storing session data in Redis, and supporting multiple tenants per deployment.

## Architecture Overview

### High-Level Architecture
FastMCP Multi-Tenancy follows a layered architecture:

1. **Web Layer**: FastAPI HTTP endpoints
2. **Transport Layer**: Vercel-compatible SSE implementation
3. **Session Layer**: Multi-tenant session management with Redis storage
4. **MCP Protocol Layer**: Standard MCP protocol implementation

### Key Components
- `FastMCPMultiTenant`: Main server class
- `RedisSessionStorage`: Persistence layer for session data
- `VercelSseServerTransport`: Serverless-friendly SSE implementation
- `MultiTenantServerSession`: Session manager for multiple concurrent tenants
- `Context`: Developer-friendly access to MCP capabilities

### Entity ID Integration
Entity IDs are integrated throughout the system to identify different tenants using URL path segments. The entity ID flows:
1. Extracted from URL path (`/{entity_id}/sse` or `/{entity_id}/messages`)
2. Stored in session state
3. Made available via the Context object to developers

### Interaction Flow
1. Client connects to `/{entity_id}/sse` endpoint
2. Server creates a session with entity ID and sends SSE endpoint URL
3. Client sends messages to `/{entity_id}/messages?session_id={id}`
4. Server processes messages and sends responses via SSE
5. Sessions persist via Redis between function invocations

## Project Structure

The project is organized as follows:

```
src/mcp/server/fastmcp-multi-tenancy/
├── README.md                   # Project documentation
├── tdd.md                      # Technical design document
├── example.py                  # Example server for local development
├── server.py                   # Main server implementation (FastMCPMultiTenant)
├── session.py                  # Multi-tenant session management
├── redis_storage.py            # Redis-backed state persistence
├── vercel_sse.py               # Vercel-compatible SSE transport
├── vercel.py                   # Vercel deployment helper
├── exceptions.py               # Custom exceptions
└── vercel_example/             # Vercel deployment example
    ├── index.py                # Serverless function entry point
    ├── requirements.txt        # Python dependencies
    └── vercel.json             # Vercel configuration
```

### Key Files and Their Purposes

- **server.py**: Core implementation of the `FastMCPMultiTenant` class. Provides the main API for registering tools, resources, and prompts. Handles integration with FastAPI.

- **session.py**: Implements the `MultiTenantServerSession` class for Redis-backed session management. Handles session state persistence across function invocations.

- **redis_storage.py**: Provides the storage layer for session persistence using Redis. Manages message queues and session data.

- **vercel_sse.py**: Implements the Server-Sent Events transport optimized for Vercel's serverless functions. Handles SSE connections and message routing with entity ID support.

- **vercel.py**: Contains the helper function `create_vercel_app()` for simplifying Vercel deployment.

- **example.py**: Complete example server implementation with sample tools, resources, and prompts. Can be run directly for local development.

- **vercel_example/**: Directory containing a full example for deploying on Vercel with fluid compute enabled:
  - **index.py**: Entry point for the Vercel serverless function
  - **requirements.txt**: Dependencies required for deployment
  - **vercel.json**: Configuration for Vercel with fluid compute settings

## Detailed Component Design

### FastMCPMultiTenant
The main server class that orchestrates all components.

**Purpose:**
- Provides the main API for developers
- Manages tools, resources, and prompts
- Creates FastAPI application

**Design:**
- Extends the original FastMCP design but with multi-tenancy support
- Uses dependency injection for Redis and SSE transport
- Provides decorators for registering tools, resources, and prompts

**Key Methods:**
- `create_fastapi_app()`: Creates a FastAPI application with routes
- `tool()`, `resource()`, `prompt()`: Decorators for registration

### RedisSessionStorage
Storage layer for session persistence between function invocations.

**Purpose:**
- Stores session state in Redis
- Manages message queues for SSE

**Design:**
- Key-based storage with session IDs
- TTL for automatic cleanup of inactive sessions
- Atomic operations for reliability

**Key Methods:**
- `store_session()`: Saves session data
- `get_session()`: Retrieves session data
- `add_to_queue()`: Adds message to session queue
- `wait_for_message()`: Awaits messages with timeout

### VercelSseServerTransport
Transport layer that supports Server-Sent Events with Vercel compatibility.

**Purpose:**
- Handles SSE connections with clients
- Processes message POSTs
- Supports entity IDs in URL paths

**Design:**
- Maintains persistent connections using SSE
- Uses Redis for message queuing
- Handles reconnections gracefully
- URL paths include entity IDs: `/{entity_id}/sse` and `/{entity_id}/messages`

**Key Methods:**
- `connect_sse()`: Establishes SSE connection with entity ID
- `handle_post_message()`: Processes messages with entity ID verification
- `setup_fastapi()`: Sets up FastAPI routes with entity ID path parameters

### MultiTenantServerSession
Session manager for multiple concurrent users.

**Purpose:**
- Implements the MCP protocol
- Manages session state across invocations
- Stores entity ID with session data

**Design:**
- Redis-backed state management
- Entity ID preservation between requests
- Support for standard MCP operations

**Key Methods:**
- `_load_state()`: Loads session data from Redis
- `_save_state()`: Persists session data to Redis
- `send_log_message()`, `send_progress_notification()`: Client notifications

### Context
Developer-friendly access to MCP capabilities.

**Purpose:**
- Provides clean interface for tools/resources
- Abstracts MCP protocol details
- Exposes entity ID to developers

**Design:**
- Injected into tool and resource functions
- Contains session and request context
- Provides entity ID access

**Key Methods:**
- `entity_id`: Property to access current entity ID
- `report_progress()`: Reports progress to client
- `read_resource()`: Reads resource by URI
- `log()`, `debug()`, `info()`, etc.: Logging methods

## API Design

### Compatibility Layer
The implementation maintains compatibility with the original FastMCP API while adding multi-tenancy support.

### Server API
Developers interact with the API primarily through decorators:

```python
@server.tool(name="example", description="Example tool")
def example_tool(param: str, ctx: Context) -> str:
    # Access entity ID
    entity_id = ctx.entity_id
    ctx.info(f"Processing for entity: {entity_id}")
    return f"Result for {entity_id}: {param}"
```

### Entity ID Support
Entity IDs are available through the Context object:

```python
@server.tool()
def entity_aware_tool(ctx: Context) -> dict:
    # Get entity ID from context
    entity_id = ctx.entity_id
    return {
        "entity_id": entity_id,
        "timestamp": datetime.now().isoformat()
    }
```

### Context Object
The Context object provides access to:
- Entity ID (`ctx.entity_id`)
- Logging (`ctx.info()`, `ctx.debug()`, etc.)
- Progress reporting (`ctx.report_progress()`)
- Resource access (`ctx.read_resource()`)
- Session information (`ctx.session`, `ctx.client_id`, etc.)

## Serverless Implementation

### Vercel Integration
The implementation is designed for Vercel serverless functions with fluid compute mode.

```python
# api/index.py
from mcp.server.fastmcp_multi_tenancy.vercel import create_vercel_app
import os

app = create_vercel_app(
    name="Multi-Tenant Server",
    redis_url=os.environ.get("REDIS_URL"),
    debug=False
)

@app.server.tool()
def hello(name: str, ctx: Context) -> str:
    entity_id = ctx.entity_id
    return f"Hello {name} from {entity_id}!"
```

### Fluid Compute Mode
Vercel's fluid compute is required for SSE connections:
- Keeps functions alive for up to 15 minutes
- Enables persistent SSE connections
- Requires specific Vercel configuration

### Deployment Helper
The `create_vercel_app()` function helps with deployment:
- Creates FastAPI app with pre-configured routes
- Sets up SSE endpoints with entity ID support
- Attaches the server to the app for easy access

## Data Flow

### Session Initialization
1. Client connects to `/{entity_id}/sse`
2. Server creates a session ID and stores entity ID
3. Server sends endpoint URL with session ID via SSE
4. Client initializes MCP protocol
5. Session state is persisted to Redis

### Message Handling
1. Client sends message to `/{entity_id}/messages?session_id={id}`
2. Server verifies entity ID matches session's entity ID
3. Server loads session state from Redis
4. Server processes the message
5. Server sends response via SSE
6. Server persists updated state to Redis

### State Persistence
1. Session state is stored in Redis with session ID as key
2. State includes entity ID, client parameters, and initialization state
3. Each function invocation loads/saves state as needed
4. TTL ensures cleanup of inactive sessions

## Performance Considerations

### Latency
- Redis operations add some latency compared to in-memory
- Designed to minimize Redis operations
- Uses efficient encoding for state storage

### Scalability
- Each tenant gets their own session
- Redis connection pooling for efficient handling
- Naturally scales with Vercel's infrastructure

### Resource Usage
- Minimal memory footprint per function instance
- Redis connection sharing across sessions
- Efficient message passing using SSE

## Security Considerations

### Session Isolation
- Each session has unique ID
- Entity ID verification prevents cross-tenant access
- Session data is isolated in Redis

### Authentication
- Entity IDs can be used with authentication middleware
- Developers can implement custom auth in routes
- Session IDs are generated as UUIDs for security

## Deployment Process

### Requirements
- Redis instance (Cloud Redis recommended)
- Vercel account with fluid compute enabled
- Python 3.8+ serverless function support

### Deployment Steps
1. Create Vercel project
2. Set up Redis instance
3. Configure environment variables
4. Create API files following the example
5. Deploy to Vercel

### Environment Variables
- `REDIS_URL`: Connection string for Redis
- `FASTMCP_MT_DEBUG`: Enable debug mode (optional)
- `FASTMCP_MT_LOG_LEVEL`: Set logging level (optional)

## Limitations and Considerations

### Function Duration
- Limited to Vercel's maximum function duration (15 minutes with fluid compute)
- Long-running operations should be avoided

### Connection Stability
- SSE connections may require reconnects
- Clients should implement reconnection logic

### Redis Dependency
- Redis is required for operation
- Redis outages will affect all sessions
- Recommended to use managed Redis service

## Future Enhancements

### Enhanced Monitoring
- More detailed session metrics
- Performance tracking across tenants
- Entity ID-based analytics

### Entity ID Integration
- Enhanced entity-based routing capabilities
- Entity-specific throttling or rate limiting
- Optional entity configuration options

### Authentication Extensions
- Built-in auth middleware for entity IDs
- Integration with common auth providers
- Permission scoping by entity ID

## Conclusion
FastMCP Multi-Tenancy successfully adapts the MCP server architecture for serverless environments with multi-tenant support. The implementation addresses key challenges of serverless deployment while maintaining compatibility with the original MCP protocol. The addition of entity ID support provides clear tenant separation within a single deployment.

## Appendix A: Key Dependencies

- `fastapi`: Web framework
- `redis`: Redis client
- `anyio`: Asynchronous I/O
- `pydantic`: Data validation
- `uvicorn`: ASGI server (local development) 