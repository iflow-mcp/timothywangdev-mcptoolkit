#!/bin/bash
# Start the FastMCP Multi-Tenancy example server

# Set Redis URL - change this to your actual Redis server
export REDIS_URL="redis://localhost:6379"

# Start the server
echo "Starting FastMCP server at http://localhost:8000"
echo "Using Redis URL: $REDIS_URL"
echo "Press Ctrl+C to stop the server"
echo

# Start uvicorn with the example server
uvicorn example.example_server:app --host 0.0.0.0 --port 8000 --reload 