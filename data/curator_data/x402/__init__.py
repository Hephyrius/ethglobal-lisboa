"""x402 — the agent paying for its own market data, out of its own wallet.

The narrative beat: an autonomous curator that funds its own information. Also
hand-rolled EIP-712 signing against a spec we cannot rehearse before the demo,
which is a bad combination with a deadline.

So it is built as a **decorator over the ordinary gateway transport**, never as
a data source:

    GatewayClient          API-key auth. Always works. The default.
    X402GatewayClient      wraps it. Tries to pay; on ANY failure delegates
                           to the wrapped client and records why.

That shape is the risk control. There is no code path where enabling x402 can
lose data that the API-key path would have returned — the worst case is one
wasted round-trip and a note in `MarketSnapshot.errors`. It is off unless
`X402_ENABLED=true` *and* a signing key is present.

`eth-account` is an optional dependency (`pip install curator-data[x402]`) and
is imported lazily, so nobody who just wants to read a yield pays for a
signing stack.
"""

from .client import X402GatewayClient
from .payment import PaymentRequirements, build_payment_header

__all__ = ["X402GatewayClient", "PaymentRequirements", "build_payment_header"]
