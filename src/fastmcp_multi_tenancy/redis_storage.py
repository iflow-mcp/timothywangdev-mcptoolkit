"""
Redis Storage Module for Multi-tenancy MCP Server

This module provides Redis-based storage for session state persistence
in serverless environments.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Set, Union
from uuid import UUID

import redis.asyncio as redis
from pydantic import BaseModel
import asyncio

logger = logging.getLogger(__name__)


class RedisSessionStorage:
    """
    Redis-based storage for MCP session state.
    
    This class provides persistence for session data in serverless environments
    where in-memory storage would be lost between function invocations.
    """
    
    def __init__(self, redis_url: str, prefix: str = "mcp:"):
        """
        Initialize Redis session storage.
        
        Args:
            redis_url: Redis connection URL
            prefix: Key prefix for Redis storage (to avoid collisions)
        """
        self.redis = redis.from_url(redis_url)
        self.redis_url = redis_url
        self.prefix = prefix
        self._redis_lock = asyncio.Lock()
        
        # Create separate connections for pub/sub
        self._publisher = None
        self._subscriber = None
        self._handlers = {}  # Channel handlers
    
    async def get_publisher(self):
        """Get Redis publisher connection."""
        if self._publisher is None:
            self._publisher = redis.from_url(self.redis_url)
        return self._publisher
    
    async def get_subscriber(self):
        """Get Redis subscriber connection."""
        if self._subscriber is None:
            self._subscriber = redis.from_url(self.redis_url)
        return self._subscriber
    
    async def publish(self, channel: str, message: Dict[str, Any]) -> None:
        """
        Publish a message to a Redis channel.
        
        Args:
            channel: Channel name
            message: Message to publish
        """
        publisher = await self.get_publisher()
        await publisher.publish(channel, json.dumps(message))
        logger.debug(f"Published message to channel {channel}")
    
    async def subscribe(self, channel: str, handler: callable) -> None:
        """
        Subscribe to a Redis channel.
        
        Args:
            channel: Channel name
            handler: Callback function to handle messages
        """
        # Save handler
        self._handlers[channel] = handler
        
        # Start listening to messages in background
        asyncio.create_task(self._listen_for_messages(channel))
        
        logger.debug(f"Started listening task for channel {channel}")
    
    async def _listen_for_messages(self, channel: str) -> None:
        """
        Listen for messages on a Redis channel.
        
        Args:
            channel: Channel name
        """
        subscriber = await self.get_subscriber()
        
        try:
            # Create Redis pubsub
            pubsub = subscriber.pubsub()
            await pubsub.subscribe(channel)
            logger.debug(f"Subscribed to channel {channel}")
            
            # Start a background task to listen for messages
            async def message_reader():
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message is not None and message["type"] == "message":
                        handler = self._handlers.get(channel)
                        if handler:
                            try:
                                # Parse message data
                                data = json.loads(message["data"])
                                # Call handler
                                await handler(data)
                            except Exception as e:
                                logger.error(f"Error in handler for channel {channel}: {e}")
                    
                    # Small sleep to avoid CPU spin
                    await asyncio.sleep(0.01)
            
            # Start the background task
            asyncio.create_task(message_reader())
            
        except Exception as e:
            logger.error(f"Error setting up message listener for channel {channel}: {e}")
    
    async def unsubscribe(self, channel: str) -> None:
        """
        Unsubscribe from a Redis channel.
        
        Args:
            channel: Channel name
        """
        try:
            subscriber = await self.get_subscriber()
            pubsub = subscriber.pubsub()
            await pubsub.unsubscribe(channel)
            
            # Remove handler
            if channel in self._handlers:
                del self._handlers[channel]
            
            logger.debug(f"Unsubscribed from channel {channel}")
        except Exception as e:
            logger.error(f"Error unsubscribing from channel {channel}: {e}")
    
    async def close(self) -> None:
        """Close Redis connections."""
        await self.redis.close()
        
        if self._publisher:
            await self._publisher.close()
        
        if self._subscriber:
            # Unsubscribe from all channels
            for channel in list(self._handlers.keys()):
                await self.unsubscribe(channel)
            await self._subscriber.close()
    
    async def _key(self, *parts: Union[str, UUID]) -> str:
        """Create a prefixed Redis key from parts."""
        joined_parts = ":".join(str(p) for p in parts)
        return f"{self.prefix}{joined_parts}"
    
    async def store_session(self, session_id: UUID, data: Dict[str, Any]) -> None:
        """
        Store session data in Redis.
        
        Args:
            session_id: Unique session identifier
            data: Session data to store
        """
        key = await self._key("session", session_id)
        await self.redis.set(key, json.dumps(data))
        logger.debug(f"Stored session {session_id} in Redis")
    
    async def get_session(self, session_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Retrieve session data from Redis.
        
        Args:
            session_id: Unique session identifier
            
        Returns:
            Session data dict or None if not found
        """
        key = await self._key("session", session_id)
        data = await self.redis.get(key)
        if data:
            logger.debug(f"Retrieved session {session_id} from Redis")
            return json.loads(data)
        logger.debug(f"Session {session_id} not found in Redis")
        return None
    
    async def delete_session(self, session_id: UUID) -> None:
        """
        Delete session data from Redis.
        
        Args:
            session_id: Unique session identifier
        """
        key = await self._key("session", session_id)
        await self.redis.delete(key)
        logger.debug(f"Deleted session {session_id} from Redis")
    
    async def store_message(self, session_id: UUID, message_id: str, message: Dict[str, Any]) -> None:
        """
        Store a message in Redis.
        
        Args:
            session_id: Session identifier
            message_id: Message identifier
            message: Message data
        """
        key = await self._key("message", session_id, message_id)
        await self.redis.set(key, json.dumps(message))
        logger.debug(f"Stored message {message_id} for session {session_id}")
    
    async def get_message(self, session_id: UUID, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a message from Redis.
        
        Args:
            session_id: Session identifier
            message_id: Message identifier
            
        Returns:
            Message data or None if not found
        """
        key = await self._key("message", session_id, message_id)
        data = await self.redis.get(key)
        if data:
            return json.loads(data)
        return None
    
    async def list_sessions(self) -> List[UUID]:
        """
        List all active session IDs.
        
        Returns:
            List of active session UUIDs
        """
        keys = await self.redis.keys(f"{self.prefix}session:*")
        return [UUID(key.decode().split(":")[-1]) for key in keys]
    
    async def add_to_queue(self, session_id: UUID, message: Dict[str, Any]) -> None:
        """
        Add a message to a session's message queue.
        
        Args:
            session_id: Session identifier
            message: Message to queue
        """
        key = await self._key("queue", session_id)
        await self.redis.rpush(key, json.dumps(message))
        logger.debug(f"Added message to queue for session {session_id}")
    
    async def get_from_queue(self, session_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get the next message from a session's queue (non-blocking).
        
        Args:
            session_id: Session identifier
            
        Returns:
            Next message or None if queue is empty
        """
        key = await self._key("queue", session_id)
        data = await self.redis.lpop(key)
        if data:
            return json.loads(data)
        return None
    
    async def wait_for_message(self, session_id: UUID, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """
        Wait for a message from a session's queue (blocking with timeout).
        
        Args:
            session_id: Session identifier
            timeout: Timeout in seconds
            
        Returns:
            Next message or None if timeout
        """
        key = await self._key("queue", session_id)
        result = await self.redis.blpop(key, timeout=timeout)
        if result:
            _, data = result
            return json.loads(data)
        return None
    
    async def store_streams(self, session_id: UUID, read_stream, write_stream):
        """
        Store the read and write streams for a session.
        
        Args:
            session_id: Session ID
            read_stream: Read stream
            write_stream: Write stream
        """
        # We don't actually store these in Redis, just keep them in memory
        # associated with the session
        async with self._redis_lock:
            if not hasattr(self, "_streams"):
                self._streams = {}
            
            self._streams[session_id] = (read_stream, write_stream)

    async def get_streams(self, session_id: UUID):
        """
        Get the read and write streams for a session.
        
        Args:
            session_id: Session ID
            
        Returns:
            Tuple of (read_stream, write_stream)
        """
        async with self._redis_lock:
            if not hasattr(self, "_streams"):
                raise ValueError(f"No streams found for session {session_id}")
            
            if session_id not in self._streams:
                raise ValueError(f"No streams found for session {session_id}")
            
            return self._streams[session_id]

    async def session_exists(self, session_id: UUID) -> bool:
        """
        Check if a session exists.
        
        Args:
            session_id: Session ID
            
        Returns:
            True if the session exists, False otherwise
        """
        key = await self._key("session", session_id)
        exists = await self.redis.exists(key)
        return bool(exists) 