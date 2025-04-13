#!/bin/bash
# Run the MCP SSE client to test the FastMCP Multi-Tenancy server

# Set the server URL (default to localhost)
SERVER_URL=${1:-"http://localhost:8000"}
# Set the entity ID (default to test-entity)
ENTITY_ID=${2:-"test-entity"}

echo "Running MCP SSE client"
echo "Server URL: $SERVER_URL"
echo "Entity ID: $ENTITY_ID"
echo

# Run the client with the specified URL and entity ID
python -m example.mcp_sse_client --url "$SERVER_URL" --entity "$ENTITY_ID" 