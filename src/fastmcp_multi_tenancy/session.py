"""
Redis-backed Server Session Module for Multi-tenancy

This module provides a MultiTenantServerSession class that stores session state in 
Redis for persistence across serverless function invocations.
"""

from enum import Enum
from typing import Any, Dict, Optional, TypeVar
from uuid import UUID

import anyio
import anyio.lowlevel
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import AnyUrl

import mcp.types as types
from mcp.server.models import InitializationOptions
from mcp.shared.session import BaseSession, RequestResponder

from .redis_storage import RedisSessionStorage


class InitializationState(Enum):
    """Session initialization states."""
    NotInitialized = 1
    Initializing = 2
    Initialized = 3


MultiTenantServerSessionT = TypeVar("MultiTenantServerSessionT", bound="MultiTenantServerSession")


class MultiTenantServerSession(
    BaseSession[
        types.ServerRequest,
        types.ServerNotification,
        types.ServerResult,
        types.ClientRequest,
        types.ClientNotification,
    ]
):
    """
    Multi-tenant server session with Redis-backed state persistence.
    
    This class extends the standard ServerSession to support:
    1. State persistence across serverless function invocations
    2. Multiple sessions in a multi-tenant environment
    
    Session state is stored in Redis instead of memory to support serverless environments.
    """
    
    _session_id: UUID
    _storage: RedisSessionStorage
    _initialization_state: InitializationState = InitializationState.NotInitialized
    _client_params: types.InitializeRequestParams | None = None
    _session_data: Dict[str, Any] = {}

    def __init__(
        self,
        session_id: UUID,
        storage: RedisSessionStorage,
        read_stream: MemoryObjectReceiveStream[types.JSONRPCMessage | Exception],
        write_stream: MemoryObjectSendStream[types.JSONRPCMessage],
        init_options: InitializationOptions,
    ) -> None:
        """
        Initialize a multi-tenant server session.
        
        Args:
            session_id: Unique session identifier
            storage: Redis storage instance
            read_stream: Stream for reading client messages
            write_stream: Stream for writing messages to client
            init_options: Initialization options
        """
        super().__init__(
            read_stream, write_stream, types.ClientRequest, types.ClientNotification
        )
        self._session_id = session_id
        self._storage = storage
        self._initialization_state = InitializationState.NotInitialized
        self._init_options = init_options
        self._session_data = {}
        
    @property
    def session_id(self) -> UUID:
        """Get the session ID."""
        return self._session_id
        
    @property
    def client_params(self) -> types.InitializeRequestParams | None:
        """Get client initialization parameters."""
        return self._client_params

    async def _load_state(self) -> None:
        """Load session state from Redis."""
        session_data = await self._storage.get_session(self._session_id)
        if not session_data:
            return
            
        # Store the full session data
        self._session_data = session_data
            
        # Extract specific fields we need
        if "client_params" in session_data:
            self._client_params = types.InitializeRequestParams.model_validate(
                session_data["client_params"]
            )
            
        if "initialization_state" in session_data:
            self._initialization_state = InitializationState(
                session_data.get("initialization_state", InitializationState.NotInitialized.value)
            )

    async def _save_state(self) -> None:
        """Save session state to Redis."""
        # Start with current session data to preserve entity_id and other fields
        session_data = dict(self._session_data) if self._session_data else {}
        
        # Update with current state
        session_data.update({
            "initialization_state": self._initialization_state.value,
        })
        
        if self._client_params:
            session_data["client_params"] = self._client_params.model_dump()
            
        # Store the updated data
        await self._storage.store_session(self._session_id, session_data)
        
        # Update our local copy
        self._session_data = session_data

    def check_client_capability(self, capability: types.ClientCapabilities) -> bool:
        """
        Check if the client supports a specific capability.
        
        Args:
            capability: Capability to check
            
        Returns:
            True if the client supports the capability, False otherwise
        """
        if self._client_params is None:
            return False

        # Get client capabilities from initialization params
        client_caps = self._client_params.capabilities

        # Check each specified capability in the passed in capability object
        if capability.roots is not None:
            if client_caps.roots is None:
                return False
            if capability.roots.listChanged and not client_caps.roots.listChanged:
                return False

        if capability.sampling is not None:
            if client_caps.sampling is None:
                return False

        if capability.experimental is not None:
            if client_caps.experimental is None:
                return False
            # Check each experimental capability
            for exp_key, exp_value in capability.experimental.items():
                if (
                    exp_key not in client_caps.experimental
                    or client_caps.experimental[exp_key] != exp_value
                ):
                    return False

        return True

    async def _received_request(
        self, responder: RequestResponder[types.ClientRequest, types.ServerResult]
    ):
        """
        Handle incoming client requests.
        
        Args:
            responder: Request responder
        """
        await self._load_state()
        
        match responder.request.root:
            case types.InitializeRequest(params=params):
                self._initialization_state = InitializationState.Initializing
                self._client_params = params
                with responder:
                    await responder.respond(
                        types.ServerResult(
                            types.InitializeResult(
                                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                                capabilities=self._init_options.capabilities,
                                serverInfo=types.Implementation(
                                    name=self._init_options.server_name,
                                    version=self._init_options.server_version,
                                ),
                                instructions=self._init_options.instructions,
                            )
                        )
                    )
                await self._save_state()
            case _:
                if self._initialization_state != InitializationState.Initialized:
                    raise RuntimeError(
                        "Received request before initialization was complete"
                    )

    async def _received_notification(
        self, notification: types.ClientNotification
    ) -> None:
        """
        Handle incoming client notifications.
        
        Args:
            notification: Client notification
        """
        await self._load_state()
        
        # Need this to avoid ASYNC910
        await anyio.lowlevel.checkpoint()
        match notification.root:
            case types.InitializedNotification():
                self._initialization_state = InitializationState.Initialized
                await self._save_state()
            case _:
                if self._initialization_state != InitializationState.Initialized:
                    raise RuntimeError(
                        "Received notification before initialization was complete"
                    )

    async def send_log_message(
        self, level: types.LoggingLevel, data: Any, logger: str | None = None
    ) -> None:
        """
        Send a log message notification to the client.
        
        Args:
            level: Log level
            data: Log data
            logger: Logger name
        """
        await self.send_notification(
            types.ServerNotification(
                types.LoggingMessageNotification(
                    method="notifications/message",
                    params=types.LoggingMessageNotificationParams(
                        level=level,
                        data=data,
                        logger=logger,
                    ),
                )
            )
        )

    async def send_resource_updated(self, uri: AnyUrl) -> None:
        """
        Send a resource updated notification to the client.
        
        Args:
            uri: Resource URI
        """
        await self.send_notification(
            types.ServerNotification(
                types.ResourceUpdatedNotification(
                    method="notifications/resources/updated",
                    params=types.ResourceUpdatedNotificationParams(uri=uri),
                )
            )
        )

    async def create_message(
        self,
        messages: list[types.SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: types.IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: types.ModelPreferences | None = None,
    ) -> types.CreateMessageResult:
        """
        Send a sampling/create_message request to the client.
        
        Args:
            messages: List of messages
            max_tokens: Maximum number of tokens to generate
            system_prompt: System prompt
            include_context: Context to include
            temperature: Sampling temperature
            stop_sequences: Sequences to stop generation
            metadata: Additional metadata
            model_preferences: Model preferences
            
        Returns:
            Create message result
        """
        return await self.send_request(
            types.ServerRequest(
                types.CreateMessageRequest(
                    method="sampling/createMessage",
                    params=types.CreateMessageRequestParams(
                        messages=messages,
                        systemPrompt=system_prompt,
                        includeContext=include_context,
                        temperature=temperature,
                        maxTokens=max_tokens,
                        stopSequences=stop_sequences,
                        metadata=metadata,
                        modelPreferences=model_preferences,
                    ),
                )
            ),
            types.CreateMessageResult,
        )

    async def list_roots(self) -> types.ListRootsResult:
        """
        Send a roots/list request to the client.
        
        Returns:
            List roots result
        """
        return await self.send_request(
            types.ServerRequest(
                types.ListRootsRequest(
                    method="roots/list",
                )
            ),
            types.ListRootsResult,
        )

    async def send_ping(self) -> types.EmptyResult:
        """
        Send a ping request to the client.
        
        Returns:
            Empty result
        """
        return await self.send_request(
            types.ServerRequest(
                types.PingRequest(
                    method="ping",
                )
            ),
            types.EmptyResult,
        )

    async def send_progress_notification(
        self, progress_token: str | int, progress: float, total: float | None = None
    ) -> None:
        """
        Send a progress notification to the client.
        
        Args:
            progress_token: Progress token
            progress: Current progress value
            total: Total progress value
        """
        await self.send_notification(
            types.ServerNotification(
                types.ProgressNotification(
                    method="notifications/progress",
                    params=types.ProgressNotificationParams(
                        token=progress_token,
                        value=progress,
                        total=total,
                    ),
                )
            )
        )

    async def send_resource_list_changed(self) -> None:
        """Send a resource list changed notification to the client."""
        await self.send_notification(
            types.ServerNotification(
                types.ResourceListChangedNotification(
                    method="notifications/resources/listChanged",
                )
            )
        )

    async def send_tool_list_changed(self) -> None:
        """Send a tool list changed notification to the client."""
        await self.send_notification(
            types.ServerNotification(
                types.ToolListChangedNotification(
                    method="notifications/tools/listChanged",
                )
            )
        )

    async def send_prompt_list_changed(self) -> None:
        """Send a prompt list changed notification to the client."""
        await self.send_notification(
            types.ServerNotification(
                types.PromptListChangedNotification(
                    method="notifications/prompts/listChanged",
                )
            )
        ) 