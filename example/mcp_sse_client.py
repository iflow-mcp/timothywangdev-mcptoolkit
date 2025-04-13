#!/usr/bin/env python3
"""
Example MCP SSE Client for testing prompts functionality.

This client demonstrates how to:
1. Connect to an MCP server using SSE
2. List available prompts
3. Get a specific prompt with arguments
4. List and call tools with various types of returns
5. Access resources with different patterns and formats
"""

import asyncio
import json
import logging
import traceback
from typing import Any, Dict
import argparse
import base64
from PIL import Image as PILImage
from io import BytesIO

from mcp import ClientSession, types
from mcp.client.sse import sse_client


# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mcp-client")


async def handle_sampling_message(
    message: types.CreateMessageRequestParams,
) -> types.CreateMessageResult:
    """Optional sampling callback handler."""
    logger.info(f"Received sampling request: {message}")
    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(
            type="text",
            text="This is a response from the client-side model.",
        ),
        model="example-model",
        stopReason="endTurn",
    )


async def run_prompts_test(session: ClientSession):
    """Test the prompts functionality."""
    # List available prompts
    logger.info("Testing prompts/list...")
    try:
        prompts = await session.list_prompts()
        logger.info(f"Found {len(prompts)} prompts:")
        for prompt in prompts:
            logger.info(f"  - {prompt.name}: {prompt.description}")
            if prompt.arguments:
                logger.info(f"    Arguments:")
                for arg in prompt.arguments:
                    required = "(required)" if arg.required else "(optional)"
                    logger.info(f"      - {arg.name}: {arg.description} {required}")
    except Exception as e:
        logger.error(f"Error listing prompts: {e}")
        logger.error(traceback.format_exc())
    
    # Get a simple prompt
    logger.info("\nTesting prompts/get with 'greeting' prompt...")
    try:
        prompt_result = await session.get_prompt(
            "greeting", arguments={"name": "Test User"}
        )
        logger.info("Prompt result:")
        logger.info(f"  Description: {prompt_result.description}")
        logger.info("  Messages:")
        for message in prompt_result.messages:
            logger.info(f"    - Role: {message.role}")
            if hasattr(message.content, "text"):
                logger.info(f"      Content: {message.content.text}")
            else:
                logger.info(f"      Content: {message.content}")
    except Exception as e:
        logger.error(f"Error getting prompt: {e}")
        logger.error(traceback.format_exc())
    
    # Get a structured prompt
    logger.info("\nTesting prompts/get with 'assistUser' prompt...")
    try:
        prompt_result = await session.get_prompt(
            "assistUser", arguments={"problem": "My application is crashing", "username": "John"}
        )
        logger.info("Structured prompt result:")
        logger.info(f"  Description: {prompt_result.description}")
        logger.info("  Messages:")
        for message in prompt_result.messages:
            logger.info(f"    - Role: {message.role}")
            if hasattr(message.content, "text"):
                logger.info(f"      Content: {message.content.text}")
            else:
                logger.info(f"      Content: {message.content}")
    except Exception as e:
        logger.error(f"Error getting structured prompt: {e}")
        logger.error(traceback.format_exc())
    
    # Get the tutorial prompt
    logger.info("\nTesting prompts/get with 'tutorialCode' prompt...")
    try:
        prompt_result = await session.get_prompt(
            "tutorialCode", arguments={"language": "Python", "concept": "async/await"}
        )
        logger.info("Tutorial prompt result:")
        logger.info(f"  Description: {prompt_result.description}")
        logger.info("  Messages:")
        for message in prompt_result.messages:
            logger.info(f"    - Role: {message.role}")
            if hasattr(message.content, "text"):
                logger.info(f"      Content: {message.content.text}")
            else:
                logger.info(f"      Content: {message.content}")
    except Exception as e:
        logger.error(f"Error getting tutorial prompt: {e}")
        logger.error(traceback.format_exc())


async def run_tools_test(session: ClientSession):
    """Test the tools functionality."""
    # List available tools
    logger.info("\nTesting tools/list...")
    try:
        tools = await session.list_tools()
        logger.info(f"Found {len(tools)} tools:")
        for tool in tools:
            logger.info(f"  - {tool.name}: {tool.description}")
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        logger.error(traceback.format_exc())
    
    # Test the hello tool
    logger.info("\nTesting tools/call with 'hello' tool...")
    try:
        hello_result = await session.call_tool("hello", {"name": "Test User"})
        logger.info("Tool result:")
        for content in hello_result:
            if hasattr(content, "text"):
                logger.info(f"  Content: {content.text}")
            else:
                logger.info(f"  Content: {content}")
    except Exception as e:
        logger.error(f"Error calling hello tool: {e}")
        logger.error(traceback.format_exc())
    
    # Test the calculate tool
    logger.info("\nTesting tools/call with 'calculate' tool...")
    try:
        calc_result = await session.call_tool(
            "calculate", 
            {"a": 10, "b": 5, "operation": "multiply"}
        )
        logger.info("Tool result:")
        for content in calc_result:
            if hasattr(content, "text"):
                logger.info(f"  Content: {content.text}")
            else:
                logger.info(f"  Content: {content}")
    except Exception as e:
        logger.error(f"Error calling calculate tool: {e}")
        logger.error(traceback.format_exc())
        
    # Test the user profile tool
    logger.info("\nTesting tools/call with 'getUserProfile' tool...")
    try:
        profile_result = await session.call_tool(
            "getUserProfile", 
            {"user_id": "12345"}
        )
        logger.info("User profile result:")
        for content in profile_result:
            if hasattr(content, "text"):
                logger.info(f"  Content: {content.text}")
            else:
                logger.info(f"  Content: {content}")
    except Exception as e:
        logger.error(f"Error calling getUserProfile tool: {e}")
        logger.error(traceback.format_exc())
    
    # Test the color swatch image tool
    logger.info("\nTesting tools/call with 'generateColorSwatch' tool...")
    try:
        swatch_result = await session.call_tool(
            "generateColorSwatch", 
            {"color": "#3498DB"}  # Blue color
        )
        logger.info("Color swatch result:")
        for content in swatch_result:
            if hasattr(content, "type") and content.type == "image":
                logger.info(f"  Received image with source starting with: {content.source[:30]}...")
                
                # Optionally save the image
                try:
                    if content.source.startswith("data:image/png;base64,"):
                        b64_data = content.source.split(",")[1]
                        img_data = base64.b64decode(b64_data)
                        img = PILImage.open(BytesIO(img_data))
                        logger.info(f"  Image size: {img.size}")
                except Exception as img_err:
                    logger.error(f"Error processing image: {img_err}")
            else:
                logger.info(f"  Content: {content}")
    except Exception as e:
        logger.error(f"Error calling generateColorSwatch tool: {e}")
        logger.error(traceback.format_exc())
    
    # Test long process tool with progress
    logger.info("\nTesting tools/call with 'longProcess' tool...")
    try:
        # Use a small number of steps to keep the test short
        long_result = await session.call_tool(
            "longProcess", 
            {"steps": 3}
        )
        logger.info("Long process result:")
        for content in long_result:
            if hasattr(content, "text"):
                logger.info(f"  Content: {content.text}")
            else:
                logger.info(f"  Content: {content}")
    except Exception as e:
        logger.error(f"Error calling longProcess tool: {e}")
        logger.error(traceback.format_exc())


async def run_resources_test(session: ClientSession):
    """Test the resources functionality."""
    # List available resources
    logger.info("\nTesting resources/list...")
    try:
        resources = await session.list_resources()
        logger.info(f"Found {len(resources)} resources:")
        for resource in resources:
            logger.info(f"  - {resource.uri}: {resource.name} ({resource.mimeType})")
            logger.info(f"    Description: {resource.description}")
    except Exception as e:
        logger.error(f"Error listing resources: {e}")
        logger.error(traceback.format_exc())
    
    # Test reading standard resource
    logger.info("\nTesting resources/read with 'resource://data'...")
    try:
        data_content, mime_type = await session.read_resource("resource://data")
        logger.info(f"Resource content (mime type: {mime_type}):")
        logger.info(f"  {data_content}")
    except Exception as e:
        logger.error(f"Error reading data resource: {e}")
        logger.error(traceback.format_exc())
    
    # Test reading parameterized resource
    logger.info("\nTesting resources/read with parameterized URI 'users://123/documents/456'...")
    try:
        doc_content, mime_type = await session.read_resource("users://123/documents/456")
        logger.info(f"Document resource content (mime type: {mime_type}):")
        logger.info(f"  {doc_content}")
    except Exception as e:
        logger.error(f"Error reading document resource: {e}")
        logger.error(traceback.format_exc())
    
    # Test reading markdown resource
    logger.info("\nTesting resources/read with 'resource://sample/markdown'...")
    try:
        md_content, mime_type = await session.read_resource("resource://sample/markdown")
        logger.info(f"Markdown resource content (mime type: {mime_type}):")
        logger.info(f"  {md_content}")
    except Exception as e:
        logger.error(f"Error reading markdown resource: {e}")
        logger.error(traceback.format_exc())


async def main():
    """Run the MCP SSE client."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="MCP SSE Client for testing")
    parser.add_argument("--url", default="http://localhost:8000", help="Server URL")
    parser.add_argument("--entity", default="test-entity", help="Entity ID")
    args = parser.parse_args()
    
    # Server URL and entity ID
    server_url = args.url
    entity_id = args.entity
    
    logger.info(f"Connecting to MCP server at {server_url} with entity ID: {entity_id}")
    
    try:
        # Connect to the server using SSE
        async with sse_client(f"{server_url}/{entity_id}/sse") as (read, write):
            # Create a client session
            async with ClientSession(
                read, write, sampling_callback=handle_sampling_message
            ) as session:
                # Initialize the connection
                logger.info("Initializing session...")
                init_result = await session.initialize()
                logger.info("Connection initialized successfully")
                logger.info(f"Server info: {init_result.serverInfo.name} v{init_result.serverInfo.version}")
                logger.info(f"Protocol version: {init_result.protocolVersion}")
                logger.info(f"Server capabilities: {init_result.capabilities}")
                
                # Wait a moment before sending requests
                await asyncio.sleep(1)
                
                # Run the prompts test
                await run_prompts_test(session)
                
                # Run the tools test
                await run_tools_test(session)
                
                # Run the resources test
                await run_resources_test(session)
                
                # Keep the connection alive for a moment
                logger.info("Connection established. Waiting 5 seconds before disconnecting...")
                await asyncio.sleep(5)
                logger.info("Client shutting down...")
    except Exception as e:
        logger.error(f"Error connecting to server: {e}")
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Client terminated by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc()) 