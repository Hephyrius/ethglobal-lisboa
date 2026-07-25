"""curator-mcp — DeFi market data from The Graph, as MCP tools.

A standalone MCP server. It has no dependency on the vault-curation agent that
happens to be its first consumer; any MCP client can install and run it.

    uvx curator-mcp

See README.md for client configuration and SKILL.md for how an agent should
actually use these tools.
"""

from .server import build_server, main

__all__ = ["build_server", "main"]

__version__ = "0.2.0"
