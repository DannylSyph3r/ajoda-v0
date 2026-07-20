"""
MonnifyProvider — the prototype's single PaymentProvider implementation.

Phase 1 implements OAuth2 auth (cached) + collections (initialize, verify) and
the collection-webhook signature check. Disbursement methods are declared on the
interface but raise NotImplementedException until Phase 3.

All outbound HTTP follows the base convention: a per-call httpx.AsyncClient with
an explicit timeout, no shared/pooled client (see CLAUDE §8). OAuth2 token
caching is layered on top with an asyncio.Lock so concurrent callers don't
stampede the auth endpoint (single-worker in-process cache, like the base's
Gemini singleton).
"""
import asyncio
import base64
import hashlib
import hmac
import logging
import time
from decimal import ROUND_HALF_UP, Decimal

import httpx

from app.core.config import get_settings
from app.core.exceptions import InternalServerException, NotImplementedException
from app.services.payment_provider import PaymentProvider

settings = get_settings()
logger = logging.getLogger("akoweai")

_TIMEOUT = 20.0  # seconds — Monnify init/verify are fast; generous ceiling
_TOKEN_SKEW = 60  # refresh this many seconds before the token actually expires

# In-process OAuth2 token cache (single worker). Guarded by _token_lock so only
# one coroutine fetches a fresh token at a time.
_token_state: dict = {"token": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()


def _kobo_to_naira(amount_kobo: int) -> float:
    """Monnify amounts are in naira (major units). Convert without float drift."""
    return float((Decimal(amount_kobo) / 100).quantize(Decimal("0.01")))


def _naira_to_kobo(amount_naira) -> int:
    """Convert a Monnify naira amount back to our internal kobo integer."""
    return int((Decimal(str(amount_naira)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def verify_monnify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    Verify Monnify's `monnify-signature` header.

    Monnify signs webhooks with HMAC-SHA512 over the raw request body, keyed with
    the account's Secret Key (there is no separate webhook-signing secret). We hash
    the exact raw bytes received — never a re-serialization — so Monnify's own body
    formatting cannot desync the comparison. Fails closed if the Secret Key is not
    configured or the signature is absent.

    Scheme confirmed against the docs' worked sample (client key
    91MUDL9N6U3BQRXBQ2PJ9M0PW4J22M1Y + the sample body reproduces the documented
    hash only under HMAC-SHA512, not the plain "SHA512(secret + body)" concat the
    prose describes). Trust HMAC-SHA512.
    """
    if not settings.monnify_secret_key:
        logger.error("MONNIFY_SECRET_KEY is not configured — rejecting webhook request")
        return False
    if not signature_header:
        return False
    expected = hmac.new(
        settings.monnify_secret_key.encode(),
        raw_body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


class MonnifyProvider(PaymentProvider):
    def __init__(self) -> None:
        self.base_url = settings.monnify_base_url.rstrip("/")
        self.contract_code = settings.monnify_contract_code

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #
    async def _get_token(self) -> str:
        """Return a valid access token, refreshing via the auth endpoint on expiry."""
        now = time.time()
        token = _token_state["token"]
        if token and now < _token_state["expires_at"]:
            return token

        async with _token_lock:
            # Re-check inside the lock — another coroutine may have refreshed it.
            now = time.time()
            token = _token_state["token"]
            if token and now < _token_state["expires_at"]:
                return token

            if not settings.monnify_api_key or not settings.monnify_secret_key:
                raise InternalServerException("Monnify API credentials are not configured")

            basic = base64.b64encode(
                f"{settings.monnify_api_key}:{settings.monnify_secret_key}".encode()
            ).decode()
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.post(
                        f"{self.base_url}/api/v1/auth/login",
                        headers={
                            "Authorization": f"Basic {basic}",
                            "Content-Type": "application/json",
                        },
                    )
                    resp.raise_for_status()
                    body = resp.json()
            except Exception:
                logger.exception("Monnify auth request failed")
                raise InternalServerException("Could not authenticate with the payment provider")

            if not body.get("requestSuccessful"):
                logger.error("Monnify auth rejected: %s", body.get("responseMessage"))
                raise InternalServerException("Payment provider authentication was rejected")

            rb = body.get("responseBody", {})
            access_token = rb.get("accessToken")
            expires_in = int(rb.get("expiresIn", 0) or 0)
            if not access_token:
                raise InternalServerException("Payment provider returned no access token")

            _token_state["token"] = access_token
            _token_state["expires_at"] = time.time() + max(expires_in - _TOKEN_SKEW, 0)
            return access_token

    async def _authed_headers(self) -> dict:
        return {"Authorization": f"Bearer {await self._get_token()}"}

    # ------------------------------------------------------------------ #
    # Collections
    # ------------------------------------------------------------------ #
    async def initialize_transaction(
        self,
        *,
        reference: str,
        amount_kobo: int,
        customer_name: str,
        customer_email: str,
        redirect_url: str,
    ) -> dict:
        payload = {
            "amount": _kobo_to_naira(amount_kobo),
            "customerName": customer_name,
            "customerEmail": customer_email,
            "paymentReference": reference,
            "paymentDescription": "Cooperative contribution",
            "currencyCode": "NGN",
            "contractCode": self.contract_code,
            "redirectUrl": redirect_url,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/merchant/transactions/init-transaction",
                    headers=await self._authed_headers(),
                    json=payload,
                )
                resp.raise_for_status()
                body = resp.json()
        except InternalServerException:
            raise
        except Exception:
            logger.exception("Monnify initialize_transaction failed for ref=%s", reference)
            raise InternalServerException("Could not start the payment with the provider")

        if not body.get("requestSuccessful"):
            logger.error(
                "Monnify init rejected for ref=%s: %s", reference, body.get("responseMessage")
            )
            raise InternalServerException("The payment provider rejected the transaction")

        rb = body.get("responseBody", {})
        checkout_url = rb.get("checkoutUrl")
        if not checkout_url:
            raise InternalServerException("The payment provider returned no checkout URL")
        return {
            "checkout_url": checkout_url,
            "transaction_reference": rb.get("transactionReference", ""),
        }

    async def verify_transaction(self, reference: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v2/merchant/transactions/query",
                    headers=await self._authed_headers(),
                    params={"paymentReference": reference},
                )
                resp.raise_for_status()
                body = resp.json()
        except InternalServerException:
            raise
        except Exception:
            logger.exception("Monnify verify_transaction failed for ref=%s", reference)
            raise InternalServerException("Could not verify the payment with the provider")

        if not body.get("requestSuccessful"):
            logger.error(
                "Monnify verify rejected for ref=%s: %s", reference, body.get("responseMessage")
            )
            raise InternalServerException("The payment provider could not verify the transaction")

        rb = body.get("responseBody", {})
        amount_paid = rb.get("amountPaid", 0) or 0
        return {
            "status": rb.get("paymentStatus", ""),
            "amount_kobo": _naira_to_kobo(amount_paid),
            "raw": rb,
        }

    # ------------------------------------------------------------------ #
    # Disbursement (Phase 3)
    # ------------------------------------------------------------------ #
    async def get_banks(self) -> list[dict]:
        raise NotImplementedException("Disbursement (get_banks) is implemented in Phase 3")

    async def name_enquiry(self, account_number: str, bank_code: str) -> dict:
        raise NotImplementedException("Disbursement (name_enquiry) is implemented in Phase 3")

    async def wallet_balance(self) -> dict:
        raise NotImplementedException("Disbursement (wallet_balance) is implemented in Phase 3")

    async def initiate_transfer(
        self,
        *,
        reference: str,
        amount_kobo: int,
        bank_code: str,
        account_number: str,
        account_name: str,
        narration: str,
    ) -> dict:
        raise NotImplementedException("Disbursement (initiate_transfer) is implemented in Phase 3")

    async def authorize_transfer(self, reference: str, otp: str) -> dict:
        raise NotImplementedException("Disbursement (authorize_transfer) is implemented in Phase 3")
