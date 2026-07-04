"""``PerseusVaultToolset`` — a Pydantic AI toolset backed by the Perseus Vault memory engine.

Perseus Vault (https://github.com/Perseus-Computing-LLC/perseus-vault) is an
open-source (MIT) local-first, encrypted, persistent memory engine that speaks
the Model Context Protocol (MCP) over stdio. It ships dozens of memory tools
(``mimir_remember``, ``mimir_recall``, ``mimir_timeline``, ...) that let an agent
durably store and retrieve facts across sessions.

Pydantic AI already speaks MCP natively via
:class:`pydantic_ai.mcp.MCPToolset`. ``PerseusVaultToolset`` is a thin, ergonomic
subclass of that toolset: instead of hand-assembling a ``StdioTransport`` and
remembering the exact ``perseus-vault serve --db ...`` invocation, you write::

    from pydantic_ai import Agent
    from pydantic_ai_perseus_vault import PerseusVaultToolset

    agent = Agent('openai:gpt-5', toolsets=[PerseusVaultToolset(db_path='~/.mimir/agent.db')])

The toolset:

* resolves the ``perseus-vault`` binary from ``$PATH`` (or an explicit path) and
  fails fast with an actionable error if it is missing;
* expands ``~`` in the database path and creates the parent directory;
* wires an optional AES-256-GCM encryption-key file into the server;
* spawns ``perseus-vault serve --db <db_path>`` as the stdio MCP server and
  exposes all of Perseus Vault's tools to the agent.

Because it *is* an :class:`~pydantic_ai.mcp.MCPToolset`, every Pydantic AI MCP
feature (tool caching, ``include_instructions``, ``process_tool_call``, tool
filtering/renaming via wrapper toolsets, etc.) works unchanged.
"""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING, Any

from pydantic_ai.mcp import MCPToolset

if TYPE_CHECKING:
    from pydantic_ai._run_context import AgentDepsT
else:  # pragma: no cover - runtime alias only
    AgentDepsT = Any


def _resolve_binary(perseus_vault_binary: str) -> str:
    """Return an absolute path to the ``perseus-vault`` executable.

    An absolute/explicit path is returned as-is; a bare name is resolved against
    ``$PATH``.

    Raises:
        FileNotFoundError: If the binary cannot be located.
    """
    # Treat anything with a path separator (or an absolute path) as explicit.
    if (
        os.path.isabs(perseus_vault_binary)
        or os.sep in perseus_vault_binary
        or (os.altsep and os.altsep in perseus_vault_binary)
    ):
        if not os.path.isfile(perseus_vault_binary):
            raise FileNotFoundError(
                f"perseus-vault binary not found at {perseus_vault_binary!r}."
            )
        return perseus_vault_binary

    resolved = shutil.which(perseus_vault_binary)
    if resolved is None:
        raise FileNotFoundError(
            f"perseus-vault binary not found on $PATH (looked for {perseus_vault_binary!r}). "
            "Install Perseus Vault from https://github.com/Perseus-Computing-LLC/perseus-vault "
            "(build from source or download a release binary) and ensure it is "
            "on your PATH, or pass the absolute path via perseus_vault_binary=."
        )
    return resolved


def build_stdio_transport(
    db_path: str = "~/.mimir/agent.db",
    *,
    perseus_vault_binary: str = "perseus-vault",
    encryption_key: str | None = None,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
):
    """Build the ``StdioTransport`` that runs ``perseus-vault serve`` for this toolset.

    Exposed separately so callers who want full control (e.g. to pass the
    transport to a plain :class:`~pydantic_ai.mcp.MCPToolset` or a
    ``fastmcp.Client``) can reuse the exact spawn logic.

    Args:
        db_path: Path to the Perseus Vault SQLite database. ``~`` is expanded and
            the parent directory is created if missing.
        perseus_vault_binary: Name or path of the ``perseus-vault`` executable.
        encryption_key: Optional path to an AES-256-GCM key file
            (base64-encoded, 32 bytes). Enables Perseus Vault's at-rest encryption.
        extra_args: Additional CLI args appended to ``perseus-vault serve``.
        env: Extra environment variables for the subprocess (merged over
            ``os.environ``).

    Returns:
        A ``fastmcp.client.transports.StdioTransport`` instance.
    """
    # Imported lazily: fastmcp is only present when pydantic-ai is installed with
    # the `mcp` extra, and importing at module load would break environments that
    # only need the helper symbols for typing.
    from fastmcp.client.transports import StdioTransport

    binary = _resolve_binary(perseus_vault_binary)

    resolved_db = os.path.expanduser(db_path)
    parent = os.path.dirname(resolved_db)
    if parent:
        os.makedirs(parent, exist_ok=True)

    args = ["serve", "--db", resolved_db]
    if encryption_key is not None:
        args += ["--encryption-key", os.path.expanduser(encryption_key)]
    if extra_args:
        args += list(extra_args)

    merged_env: dict[str, str] | None = None
    if env:
        merged_env = {**os.environ, **env}

    return StdioTransport(command=binary, args=args, env=merged_env)


class PerseusVaultToolset(MCPToolset[AgentDepsT]):
    """A Pydantic AI toolset exposing the Perseus Vault memory engine's MCP tools.

    Spawns ``perseus-vault serve --db <db_path>`` as a local stdio MCP server and
    makes all of its memory tools available to the agent. This is a thin wrapper
    over :class:`pydantic_ai.mcp.MCPToolset`; any keyword accepted by
    ``MCPToolset`` (e.g. ``id``, ``include_instructions``, ``process_tool_call``,
    ``max_retries``, ``cache_tools``) may be passed through.

    Example::

        from pydantic_ai import Agent
        from pydantic_ai_perseus_vault import PerseusVaultToolset

        memory = PerseusVaultToolset(db_path="~/.mimir/agent.db")
        agent = Agent("openai:gpt-5", toolsets=[memory])

        async def main():
            async with agent:
                result = await agent.run("Remember that my favourite colour is teal.")
                print(result.output)
    """

    def __init__(
        self,
        db_path: str = "~/.mimir/agent.db",
        *,
        perseus_vault_binary: str = "perseus-vault",
        encryption_key: str | None = None,
        extra_args: list[str] | None = None,
        env: dict[str, str] | None = None,
        **mcp_toolset_kwargs: Any,
    ) -> None:
        """Create a Perseus Vault-backed toolset.

        Args:
            db_path: Path to the Perseus Vault SQLite database. ``~`` is expanded
                and the parent directory is created. Defaults to
                ``~/.mimir/agent.db``.
            perseus_vault_binary: Name or path of the ``perseus-vault``
                executable. A bare name is resolved from ``$PATH``; an explicit
                path is used directly.
            encryption_key: Optional path to an AES-256-GCM key file to enable
                Perseus Vault's at-rest encryption.
            extra_args: Extra CLI args appended to ``perseus-vault serve``.
            env: Extra environment variables for the ``perseus-vault`` subprocess.
            **mcp_toolset_kwargs: Forwarded verbatim to
                :class:`pydantic_ai.mcp.MCPToolset` (e.g. ``id``,
                ``include_instructions``, ``cache_tools``, ``max_retries``).

        Raises:
            FileNotFoundError: If the ``perseus-vault`` binary cannot be located.
        """
        self.db_path = os.path.expanduser(db_path)
        transport = build_stdio_transport(
            db_path,
            perseus_vault_binary=perseus_vault_binary,
            encryption_key=encryption_key,
            extra_args=extra_args,
            env=env,
        )
        super().__init__(transport, **mcp_toolset_kwargs)
