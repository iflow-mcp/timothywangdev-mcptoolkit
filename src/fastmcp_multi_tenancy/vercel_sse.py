"""
Vercel-compatible SSE Server Transport Module

This module implements a Server-Sent Events (SSE) transport layer for MCP servers
that is compatible with Vercel serverless functions with fluid compute enabled.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple, cast, Callable
from urllib.parse import quote
from uuid import UUID, uuid4

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

import mcp.types as types
from mcp.server.lowlevel.server import Server as McpServer
from mcp.server.models import InitializationOptions
from .redis_storage import RedisSessionStorage
import inspect
from fastapi import Request

logger = logging.getLogger(__name__)


class RedisObjectReceiveStream(MemoryObjectReceiveStream):
    """A MemoryObjectReceiveStream that receives messages from Redis pub/sub."""
    
    def __init__(self, storage, channel):
        # Create a queue to store messages from Redis
        self._queue = asyncio.Queue()
        self._storage = storage
        self._channel = channel
        self._closed = False
        self._task = None
        
        # Set up the handler for Redis messages
        async def _message_handler(message):
            try:
                # Parse the JSON-RPC message and convert to appropriate MCP type
                if isinstance(message, dict):
                    # Try to parse as a request
                    if "method" in message:
                        if message.get("id") is not None:
                            # It's a request
                            request = types.JSONRPCRequest.model_validate(message)
                            # MCP server expects message.root to be JSONRPCRequest
                            # Since we're using RedisObjectReceiveStream, we need to adapt
                            # Create a wrapper object with root attribute
                            class RequestWrapper:
                                def __init__(self, request):
                                    self.root = request
                            await self._queue.put(RequestWrapper(request))
                        else:
                            # It's a notification
                            notification = types.JSONRPCNotification.model_validate(message)
                            # Same pattern for notifications
                            class NotificationWrapper:
                                def __init__(self, notification):
                                    self.root = notification
                            await self._queue.put(NotificationWrapper(notification))
            except Exception as e:
                logger.error(f"Error processing Redis message: {e}", exc_info=True)
        
        # Subscribe to the Redis channel
        async def _subscribe_and_listen():
            try:
                await self._storage.subscribe(self._channel, _message_handler)
                logger.debug(f"Subscribed to channel {self._channel}")
            except Exception as e:
                logger.error(f"Error subscribing to channel {self._channel}: {e}", exc_info=True)
                
        # Start the subscription task        
        self._task = asyncio.create_task(_subscribe_and_listen())
    
    async def receive(self):
        """Receive a message from the Redis channel."""
        if self._closed:
            raise anyio.EndOfStream("Stream is closed")
        
        # Get the next message from the queue
        try:
            message = await self._queue.get()
            return message
        except asyncio.CancelledError:
            # Handle cancellation gracefully
            self._closed = True
            raise anyio.EndOfStream("Stream was cancelled")
        except Exception as e:
            # Handle other exceptions
            logger.error(f"Error receiving message: {e}", exc_info=True)
            self._closed = True
            raise anyio.EndOfStream(f"Stream error: {e}")
    
    async def aclose(self):
        """Close the stream and unsubscribe from Redis."""
        if not self._closed:
            self._closed = True
            # Cancel the subscription task if running
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await asyncio.wait_for(self._task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                
            # Unsubscribe from the Redis channel
            try:
                await self._storage.unsubscribe(self._channel)
                logger.debug(f"Unsubscribed from channel {self._channel}")
            except Exception as e:
                logger.error(f"Error unsubscribing from channel {self._channel}: {e}", exc_info=True)


class RedisObjectSendStream(MemoryObjectSendStream):
    """A MemoryObjectSendStream that sends messages to Redis pub/sub and a local queue."""
    
    def __init__(self, storage, channel, response_queue):
        self._storage = storage
        self._channel = channel
        self._response_queue = response_queue
        self._closed = False
    
    async def send(self, message):
        """Send a message to the Redis channel and the local response queue."""
        if self._closed:
            raise anyio.ClosedResourceError("Stream is closed")
        
        try:
            # Convert message to a JSON-serializable format
            if hasattr(message, "model_dump"):
                # It's a Pydantic v2 model
                message_data = message.model_dump(by_alias=True)
            elif hasattr(message, "dict"):
                # It's a Pydantic v1 model
                message_data = message.dict(by_alias=True)
            else:
                # It's something else, try to convert to dict
                message_data = message
            
            # Send to Redis
            await self._storage.publish(self._channel, message_data)
            
            # Also put in the local response queue for immediate SSE delivery
            await self._response_queue.put(message_data)
        except Exception as e:
            logger.error(f"Error sending message: {e}", exc_info=True)
            if not self._closed:
                # Try to put an error message in the response queue
                try:
                    error_msg = {
                        "error": {
                            "code": -32000,
                            "message": f"Error sending message: {str(e)}"
                        }
                    }
                    await self._response_queue.put(error_msg)
                except Exception:
                    pass
    
    async def aclose(self):
        """Close the stream."""
        self._closed = True


class VercelSseServerTransport:
    """
    Vercel-compatible SSE server transport for MCP.
    
    This class provides SSE functionality that works with Vercel serverless functions:
    
    1. connect_sse() sets up a new SSE stream to send server messages to the client
    2. handle_post_message() receives client messages through POST requests
    
    Unlike the standard SseServerTransport, this implementation:
    1. Uses Redis for state persistence between function invocations
    2. Is designed to work with Vercel's serverless architecture
    3. Supports multi-tenancy with multiple users connecting to the same endpoint
    4. Supports entity IDs in URL paths (/{entity_id}/sse and /{entity_id}/messages)
    """

    _endpoint_base: str
    _storage: RedisSessionStorage
    _streams: Dict[UUID, bool]
    _closed: bool
    _lifespan: Optional[Callable]

    def __init__(self, endpoint_base: str, redis_url: str, lifespan: Optional[Callable] = None) -> None:
        """
        Create a new Vercel SSE server transport.
        
        Args:
            endpoint_base: Base path for endpoints (e.g., "/messages")
            redis_url: Redis connection URL for state persistence
            lifespan: Optional lifespan context manager for McpServer instances
        """
        super().__init__()
        self._endpoint_base = endpoint_base.rstrip("/")
        self._storage = RedisSessionStorage(redis_url)
        self._streams = {}
        self._closed = False
        self._lifespan = lifespan
        logger.debug(f"VercelSseServerTransport initialized with endpoint base: {endpoint_base}")

    async def setup_fastapi(self, app: FastAPI) -> None:
        """
        Set up FastAPI routes for the SSE transport.
        """
        @app.get("/{entity_id}/sse")
        async def handle_sse(request: Request, entity_id: str):
            """Handle SSE connection requests with entity ID."""
            return await self._create_sse_response(request, entity_id)
        
        @app.post("/{entity_id}" + self._endpoint_base)
        async def handle_post(request: Request, entity_id: str):
            """Handle message POST requests with entity ID."""
            return await self.handle_post_message(request, entity_id)

    async def _create_sse_response(self, request: Request, entity_id: str) -> StreamingResponse:
        """
        Create and return an SSE streaming response.
        
        Args:
            request: FastAPI request object
            entity_id: Entity identifier from URL path
            
        Returns:
            StreamingResponse for SSE communication
        """
        logger.debug(f"Setting up SSE connection for entity: {entity_id}")
        
        # Create a unique session ID for this connection
        session_id = uuid4()
        session_id_str = str(session_id).replace("-", "")
        session_uri = f"/{entity_id}{self._endpoint_base}?session_id={session_id_str}"
        logger.debug(f"Created new session with ID: {session_id}")
        
        # Store the session in Redis with entity ID
        await self._storage.store_session(session_id, {
            "created_at": asyncio.get_event_loop().time(),
            "entity_id": entity_id,
            "client_info": {
                "user_agent": request.headers.get("user-agent", ""),
                "remote_addr": request.client.host if request.client else "unknown",
            }
        })
        
        # Store session ID in streams dictionary to mark it as active
        self._streams[session_id] = True
        logger.debug(f"Marked session {session_id} as active")
        
        server = request.app.state.server
        
        # Create Redis channels for this session
        requests_channel = f"requests:{session_id}"
        responses_channel = f"responses:{session_id}"
        
        # Create a queue for immediate responses during this connection
        response_queue = asyncio.Queue()
        
        # Create Redis-backed streams for the MCP server
        receive_stream = RedisObjectReceiveStream(self._storage, requests_channel)
        send_stream = RedisObjectSendStream(self._storage, responses_channel, response_queue)
        
        # Start the server in a separate task
        async def run_server():
            try:
                logger.debug(f"Starting MCP server for entity: {entity_id}")
                
                # Create a standard MCP server
                mcp_server = McpServer(
                    name=f"SSE Server for {entity_id}",
                    version="0.1.0",
                    lifespan=self._lifespan
                )
                
                # Set up proper session data
                session_data = await self._storage.get_session(session_id) or {}
                session_data["entity_id"] = entity_id
                await self._storage.store_session(session_id, session_data)
                
                # Register essential handlers from the application server if available
                handlers_registered = False
                if server:
                    try:
                        # Get handler map and register with MCP server
                        handlers = server.get_handler_map()
                        
                        # Create wrapper for methods that need access to the request context
                        def create_handler_wrapper(handler_fn, mcp_server):
                            async def wrapped_handler(*args, **kwargs):
                                """Handle MCP requests with context in single-process or serverless environments."""
                                try:
                                    # For call_tool, we need to ensure context is provided
                                    if handler_fn.__name__ == 'call_tool':
                                        logger.debug(f"Handling call_tool with entity_id={entity_id}")
                                        
                                        # First try to get the current request context
                                        request_ctx = None
                                        try:
                                            # This should work in single-process testing
                                            request_ctx = mcp_server.request_context
                                            logger.debug(f"Successfully retrieved request context={request_ctx} from MCP server")
                                        except LookupError:
                                            # This is normal - request context is designed to not be available outside of requests
                                            logger.debug("No request context available (expected in many cases)")
                                            
                                        # Create a context with whatever request_ctx we have (or None)
                                        context = server.get_context(request_ctx, entity_id=entity_id)
                                        
                                        # Pass context as a keyword argument instead of appending to positional args
                                        kwargs['context'] = context
                                    
                                    # Call the original handler
                                    return await handler_fn(*args, **kwargs)
                                except Exception as e:
                                    logger.error(f"Error in handler: {e}")
                                    import traceback
                                    logger.error(f"Detailed traceback:\n{traceback.format_exc()}")
                                    raise
                            return wrapped_handler
                        
                        # Register handlers with proper context wrapping
                        mcp_server.list_tools()(create_handler_wrapper(handlers["list_tools"], mcp_server))
                        mcp_server.call_tool()(create_handler_wrapper(handlers["call_tool"], mcp_server))
                        mcp_server.list_resources()(create_handler_wrapper(handlers["list_resources"], mcp_server))
                        mcp_server.read_resource()(create_handler_wrapper(handlers["read_resource"], mcp_server))
                        mcp_server.list_prompts()(create_handler_wrapper(handlers["list_prompts"], mcp_server))
                        mcp_server.get_prompt()(create_handler_wrapper(handlers["get_prompt"], mcp_server))
                        mcp_server.list_resource_templates()(create_handler_wrapper(handlers["list_resource_templates"], mcp_server))
                        
                        handlers_registered = True
                        logger.debug("Registered all handlers successfully")
                    except Exception as e:
                        logger.error(f"Error registering handlers: {e}", exc_info=True)
                
                # Run the MCP server with our Redis-backed streams
                logger.debug("Starting MCP server run...")

                await mcp_server.run(
                    receive_stream,
                    send_stream,
                    mcp_server.create_initialization_options(),
                )
                logger.debug("MCP server run completed normally")
            except Exception as e:
                import traceback
                logger.error(f"Error running MCP server: {e}", exc_info=True)
                logger.error(f"Detailed traceback:\n{traceback.format_exc()}")
            finally:
                # Clean up when the server finishes
                logger.debug("Cleaning up server resources")
                try:
                    await receive_stream.aclose()
                except Exception as e:
                    logger.error(f"Error closing receive stream: {e}")
                
                try:
                    await send_stream.aclose()
                except Exception as e:
                    logger.error(f"Error closing send stream: {e}")
        
        # Start the server task
        server_task = asyncio.create_task(run_server())
        
        async def event_generator():
            """Generate SSE events."""
            try:
                # Send the endpoint URL as the first event
                yield f"event: endpoint\ndata: {session_uri}\n\n"
                logger.debug(f"Sent endpoint event: {session_uri}")
                
                # Keep the connection alive and send messages
                keep_alive_counter = 0
                while True:
                    # Try to get a message from the response queue with a timeout
                    try:
                        response = await asyncio.wait_for(response_queue.get(), timeout=1.0)
                        # Send the response as an SSE event
                        json_data = json.dumps(response)
                        yield f"event: message\ndata: {json_data}\n\n"
                        logger.debug(f"Sent response via SSE: {json_data[:100]}...")
                    except asyncio.TimeoutError:
                        # Send a keep-alive comment every other time
                        keep_alive_counter += 1
                        if keep_alive_counter % 2 == 0:
                            yield ": keep-alive\n\n"
                    except Exception as e:
                        logger.error(f"Error getting/sending message: {e}", exc_info=True)
                        # Try to continue - don't break the connection
                        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                        await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.debug(f"SSE connection for session {session_id} was cancelled")
                raise
            except Exception as e:
                logger.error(f"Unexpected error in event generator: {e}", exc_info=True)
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            finally:
                # Clean up resources when the connection ends
                logger.debug(f"Event generator ending for session {session_id}")
                try:
                    # Cancel the server task
                    if not server_task.done():
                        server_task.cancel()
                        try:
                            await asyncio.wait_for(server_task, timeout=2.0)
                        except (asyncio.TimeoutError, asyncio.CancelledError):
                            pass
                    
                    # Clean up session when client disconnects
                    await self._storage.unsubscribe(requests_channel)
                    await self._storage.unsubscribe(responses_channel)
                    await self._storage.delete_session(session_id)
                    
                    # Remove from active sessions
                    if session_id in self._streams:
                        del self._streams[session_id]
                        logger.debug(f"Removed session {session_id} from active sessions")
                except Exception as e:
                    logger.error(f"Error in event generator cleanup: {e}", exc_info=True)
        
        # Create the SSE streaming response
        response = StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable proxy buffering
            }
        )
        
        return response

    @asynccontextmanager
    async def connect_sse(self, request: Request, entity_id: str):
        """
        Set up an SSE connection with the client.
        
        Args:
            request: FastAPI request object
            entity_id: Entity identifier from URL path
            
        Yields:
            Tuple of read and write streams for communication
        """
        logger.debug(f"Setting up SSE connection for entity: {entity_id}")
        
        # Create a unique session ID for this connection
        session_id = uuid4()
        # Include entity ID in the endpoint URL
        session_uri = f"/{entity_id}{self._endpoint_base}?session_id={session_id.hex}"
        logger.debug(f"Created new session with ID: {session_id}")
        
        # Create queues for holding messages
        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)
        
        # Store the session in Redis with entity ID
        await self._storage.store_session(session_id, {
            "created_at": asyncio.get_event_loop().time(),
            "entity_id": entity_id,
            "client_info": {
                "user_agent": request.headers.get("user-agent", ""),
                "remote_addr": request.client.host if request.client else "unknown",
            }
        })
        
        try:
            # Yield the streams for MCP server to use
            yield (read_stream, write_stream)
        finally:
            # Ensure we close streams when done
            await read_stream_writer.aclose()
            await write_stream.aclose()

    async def handle_post_message(self, request: Request, entity_id: str) -> Response:
        """
        Handle a POST message from a client.
        
        Args:
            request: FastAPI request object
            entity_id: Entity identifier from URL path
            
        Returns:
            Response object
        """
        logger.debug(f"Handling POST message for entity: {entity_id}")
        
        # Get session ID from query parameters
        session_id_param = request.query_params.get("session_id")
        if session_id_param is None:
            logger.warning("Received request without session_id")
            return JSONResponse(
                content={"error": "session_id is required"}, 
                status_code=400
            )
        
        try:
            # Format the session ID correctly
            if len(session_id_param) == 32 and "-" not in session_id_param:
                # Format without hyphens to UUID with hyphens
                formatted = f"{session_id_param[0:8]}-{session_id_param[8:12]}-{session_id_param[12:16]}-{session_id_param[16:20]}-{session_id_param[20:]}"
                logger.debug(f"Reformatted session ID from {session_id_param} to {formatted}")
                session_id = UUID(formatted)
            else:
                # Try to parse as is
                session_id = UUID(session_id_param)
            
            logger.debug(f"Parsed session ID: {session_id} (hex: {session_id.hex})")
        except ValueError:
            logger.warning(f"Invalid session ID format: {session_id_param}")
            return JSONResponse(
                content={"error": "Invalid session ID format"}, 
                status_code=400
            )
        
        # Check if the session exists
        session_exists = await self._storage.session_exists(session_id)
        logger.debug(f"Session exists: {session_exists}")
        if not session_exists:
            logger.warning(f"Session not found: {session_id}")
            return JSONResponse(
                content={"error": "Session not found"}, 
                status_code=404
            )
        
        # Get the message content
        try:
            message_data = await request.json()
            logger.debug(f"Received message: {message_data}")
            
            # Special handling for notifications which may not have an id
            if message_data.get("method", "").startswith("notifications/"):
                # For notifications, we don't need a response, just acknowledge with 202
                logger.debug(f"Received notification: {message_data.get('method')}")
                
                # Publish message to Redis channel
                requests_channel = f"requests:{session_id}"
                await self._storage.publish(requests_channel, message_data)
                
                # Return success without waiting for a response
                return JSONResponse(content={"status": "ok"}, status_code=202)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in request body")
            return JSONResponse(
                content={"error": "Invalid JSON in request body"}, 
                status_code=400
            )
        
        # Send the message via Redis
        try:
            # Convert the message data to an MCP message
            logger.debug(f"Validating message: {message_data}")
            message = types.JSONRPCRequest.model_validate(message_data)
            logger.debug(f"Validated message: {message}")
            
            # Publish message to Redis channel
            requests_channel = f"requests:{session_id}"
            message_json = message.model_dump(by_alias=True, exclude_none=True)
            await self._storage.publish(requests_channel, message_json)
            logger.debug(f"Published message to channel: {requests_channel}")
            
            # Return a success response
            return JSONResponse(
                content={"status": "ok"},
                status_code=202  # Accepted
            )
        except ValidationError as e:
            logger.warning(f"Invalid MCP message format: {e}")
            return JSONResponse(
                content={"error": "Invalid MCP message format", "details": str(e)}, 
                status_code=400
            )
        except Exception as e:
            import traceback
            logger.error(f"Error sending message: {e}", exc_info=True)
            logger.error(f"Traceback: {traceback.format_exc()}")
            return JSONResponse(
                content={"error": f"Error sending message: {str(e)}"}, 
                status_code=500
            )
    
    async def close(self) -> None:
        """Close Redis connection and clean up resources."""
        self._closed = True
        await self._storage.close() 