"""Pydantic AI integration for the Perseus Vault memory engine.

Exposes :class:`PerseusVaultToolset`, a Pydantic AI toolset that spawns the local
``perseus-vault`` MCP server and makes its persistent-memory tools available to
an agent.
"""

from .toolset import PerseusVaultToolset, build_stdio_transport

__all__ = ["PerseusVaultToolset", "build_stdio_transport"]

__version__ = "0.1.0"
