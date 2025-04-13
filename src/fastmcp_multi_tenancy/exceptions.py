"""
Exceptions for FastMCP Multi-Tenancy implementation.
"""


class ResourceError(Exception):
    """Raised when there's an error with resource handling."""
    pass


class ConfigurationError(Exception):
    """Raised when there's an error with the server configuration."""
    pass


class ServerlessError(Exception):
    """Raised when there's an error specific to serverless execution."""
    pass


class StorageError(Exception):
    """Raised when there's an error with Redis storage operations."""
    pass 