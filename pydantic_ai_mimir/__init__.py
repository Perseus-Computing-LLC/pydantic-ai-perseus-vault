"""Pydantic AI integration for the Mimir memory engine.

Exposes :class:`MimirToolset`, a Pydantic AI toolset that spawns the local
``mimir`` MCP server and makes its persistent-memory tools available to an agent.
"""

from .toolset import MimirToolset, build_stdio_transport

__all__ = ["MimirToolset", "build_stdio_transport"]

__version__ = "0.1.0"
