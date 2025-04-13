"""
Example FastMCP Multi-Tenant Server

This example demonstrates how to create and run a multi-tenant MCP server
using the FastMCPMultiTenant implementation.

For local development:
    python -m src.mcp.server.fastmcp-multi-tenancy.example

For Vercel deployment:
    Create an api/index.py file based on the create_vercel_app example.
"""

import json
import os
from typing import Dict, List

from .server import FastMCPMultiTenant, Context


def create_example_server():
    """Create and configure an example server."""
    # Use local Redis or environment variable
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    
    # Create server
    server = FastMCPMultiTenant(
        name="Example Multi-Tenant Server",
        instructions="This is an example server demonstrating multi-tenancy with entity IDs",
        redis_url=redis_url,
        debug=True,
        log_level="INFO",
    )
    
    # Add tools
    @server.tool(
        name="hello",
        description="Say hello to someone"
    )
    def hello(name: str, ctx: Context) -> str:
        """Say hello to someone."""
        # Get entity ID from context
        entity_id = ctx.entity_id
        ctx.info(f"Saying hello to {name} from entity {entity_id}")
        return f"Hello, {name} from {entity_id or 'unknown entity'}!"
    
    @server.tool(
        name="entity_info",
        description="Get information about the current entity"
    )
    def entity_info(ctx: Context) -> Dict:
        """Get information about the current entity."""
        entity_id = ctx.entity_id
        ctx.info(f"Getting info for entity {entity_id}")
        
        # This could be a database lookup in a real application
        return {
            "entity_id": entity_id,
            "client_id": ctx.client_id,
            "request_id": ctx.request_id,
            "session_active": True
        }
    
    @server.tool(
        name="calculate",
        description="Perform a calculation"
    )
    def calculate(a: float, b: float, operation: str, ctx: Context) -> Dict:
        """Perform a calculation using the specified operation."""
        entity_id = ctx.entity_id
        ctx.info(f"Calculating {a} {operation} {b} for entity {entity_id}")
        
        result = None
        if operation == "add":
            result = a + b
        elif operation == "subtract":
            result = a - b
        elif operation == "multiply":
            result = a * b
        elif operation == "divide":
            if b == 0:
                ctx.error("Cannot divide by zero")
                raise ValueError("Cannot divide by zero")
            result = a / b
        else:
            ctx.error(f"Unknown operation: {operation}")
            raise ValueError(f"Unknown operation: {operation}")
        
        # Report progress as we go
        ctx.report_progress(50, 100)
        
        # Final result
        ctx.report_progress(100, 100)
        return {
            "entity_id": entity_id,
            "operation": operation,
            "a": a,
            "b": b,
            "result": result
        }
    
    # Add resources
    @server.resource(
        uri="resource://data",
        name="Entity Data",
        description="Data specific to the entity",
        mime_type="application/json"
    )
    def get_data(ctx: Context) -> str:
        """Get entity-specific data."""
        entity_id = ctx.entity_id
        ctx.info(f"Fetching data for entity {entity_id}")
        return json.dumps({
            "entity_id": entity_id,
            "items": [
                {"id": 1, "name": f"{entity_id} Item 1"},
                {"id": 2, "name": f"{entity_id} Item 2"},
                {"id": 3, "name": f"{entity_id} Item 3"}
            ]
        })
    
    # Add parametrized resource
    @server.resource(
        uri="resource://data/{id}",
        name="Item Data",
        description="Get data for a specific item in the entity",
        mime_type="application/json"
    )
    def get_item(id: str, ctx: Context) -> str:
        """Get data for a specific item."""
        entity_id = ctx.entity_id
        ctx.info(f"Fetching data for item {id} in entity {entity_id}")
        
        # Simulate item lookup
        items = {
            "1": {"id": 1, "name": f"{entity_id} Item 1", "description": "First item"},
            "2": {"id": 2, "name": f"{entity_id} Item 2", "description": "Second item"},
            "3": {"id": 3, "name": f"{entity_id} Item 3", "description": "Third item"}
        }
        
        if id not in items:
            ctx.error(f"Item {id} not found in entity {entity_id}")
            return json.dumps({"error": "Item not found", "entity_id": entity_id})
        
        return json.dumps(items[id])
    
    # Add prompts
    @server.prompt(
        name="greeting",
        description="Generate a greeting message for the entity"
    )
    def greeting_prompt(name: str, ctx: Context) -> str:
        """Generate a greeting message."""
        entity_id = ctx.entity_id
        ctx.info(f"Generating greeting for {name} in entity {entity_id}")
        return f"Welcome to {entity_id or 'our server'}, {name}! How can I assist you today?"
    
    return server


def main():
    """Run the example server locally."""
    # Create the server
    server = create_example_server()
    
    # Create FastAPI app
    app = server.create_fastapi_app()
    
    print("=" * 80)
    print("FastMCP Multi-Tenant Server")
    print("=" * 80)
    print(f"Server available at: http://localhost:8000")
    print(f"To connect, use one of the following URLs:")
    print(f"  - SSE Connection: http://localhost:8000/tenant1/sse")
    print(f"  - SSE Connection: http://localhost:8000/tenant2/sse")
    print(f"  - SSE Connection: http://localhost:8000/any-entity-id/sse")
    print("=" * 80)
    
    # Run with uvicorn
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main() 