"""
Vercel deployment example for FastMCP Multi-Tenant

This file should be placed in the api/ directory of your Vercel project.
"""

import json
import os
import logging
import time
import base64
from io import BytesIO
from typing import Dict, List

# Import the Vercel app creator
from fastmcp_multi_tenancy.vercel import create_vercel_app
from fastmcp_multi_tenancy.server import Context
from mcp.types import TextContent, ImageContent, EmbeddedResource
from mcp.server.fastmcp.utilities.types import Image

# Get Redis URL from environment variable
redis_url = os.environ.get("REDIS_URL")
if not redis_url:
    raise ValueError(
        "REDIS_URL environment variable is required. Set it in your Vercel project settings."
    )

# Create the FastAPI app
app = create_vercel_app(
    name="MCP Vercel Server",
    instructions="A multi-tenant MCP server deployed on Vercel with fluid compute",
    redis_url=redis_url,
    debug=True,  # Enable debug mode for detailed logging
)

# Add tools
@app.state.server.tool(
    name="hello",
    description="Say hello to someone"
)
async def hello(name: str, context: Context) -> str:
    """
    Say hello to someone.
    
    Args:
        name: The name to greet
        context: The execution context (required)
    """
    await context.info(f"Saying hello to {name} with entity {context.entity_id}")
    
    return f"Hello, {name} with entity {context.entity_id}!"

@app.state.server.tool(
    name="calculate",
    description="Perform a calculation"
)
async def calculate(a: float, b: float, operation: str, context: Context) -> Dict:
    """
    Perform a calculation using the specified operation.
    
    Args:
        a: First number
        b: Second number
        operation: Operation to perform (add, subtract, multiply, divide)
        context: The execution context (required)
    """
    
    await context.info(f"Calculating {a} {operation} {b}")
    
    result = None
    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    elif operation == "divide":
        if b == 0:
            await context.error("Cannot divide by zero")
            raise ValueError("Cannot divide by zero")
        result = a / b
    else:
        await context.error(f"Unknown operation: {operation}")
        raise ValueError(f"Unknown operation: {operation}")
    
    # Report progress
    await context.report_progress(100, 100)
    
    return {
        "operation": operation,
        "a": a,
        "b": b,
        "result": result
    }

# New tool with progress reporting
@app.state.server.tool(
    name="longProcess",
    description="Simulate a long-running process with progress updates"
)
async def long_process(steps: int, context: Context) -> str:
    """
    Simulate a long-running process with progress updates.
    
    Args:
        steps: Number of steps to process
        context: The execution context (required)
    """
    await context.info(f"Starting long process with {steps} steps")
    
    for i in range(steps):
        # Log current step
        await context.info(f"Processing step {i+1} of {steps}")
        
        # Report progress (0-100%)
        await context.report_progress(i+1, steps)
        
        # Simulate work
        await asyncio.sleep(0.2)
    
    return f"Completed {steps} steps successfully"

# New tool returning structured data
@app.state.server.tool(
    name="getUserProfile",
    description="Get a user profile"
)
async def get_user_profile(user_id: str, context: Context) -> Dict:
    """
    Get a user's profile data.
    
    Args:
        user_id: The user ID to look up
        context: The execution context (required)
    """
    await context.info(f"Fetching profile for user {user_id}")
    
    # Simulate user data
    user_data = {
        "id": user_id,
        "name": f"User {user_id}",
        "email": f"user{user_id}@example.com",
        "role": "member",
        "createdAt": "2023-01-01T00:00:00Z",
        "settings": {
            "theme": "dark",
            "notifications": True
        }
    }
    
    return user_data

# New tool creating and returning an image
@app.state.server.tool(
    name="generateColorSwatch",
    description="Generate a color swatch image"
)
async def generate_color_swatch(color: str, context: Context) -> ImageContent:
    """
    Generate a color swatch image.
    
    Args:
        color: The color to use (hex code or name)
        context: The execution context (required)
    """
    try:
        from PIL import Image as PILImage, ImageDraw
        
        await context.info(f"Generating color swatch for {color}")
        
        # Create a simple color swatch
        img = PILImage.new('RGB', (100, 100), color=color)
        
        # Save to bytes
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes = img_bytes.getvalue()
        
        # Convert to base64
        b64_img = base64.b64encode(img_bytes).decode('utf-8')
        
        return ImageContent(
            type="image",
            source=f"data:image/png;base64,{b64_img}"
        )
    except Exception as e:
        await context.error(f"Error generating color swatch: {str(e)}")
        return TextContent(
            type="text",
            text=f"Error generating color swatch: {str(e)}"
        )

# Add resources
@app.state.server.resource(
    uri="resource://data",
    name="Sample Data",
    description="A sample data resource",
    mime_type="application/json"
)
async def get_data() -> str:
    """Get sample data."""
    return json.dumps({
        "message": "This data is served from a Vercel serverless function",
        "timestamp": time.time(),
        "items": [
            {"id": 1, "name": "Item 1"},
            {"id": 2, "name": "Item 2"},
            {"id": 3, "name": "Item 3"}
        ]
    })

# New resource with multiple parameters
@app.state.server.resource(
    uri="users://{user_id}/documents/{doc_id}",
    name="User Document",
    description="Access a specific document for a user",
    mime_type="text/plain"
)
async def get_user_document(user_id: str, doc_id: str) -> str:
    """
    Get a specific document for a user.
    
    Args:
        user_id: The user ID
        doc_id: The document ID
    """
    # In a real implementation, this would fetch from a database
    return f"Document content for user {user_id}, document {doc_id}\n\nThis is a sample document content that would normally be retrieved from a database or storage system."

# Embedded resource example
@app.state.server.resource(
    uri="resource://sample/markdown",
    name="Sample Markdown",
    description="A sample markdown embedded resource",
    mime_type="text/markdown"
)
async def get_markdown() -> EmbeddedResource:
    """Get sample markdown as an embedded resource."""
    content = """
# Sample Markdown Document

This is an example of an embedded **markdown** resource.

## Features
- Formatted text
- Lists like this one
- *Emphasis* and **strong text**

```python
# Even code blocks
def hello_world():
    print("Hello from embedded markdown!")
```
    """
    
    return EmbeddedResource(
        type="embedded",
        mimeType="text/markdown",
        content=content
    )

# Add prompts
@app.state.server.prompt(
    name="greeting",
    description="Generate a greeting message"
)
def greeting_prompt(name: str) -> str:
    """Generate a greeting message."""
    return f"Welcome to our Vercel-deployed MCP server, {name}! How can I assist you today?"

# New structured prompt example
@app.state.server.prompt(
    name="assistUser",
    description="Start a conversation to assist a user with a specific problem"
)
def assist_user_prompt(problem: str, username: str) -> List[Dict]:
    """
    Generate a structured conversation starter based on a user's problem.
    
    Args:
        problem: Description of the user's problem
        username: The user's name
    """
    return [
        {
            "role": "system",
            "content": {
                "type": "text",
                "text": "You are a helpful assistant specializing in technical support."
            }
        },
        {
            "role": "user",
            "content": {
                "type": "text",
                "text": f"Hi, I'm {username} and I'm having an issue: {problem}"
            }
        },
        {
            "role": "assistant",
            "content": {
                "type": "text",
                "text": f"Hello {username}, I'll help you solve this problem. Could you provide more details about when you first noticed this issue?"
            }
        }
    ]

# New tutorial prompt
@app.state.server.prompt(
    name="tutorialCode",
    description="Generate a coding tutorial with sample code"
)
def tutorial_code_prompt(language: str, concept: str) -> List[Dict]:
    """
    Generate a coding tutorial with sample code.
    
    Args:
        language: Programming language
        concept: Programming concept to explain
    """
    return [
        {
            "role": "system",
            "content": {
                "type": "text",
                "text": f"You are an expert {language} programming tutor."
            }
        },
        {
            "role": "user",
            "content": {
                "type": "text",
                "text": f"Please teach me about {concept} in {language} with clear examples."
            }
        }
    ]

# Import async for the long_process tool
import asyncio 