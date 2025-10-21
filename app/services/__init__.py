"""Service layer modules for coordinating realtime gameplay."""

from .manager import ConnectionManager

# Single shared manager used by API endpoints.
manager = ConnectionManager()

__all__ = ["ConnectionManager", "manager"]
