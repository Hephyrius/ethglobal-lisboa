"""Reading data straight off a chain.

Every other source in this package speaks HTTP to somebody's API. This one
speaks JSON-RPC to a node, which is the point: the `DataSource` port abstracts
*kinds of provider*, not just endpoints. A source that reads a contract and a
source that queries a subgraph merge into the same `MarketSnapshot` without
either knowing the other exists.
"""

from .rpc import RpcClient, RpcError

__all__ = ["RpcClient", "RpcError"]
