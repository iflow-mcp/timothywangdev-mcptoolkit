#!/usr/bin/env python3
"""
Simple test script for MCP server
"""
import asyncio
import json
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

if __name__ == "__main__":
    # Just list the tools for testing
    print("Available tools:")
    for tool in mcp._tool_manager.list_tools():
        print(f"  - {tool.name}: {tool.description}")
    print("\nTotal tools:", len(mcp._tool_manager.list_tools()))