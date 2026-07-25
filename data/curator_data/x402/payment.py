"""Building and signing an x402 payment payload.

The `exact` scheme over an EIP-3009 stablecoin: the server answers a request
with `402 Payment Required` and a JSON body describing what it wants; the
client signs a `TransferWithAuthorization` and retries with an `X-PAYMENT`
header carrying the signed authorization, base64-encoded.

Signing an authorization is not spending — it authorises the facilitator to
pull exactly `value` once, before `validBefore`, with a nonce that cannot be
replayed. Still, this is a real key signing a real transfer, so the safety
rails here are deliberate:

  * **A maximum we are willing to pay**, enforced client-side. A malicious or
    misconfigured gateway asking for 500 USDC per query gets refused rather
    than signed. Queries cost fractions of a cent, so the ceiling is generous
    and still catches anything alarming.
  * **A short validity window**, so an unused authorization expires quickly.
  * **A random 32-byte nonce** per payment.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

#: Refuse to sign anything above this, in atomic units of the asset. USDC has
#: 6 decimals, so this is 1.00 USDC — several thousand times a real query
#: price. A request above it means something is wrong, not that data got
#: expensive.
MAX_PAYMENT_ATOMIC = 1_000_000

#: EIP-3009. The type the stablecoin's `transferWithAuthorization` verifies.
TRANSFER_WITH_AUTHORIZATION_TYPES = {
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ]
}

CHAIN_IDS = {"base": 8453, "base-sepolia": 84532}

#: The Graph's gateway announces networks in CAIP-2 form (`eip155:8453`) rather
#: than by name. Both are accepted so the parser survives either spelling.
def chain_id_for(network: str) -> int | None:
    """Chain id for a network name or CAIP-2 identifier."""
    name = (network or "").strip().lower()
    if name in CHAIN_IDS:
        return CHAIN_IDS[name]
    if name.startswith("eip155:"):
        try:
            return int(name.split(":", 1)[1])
        except ValueError:
            return None
    return None


class PaymentError(RuntimeError):
    """Payment could not be constructed or signed. Always recoverable —
    the caller falls back to the API-key path."""


@dataclass(frozen=True)
class PaymentRequirements:
    """The server's terms, parsed out of a 402 body."""

    scheme: str
    network: str
    max_amount_required: int
    pay_to: str
    asset: str
    resource: str
    max_timeout_seconds: int = 60
    #: EIP-712 domain details for the asset contract (`name`, `version`).
    extra: dict[str, Any] | None = None
    x402_version: int = 1
    #: The offer exactly as the server sent it. v2 requires echoing it back
    #: under `accepted`, and reconstructing it from parsed fields risks a
    #: mismatch on anything we did not model.
    raw_offer: dict[str, Any] | None = None
    #: The `resource` object from a v2 402, echoed back unchanged.
    raw_resource: dict[str, Any] | None = None

    @classmethod
    def from_header(cls, header_value: str) -> PaymentRequirements:
        """Parse the base64 `payment-required` response header.

        This is how The Graph's gateway actually states its terms — verified
        live 2026-07-25. The 402 arrives with an **empty body** and everything
        in this header, which is why body-only parsing silently fell back on
        every request.
        """
        if not header_value:
            raise PaymentError("empty payment-required header")
        padded = header_value.strip() + "=" * (-len(header_value.strip()) % 4)
        try:
            decoded = base64.b64decode(padded)
            return cls.from_response(json.loads(decoded))
        except PaymentError:
            raise
        except Exception as exc:  # noqa: BLE001 - any decode failure is a fallback
            raise PaymentError(f"unreadable payment-required header: {exc}") from exc

    @classmethod
    def from_response(cls, body: dict[str, Any]) -> PaymentRequirements:
        """Parse decoded 402 terms, preferring an `exact` offer we can pay.

        `accepts` is a list because a server may support several schemes and
        networks. We take the first `exact` offer; if there is none we raise
        and the caller falls back.

        Field names differ across x402 versions and both are accepted: v1 calls
        the price `maxAmountRequired`, the gateway's v2 calls it `amount`.
        """
        offers = body.get("accepts") or []
        if not offers:
            raise PaymentError("402 terms contained no payment options")

        exact = [o for o in offers if str(o.get("scheme", "")).lower() == "exact"]
        if not exact:
            schemes = sorted({str(o.get("scheme")) for o in offers})
            raise PaymentError(f"no 'exact' scheme offered (got: {', '.join(schemes)})")

        offer = exact[0]
        raw_amount = offer.get("amount", offer.get("maxAmountRequired"))
        try:
            amount = int(raw_amount)
        except (TypeError, ValueError) as exc:
            raise PaymentError(f"unreadable payment amount: {raw_amount!r}") from exc

        resource = offer.get("resource")
        if not resource:
            # v2 moves the resource up next to the offers.
            resource = (body.get("resource") or {}).get("url", "")

        return cls(
            scheme="exact",
            network=str(offer.get("network") or "base"),
            max_amount_required=amount,
            pay_to=str(offer.get("payTo") or ""),
            asset=str(offer.get("asset") or ""),
            resource=str(resource or ""),
            max_timeout_seconds=int(offer.get("maxTimeoutSeconds") or 60),
            extra=offer.get("extra") or {},
            x402_version=int(body.get("x402Version") or 1),
            raw_offer=dict(offer),
            raw_resource=body.get("resource") if isinstance(body.get("resource"), dict) else None,
        )

    def validate(self, *, max_atomic: int = MAX_PAYMENT_ATOMIC) -> None:
        """Refuse anything we should not sign. Raises `PaymentError`."""
        if not self.pay_to or not self.asset:
            raise PaymentError("402 offer is missing payTo or asset")
        if self.max_amount_required <= 0:
            raise PaymentError(f"nonsensical payment amount: {self.max_amount_required}")
        if self.max_amount_required > max_atomic:
            raise PaymentError(
                f"refusing to sign {self.max_amount_required} atomic units - above the "
                f"{max_atomic} ceiling. A market-data query should cost a fraction of a cent."
            )
        if chain_id_for(self.network) is None:
            raise PaymentError(f"unsupported network '{self.network}'")

    @property
    def chain_id(self) -> int:
        resolved = chain_id_for(self.network)
        if resolved is None:
            raise PaymentError(f"unsupported network '{self.network}'")
        return resolved


def build_payment_header(
    requirements: PaymentRequirements,
    private_key: str,
    *,
    max_atomic: int = MAX_PAYMENT_ATOMIC,
    now: int | None = None,
) -> str:
    """Sign the authorization and return the `X-PAYMENT` header value.

    Raises `PaymentError` for anything that should stop us paying. Every raise
    here is caught by the client and turned into a fallback, so refusing is
    always safe.
    """
    requirements.validate(max_atomic=max_atomic)

    try:
        from eth_account import Account
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise PaymentError(
            "eth-account is not installed - `pip install curator-data[x402]`"
        ) from exc

    try:
        account = Account.from_key(private_key)
    except Exception as exc:  # noqa: BLE001 - any key problem is a fallback
        raise PaymentError(f"could not load X402_PRIVATE_KEY: {type(exc).__name__}") from exc

    issued = int(time.time()) if now is None else now
    authorization = {
        # `from` is a Python keyword, so this dict is built literally rather
        # than with kwargs.
        "from": account.address,
        "to": requirements.pay_to,
        "value": str(requirements.max_amount_required),
        # A minute of backdating absorbs clock skew between us and the
        # facilitator; without it a correct signature can be rejected as
        # not-yet-valid.
        "validAfter": str(issued - 60),
        "validBefore": str(issued + max(requirements.max_timeout_seconds, 60)),
        "nonce": "0x" + secrets.token_bytes(32).hex(),
    }

    extra = requirements.extra or {}
    domain = {
        # Defaults match USDC, which is what the gateway prices in; a
        # conforming 402 body supplies both explicitly.
        "name": str(extra.get("name") or "USD Coin"),
        "version": str(extra.get("version") or "2"),
        "chainId": requirements.chain_id,
        "verifyingContract": requirements.asset,
    }

    try:
        signed = Account.sign_typed_data(
            private_key,
            domain_data=domain,
            message_types=TRANSFER_WITH_AUTHORIZATION_TYPES,
            message_data={
                **authorization,
                "value": int(authorization["value"]),
                "validAfter": int(authorization["validAfter"]),
                "validBefore": int(authorization["validBefore"]),
                "nonce": bytes.fromhex(authorization["nonce"][2:]),
            },
        )
    except Exception as exc:  # noqa: BLE001 - signing failure must fall back
        raise PaymentError(f"signing failed: {type(exc).__name__}: {exc}") from exc

    raw_signature = str(signed.signature.hex())
    signature = raw_signature if raw_signature.startswith("0x") else "0x" + raw_signature
    signed_payload = {"signature": signature, "authorization": authorization}

    # v1 and v2 wrap the same signed authorization differently. v2 echoes the
    # accepted offer and the resource back to the server instead of restating
    # scheme/network at the top level.
    if requirements.x402_version >= 2:
        payload: dict[str, Any] = {
            "x402Version": requirements.x402_version,
            "accepted": requirements.raw_offer
            or {
                "scheme": requirements.scheme,
                "network": requirements.network,
                "amount": str(requirements.max_amount_required),
                "asset": requirements.asset,
                "payTo": requirements.pay_to,
                "maxTimeoutSeconds": requirements.max_timeout_seconds,
                "extra": extra,
            },
            "payload": signed_payload,
            "extensions": {},
        }
        if requirements.raw_resource:
            payload["resource"] = requirements.raw_resource
        elif requirements.resource:
            payload["resource"] = {"url": requirements.resource}
    else:
        payload = {
            "x402Version": requirements.x402_version,
            "scheme": requirements.scheme,
            "network": requirements.network,
            "payload": signed_payload,
        }

    return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


__all__ = [
    "PaymentRequirements",
    "PaymentError",
    "build_payment_header",
    "MAX_PAYMENT_ATOMIC",
    "TRANSFER_WITH_AUTHORIZATION_TYPES",
]
