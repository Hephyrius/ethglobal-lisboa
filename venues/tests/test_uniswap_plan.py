"""Offline tests for the Uniswap plan builder.

These replay recorded API responses, so they assert the *translation* — step
ordering, unit conversion, allowlist enforcement — without spending live quota
or depending on market conditions.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from curator_schema.models import ExecutionPlan
from jsonschema import Draft202012Validator

from venues import addresses
from venues.abi import ERC20_APPROVE, PERMIT2_APPROVE, selector
from venues.errors import PlanValidationError
from venues.uniswap.plan import QUOTE_TTL, build_plan, describe, slippage_bps

from .conftest import FIXED_NOW


def _plan(quote_response: dict[str, Any], swap_response: dict[str, Any], **kw) -> ExecutionPlan:
    return build_plan(quote_response, swap_response, now=FIXED_NOW, **kw)


class TestStepOrdering:
    """Approvals must precede the call that needs them, or the plan reverts."""

    def test_emits_three_ordered_steps(self, quote_response, swap_response):
        plan = _plan(quote_response, swap_response)
        assert len(plan.steps) == 3

        # 1. ERC-20 approve on the input token, granting Permit2.
        assert plan.steps[0].target.lower() == addresses.USDC.lower()
        assert plan.steps[0].calldata.startswith("0x" + selector(ERC20_APPROVE).hex())
        assert addresses.PERMIT2[2:].lower() in plan.steps[0].calldata.lower()

        # 2. Permit2 approve, granting the router. Signature-free path: the
        #    vault is a contract and cannot produce an EIP-712 signature.
        assert plan.steps[1].target.lower() == addresses.PERMIT2.lower()
        assert plan.steps[1].calldata.startswith("0x" + selector(PERMIT2_APPROVE).hex())

        # 3. The swap itself, calldata verbatim from the API.
        assert plan.steps[2].target == swap_response["swap"]["to"]
        assert plan.steps[2].calldata == swap_response["swap"]["data"]

    def test_permit2_approval_names_the_router_as_spender(
        self, quote_response, swap_response
    ):
        plan = _plan(quote_response, swap_response)
        router = swap_response["swap"]["to"]
        assert router[2:].lower() in plan.steps[1].calldata.lower()

    def test_approvals_can_be_omitted_for_standing_allowances(
        self, quote_response, swap_response
    ):
        plan = _plan(quote_response, swap_response, include_approvals=False)
        assert len(plan.steps) == 1
        assert plan.steps[0].target == swap_response["swap"]["to"]


class TestAKeylessContractCanExecuteEveryStep:
    """The property the whole Uniswap integration is shaped around.

    The vault is a contract with no private key. The Trading API's documented
    happy path hands back a `permitData` block to be signed as an EIP-712
    `PermitSingle` — which our swapper cannot do, ever. The plan therefore takes
    Permit2's *other* entry point: an ordinary on-chain
    `approve(token, spender, amount, expiration)`.

    Pinned as tests rather than left as a comment because the failure is not
    loud. A plan that smuggled in a signature-dependent step would build fine,
    validate fine, and revert only when the vault tried to execute it — and the
    fix would then look like an execution bug rather than a design mistake.

    Re-verified against the live API 2026-07-25: for a contract swapper the
    quote returns `permitData` populated, `permitTransaction` **null**, and
    `POST /swap` still returns a complete unsigned transaction. See FEEDBACK.md
    §4.
    """

    #: `permit(address,((address,uint160,uint48,uint48),address,uint256),bytes)`
    #: — the signature-consuming Permit2 entry point. Its presence in a plan
    #: would mean the signature-free path had been silently abandoned.
    PERMIT2_PERMIT_WITH_SIGNATURE = "0x2b67b570"

    def test_the_permit2_step_is_the_approve_not_the_signature_entry_point(
        self, quote_response, swap_response
    ):
        plan = _plan(quote_response, swap_response)
        assert plan.steps[1].calldata.startswith("0x" + selector(PERMIT2_APPROVE).hex())
        assert not plan.steps[1].calldata.startswith(self.PERMIT2_PERMIT_WITH_SIGNATURE)

    def test_no_step_anywhere_calls_the_signature_entry_point(
        self, quote_response, swap_response
    ):
        for step in _plan(quote_response, swap_response).steps:
            assert not step.calldata.startswith(self.PERMIT2_PERMIT_WITH_SIGNATURE), (
                f"step targeting {step.target} needs an EIP-712 signature the vault cannot produce"
            )

    def test_the_plan_carries_no_signature_material(self, quote_response, swap_response):
        """A plan is executed by `executeBatch`, which passes only
        (target, value, calldata). There is nowhere for a signature to live, so
        anything the API expected us to sign must have been resolved before
        this point — not carried along in hope."""
        plan = _plan(quote_response, swap_response)
        for step in plan.steps:
            assert set(step.model_dump()) <= {"target", "value", "calldata", "why"}

    def test_the_api_still_offers_a_signature_we_deliberately_ignore(self, quote_response):
        """Guards the *reason* for the workaround, not just the workaround.

        If Uniswap ever populates `permitTransaction`, or stops sending
        `permitData` to contract swappers, this fails and someone re-reads
        FEEDBACK.md §4 instead of carrying a workaround nobody remembers the
        cause of."""
        assert "permitData" in quote_response, (
            "the recorded quote no longer carries permitData - re-check whether "
            "the contract-caller workaround is still necessary (FEEDBACK.md #4)"
        )


class TestUnitConversion:
    """Every one of these is a silent-wrongness bug if it regresses."""

    def test_hex_value_becomes_decimal_string(self, quote_response, swap_response):
        # The API returns value as "0x00"; the schema requires ^[0-9]+$.
        assert swap_response["swap"]["value"].startswith("0x")
        plan = _plan(quote_response, swap_response)
        assert all(step.value.isdigit() for step in plan.steps)
        assert plan.steps[2].value == "0"

    def test_slippage_percent_becomes_basis_points(self, quote_response):
        # API says 2.5 meaning 2.5%; the mandate ceiling is in bps, so 250.
        assert quote_response["quote"]["slippage"] == 2.5
        assert slippage_bps(quote_response["quote"]) == 250

    def test_slippage_absent_is_none_not_zero(self):
        # Zero would read as "no slippage tolerance" and wrongly pass a strict
        # mandate ceiling. Absent must stay absent.
        assert slippage_bps({}) is None

    def test_quote_expiry_is_set_and_short(self, quote_response, swap_response):
        plan = _plan(quote_response, swap_response)
        assert plan.quote_expires_at == FIXED_NOW + QUOTE_TTL
        assert plan.quote_expires_at - FIXED_NOW <= timedelta(minutes=1)


class TestAllowlist:
    def test_all_targets_are_on_the_agreed_allowlist(self, quote_response, swap_response):
        plan = _plan(quote_response, swap_response)
        for step in plan.steps:
            assert step.target.lower() in addresses.allowlist()

    def test_unknown_target_is_rejected_before_it_can_revert_on_chain(
        self, quote_response, swap_response
    ):
        rogue = json.loads(json.dumps(swap_response))
        rogue["swap"]["to"] = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        with pytest.raises(PlanValidationError, match="allowlist"):
            _plan(quote_response, rogue)

    def test_router_address_is_the_one_the_api_actually_returns(self, swap_response):
        # Regression guard for the finding behind cross-lane request 7: the
        # golden fixture's 0x2626664c router is NOT what the API returns.
        assert swap_response["swap"]["to"].lower() == addresses.UNIVERSAL_ROUTER.lower()
        assert (
            addresses.UNIVERSAL_ROUTER.lower()
            != addresses.UNIVERSAL_ROUTER_LEGACY.lower()
        )


class TestSchemaConformance:
    """Validate against the JSON Schema, not just the pydantic mirror — the
    JSON is the source of truth and the two can drift."""

    def test_plan_validates_against_frozen_json_schema(
        self, quote_response, swap_response, repo_root: Path
    ):
        schema = json.loads(
            (repo_root / "packages/schema/execution-plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        plan = _plan(quote_response, swap_response)
        payload = json.loads(plan.model_dump_json(exclude_none=True))
        Draft202012Validator(schema).validate(payload)

    def test_missing_swap_data_fails_loudly(self, quote_response):
        with pytest.raises(PlanValidationError, match="data"):
            _plan(quote_response, {"swap": {"to": addresses.UNIVERSAL_ROUTER}})


class TestErrorClassification:
    """An unroutable trade is an ordinary market condition. Escalating it to a
    hard API error makes the agent look broken when it is merely unable to
    trade right now."""

    @staticmethod
    def _classify(status: int, body: dict):
        import httpx

        from venues.uniswap.client import _api_error

        return _api_error(
            httpx.Response(status, json=body, request=httpx.Request("POST", "http://x"))
        )

    @pytest.mark.parametrize(
        ("status", "body"),
        [
            # Observed live: an unroutable trade returns 404 ResourceNotFound,
            # sharing neither the code nor the phrasing of the documented form.
            (404, {"errorCode": "ResourceNotFound", "detail": "No quotes available"}),
            (404, {"errorCode": "QUOTE_ERROR", "detail": "No route found"}),
            (400, {"errorCode": "SOMETHING", "detail": "insufficient liquidity"}),
        ],
    )
    def test_unroutable_trades_are_not_hard_errors(self, status, body):
        from venues.errors import NoRouteError

        assert isinstance(self._classify(status, body), NoRouteError)

    def test_a_genuine_api_error_stays_a_hard_error(self):
        from venues.errors import NoRouteError, VenueAPIError

        error = self._classify(
            400, {"errorCode": "RequestValidationError", "detail": "bad field"}
        )
        assert isinstance(error, VenueAPIError)
        assert not isinstance(error, NoRouteError)
        assert error.status == 400


class TestDescription:
    def test_describes_the_trade_in_human_units(self, quote_response):
        text = describe(quote_response["quote"])
        assert "USDC" in text and "WETH" in text
        assert text.startswith("swap 1 USDC")  # 1000000 base units, 6 decimals

    def test_degrades_instead_of_raising_on_a_malformed_quote(self):
        assert describe({}) == "swap via Uniswap"
