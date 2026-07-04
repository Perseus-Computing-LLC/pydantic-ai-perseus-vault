"""Tests for ``pydantic_ai_perseus_vault``.

The unit tests mock binary resolution and the ``StdioTransport`` so they run
with no ``perseus-vault`` binary present and never spawn a subprocess. A real,
end-to-end smoke test is included but skipped automatically when the
``perseus-vault`` binary is not on ``$PATH``.
"""

from __future__ import annotations

import os
import shutil

import pytest

import pydantic_ai_perseus_vault.toolset as toolset_mod
from pydantic_ai_perseus_vault import PerseusVaultToolset, build_stdio_transport
from pydantic_ai.mcp import MCPToolset


# ── Test doubles ─────────────────────────────────────────────────────────────


class FakeStdioTransport:
    """Records the args PerseusVaultToolset would spawn ``perseus-vault serve`` with."""

    def __init__(self, command, args, env=None):
        self.command = command
        self.args = args
        self.env = env


@pytest.fixture
def fake_transport(monkeypatch):
    """Patch ``fastmcp.client.transports.StdioTransport`` with a recorder.

    ``build_stdio_transport`` imports the symbol lazily from that module, so we
    patch it at the source module to intercept the import.
    """
    import fastmcp.client.transports as transports

    monkeypatch.setattr(transports, "StdioTransport", FakeStdioTransport)
    return FakeStdioTransport


@pytest.fixture
def fake_binary(monkeypatch, tmp_path):
    """Make ``shutil.which('perseus-vault')`` resolve to a fake on-PATH binary."""
    fake = tmp_path / "perseus-vault"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setattr(
        toolset_mod.shutil,
        "which",
        lambda name: str(fake) if name == "perseus-vault" else shutil.which(name),
    )
    return str(fake)


# ── Binary resolution ────────────────────────────────────────────────────────


def test_resolve_binary_from_path(fake_binary):
    assert toolset_mod._resolve_binary("perseus-vault") == fake_binary


def test_resolve_binary_missing_raises():
    with pytest.raises(FileNotFoundError, match="not found on .PATH"):
        toolset_mod._resolve_binary("definitely-not-a-real-binary-xyz")


def test_resolve_binary_explicit_path_missing_raises(tmp_path):
    missing = str(tmp_path / "nope" / "perseus-vault")
    with pytest.raises(FileNotFoundError, match="not found at"):
        toolset_mod._resolve_binary(missing)


def test_resolve_binary_explicit_path_ok(tmp_path):
    real = tmp_path / "custom-perseus-vault"
    real.write_text("x")
    assert toolset_mod._resolve_binary(str(real)) == str(real)


# ── build_stdio_transport ────────────────────────────────────────────────────


def test_transport_serve_invocation(fake_transport, fake_binary, tmp_path):
    db = tmp_path / "memdir" / "agent.db"
    t = build_stdio_transport(str(db))
    assert t.command == fake_binary
    assert t.args == ["serve", "--db", str(db)]
    # Parent directory is created.
    assert (tmp_path / "memdir").is_dir()


def test_transport_expands_home(fake_transport, fake_binary):
    t = build_stdio_transport("~/.mimir/agent.db")
    db_arg = t.args[t.args.index("--db") + 1]
    assert "~" not in db_arg
    assert db_arg == os.path.expanduser("~/.mimir/agent.db")


def test_transport_encryption_key(fake_transport, fake_binary, tmp_path):
    db = tmp_path / "agent.db"
    t = build_stdio_transport(str(db), encryption_key="/keys/perseus-vault.key")
    assert "--encryption-key" in t.args
    assert t.args[t.args.index("--encryption-key") + 1] == os.path.expanduser(
        "/keys/perseus-vault.key"
    )


def test_transport_extra_args(fake_transport, fake_binary, tmp_path):
    db = tmp_path / "agent.db"
    t = build_stdio_transport(str(db), extra_args=["--web", "--port", "9000"])
    assert t.args[-3:] == ["--web", "--port", "9000"]


def test_transport_env_merged(fake_transport, fake_binary, tmp_path, monkeypatch):
    monkeypatch.setenv("PRE_EXISTING", "1")
    db = tmp_path / "agent.db"
    t = build_stdio_transport(str(db), env={"PERSEUS_VAULT_EXTRA": "x"})
    assert t.env["PERSEUS_VAULT_EXTRA"] == "x"
    assert t.env["PRE_EXISTING"] == "1"  # merged over os.environ


def test_transport_no_env_is_none(fake_transport, fake_binary, tmp_path):
    db = tmp_path / "agent.db"
    t = build_stdio_transport(str(db))
    assert t.env is None


# ── PerseusVaultToolset ──────────────────────────────────────────────────────


# These build a *real* MCPToolset (the binary is a real file, but
# StdioTransport does not spawn it until the toolset is entered as an async
# context manager — so construction stays subprocess-free).


def test_toolset_is_mcp_toolset(fake_binary, tmp_path):
    ts = PerseusVaultToolset(db_path=str(tmp_path / "agent.db"))
    assert isinstance(ts, MCPToolset)


def test_toolset_records_db_path(fake_binary, tmp_path):
    db = tmp_path / "agent.db"
    ts = PerseusVaultToolset(db_path=str(db))
    assert ts.db_path == str(db)


def test_toolset_missing_binary_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(toolset_mod.shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError):
        PerseusVaultToolset(db_path=str(tmp_path / "agent.db"))


def test_toolset_forwards_mcp_kwargs(fake_binary, tmp_path):
    # `id` is a recognised MCPToolset kwarg; passing it must not error and must
    # be applied to the underlying toolset.
    ts = PerseusVaultToolset(db_path=str(tmp_path / "agent.db"), id="perseus-vault-memory")
    assert ts.id == "perseus-vault-memory"


# ── Real smoke test (skipped without the binary) ─────────────────────────────


# The smoke test uses $PERSEUS_VAULT_BINARY if set, otherwise a `perseus-vault`
# on $PATH. Perseus Vault still serves its MCP tools under the historical
# ``mimir_*`` prefix (preserved for backward compatibility), so the tool-name
# assertions below intentionally check for ``mimir_*`` names.
_PV_BINARY = os.environ.get("PERSEUS_VAULT_BINARY") or shutil.which("perseus-vault")


@pytest.mark.skipif(
    _PV_BINARY is None,
    reason="no perseus-vault binary ($PERSEUS_VAULT_BINARY unset and none on $PATH)",
)
async def test_smoke_real_perseus_vault_lists_tools(tmp_path):
    """Spawn the real ``perseus-vault serve`` and confirm its memory tools load.

    Exercises the full path: binary resolution -> StdioTransport ->
    MCPToolset -> MCP initialize handshake -> tools/list.
    """
    ts = PerseusVaultToolset(
        db_path=str(tmp_path / "smoke.db"), perseus_vault_binary=_PV_BINARY
    )
    async with ts:
        # The underlying FastMCP client performs the real MCP tools/list call.
        tools = await ts.client.list_tools()
        names = {t.name for t in tools}
        assert any(n.startswith("mimir_") for n in names), names
        assert "mimir_remember" in names
        assert "mimir_recall" in names


@pytest.mark.skipif(
    _PV_BINARY is None,
    reason="no perseus-vault binary ($PERSEUS_VAULT_BINARY unset and none on $PATH)",
)
async def test_smoke_real_agent_remembers_and_recalls(tmp_path):
    """Full round-trip through a real Pydantic AI Agent over the live MCP link.

    A FunctionModel drives the conversation deterministically: first turn calls
    ``mimir_remember`` with a real fact, second turn calls ``mimir_recall``,
    third turn returns the recalled text. This proves the agent discovers,
    invokes, and gets real results from Perseus Vault's tools — and that the
    fact actually persisted and was retrieved."""
    import json

    from pydantic_ai import Agent
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        ToolCallPart,
    )
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    fact = "The launch code is teal-griffin-42."

    def model(messages, info: AgentInfo) -> ModelResponse:
        # Count tool-return messages already seen to decide the next step.
        returns = [
            p
            for m in messages
            if isinstance(m, ModelRequest)
            for p in m.parts
            if p.part_kind == "tool-return"
        ]
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "mimir_remember",
                        {
                            "category": "smoke",
                            "key": "launch-code",
                            "body_json": json.dumps({"text": fact}),
                            "tags": ["test"],
                        },
                    )
                ]
            )
        if len(returns) == 1:
            return ModelResponse(
                parts=[ToolCallPart("mimir_recall", {"query": "launch code", "limit": 5})]
            )
        # Surface the recall result so the test can assert persistence.
        return ModelResponse(parts=[TextPart(str(returns[-1].content))])

    ts = PerseusVaultToolset(
        db_path=str(tmp_path / "agent.db"), perseus_vault_binary=_PV_BINARY
    )
    agent = Agent(FunctionModel(model), toolsets=[ts])
    async with agent:
        result = await agent.run("Remember the launch code, then recall it.")

    # The recalled payload must contain the fact we stored a turn earlier.
    assert "teal-griffin-42" in result.output
