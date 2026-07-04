# pydantic-ai-perseus-vault

Persistent, local-first, **encrypted** memory for [Pydantic AI](https://ai.pydantic.dev)
agents — backed by [Perseus Vault](https://github.com/Perseus-Computing-LLC/perseus-vault) (formerly "Mimir"/"Mneme").

`PerseusVaultToolset` gives a Pydantic AI `Agent` durable memory that survives across
runs and processes. Your agent can `mimir_remember` facts and `mimir_recall`
them later, with full-text + semantic search, all stored in a local SQLite
database that never leaves the machine (and can be AES-256-GCM encrypted at
rest).

> **Tool names.** Perseus Vault still exposes its MCP tools under the historical
> `mimir_*` prefix (`mimir_remember`, `mimir_recall`, ...), preserved for
> backward compatibility — that is why the tool names below start with `mimir_`.

## Why this package?

Pydantic AI already speaks the Model Context Protocol natively via
[`MCPToolset`](https://ai.pydantic.dev/mcp/client/), and Perseus Vault is an MCP stdio
server — so you *could* wire them together by hand. `PerseusVaultToolset` is the
ergonomic shortcut: it subclasses `MCPToolset`, resolves the `perseus-vault` binary,
manages the database path, optionally enables encryption, and spawns
`perseus-vault serve` for you. One line instead of a transport assembly. Because it
*is* an `MCPToolset`, every Pydantic AI MCP feature (tool caching,
`include_instructions`, `process_tool_call`, tool filtering/renaming) works
unchanged.

## Prerequisite: the `perseus-vault` binary

Perseus Vault is a single self-contained binary. Install it and make sure it is on your
`PATH`:

```bash
# One-line install (installs to ~/.local/bin/perseus-vault):
curl -sSf https://raw.githubusercontent.com/Perseus-Computing-LLC/perseus-vault/main/scripts/install.sh | sh

# ...or build from source (Rust toolchain required):
git clone https://github.com/Perseus-Computing-LLC/perseus-vault
cd perseus-vault && cargo build --release
# then put target/release/perseus-vault on your PATH

# ...or download a prebuilt binary from the releases page:
#   https://github.com/Perseus-Computing-LLC/perseus-vault/releases
```

Verify:

```bash
perseus-vault --version
```

## Install

```bash
pip install pydantic-ai-perseus-vault
```

This pulls in `pydantic-ai-slim[mcp]`. If you already use the full
`pydantic-ai`, that satisfies the dependency too.

## Usage

```python
import asyncio

from pydantic_ai import Agent
from pydantic_ai_perseus_vault import PerseusVaultToolset

# Spawns `perseus-vault serve --db ~/.mimir/agent.db` and exposes its memory tools.
memory = PerseusVaultToolset(db_path="~/.mimir/agent.db")

agent = Agent(
    "openai:gpt-5",
    toolsets=[memory],
    instructions=(
        "You have a persistent memory. Use mimir_remember to store durable "
        "facts about the user, and mimir_recall to look them up before "
        "answering."
    ),
)


async def main() -> None:
    async with agent:  # opens the MCP connection for the agent's lifetime
        await agent.run("My favourite colour is teal. Please remember that.")
        result = await agent.run("What's my favourite colour?")
        print(result.output)  # -> teal


asyncio.run(main())
```

### Encryption at rest

```python
memory = PerseusVaultToolset(
    db_path="~/.mimir/agent.db",
    encryption_key="~/.mimir/key.b64",  # base64-encoded 32-byte AES-256-GCM key
)
```

### Custom binary location

```python
memory = PerseusVaultToolset(
    db_path="~/.mimir/agent.db",
    perseus_vault_binary="/opt/perseus-vault/bin/perseus-vault",  # explicit path; otherwise resolved from PATH
)
```

### Passing through `MCPToolset` options

Any `MCPToolset` keyword is forwarded:

```python
memory = PerseusVaultToolset(
    db_path="~/.mimir/agent.db",
    id="perseus-vault-memory",  # stable id (needed for Temporal/DBOS durability)
    include_instructions=True,  # inject Perseus Vault's server instructions into the agent
    cache_tools=True,
)
```

## What tools does the agent get?

All of Perseus Vault's MCP tools (exposed under the `mimir_*` prefix), including:

| Tool | Purpose |
| --- | --- |
| `mimir_remember` | Store a durable memory (category, key, body, tags) |
| `mimir_recall` | Hybrid full-text + semantic search over memories |
| `mimir_get_entity` | Fetch a specific memory by id/key |
| `mimir_timeline` | Time-ordered view of memories |
| `mimir_forget` / `mimir_supersede` | Delete or replace memories |
| `mimir_link` / `mimir_traverse` | Relate and walk between memories |
| ... | and many more (stats, journaling, vault import/export, etc.) |

The exact set depends on your installed Perseus Vault version.

## Development

```bash
pip install -e ".[test]"
pytest
```

The unit tests mock the subprocess and run with no `perseus-vault` binary installed. A
real end-to-end smoke test runs automatically when a `perseus-vault` binary is on
`PATH`, and is skipped otherwise.

## License

MIT © 2026 Perseus Computing LLC
