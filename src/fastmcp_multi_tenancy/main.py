"""
MCPToolKit - Production-Ready MCP Server Framework
Main entry point for stdio transport
"""

import asyncio
from mcp.server.stdio import stdio_server
from mcp.server.fastmcp import FastMCP

# Create a simple MCP server for stdio transport
mcp = FastMCP("MCPToolKit Demo")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b

@mcp.tool()
def subtract(a: int, b: int) -> int:
    """Subtract two numbers"""
    return a - b

@mcp.tool()
def multiply(a: int, b: int) -> int:
    """Multiply two numbers"""
    return a * b

@mcp.tool()
def divide(a: float, b: float) -> float:
    """Divide two numbers"""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

async def main():
    """Main entry point"""
    async with stdio_server() as (read_stream, write_stream):
        await mcp.run(
            read_stream,
            write_stream
        )

def main_sync():
    """Synchronous entry point for uvx"""
    asyncio.run(main())

if __name__ == "__main__":
    main_sync()