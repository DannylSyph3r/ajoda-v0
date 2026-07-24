"""
MonnifyProvider — the prototype's single PaymentProvider implementation.

Phase 1 implements OAuth2 auth (cached) + collections (initialize, verify) and
the collection-webhook signature check. Phase 3 adds disbursement: get banks
(cached), name enquiry, wallet balance, initiate single transfer (async), authorize
transfer (OTP), and transfer-status poll.

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
from app.core.exceptions import BadRequestException, InternalServerException
from app.services.payment_provider import PaymentProvider

settings = get_settings()
logger = logging.getLogger("akoweai")

_TIMEOUT = 20.0  # seconds — Monnify init/verify are fast; generous ceiling
_TOKEN_SKEW = 60  # refresh this many seconds before the token actually expires

# In-process OAuth2 token cache (single worker). Guarded by _token_lock so only
# one coroutine fetches a fresh token at a time.
_token_state: dict = {"token": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()

# In-process cache for the bank list (effectively static).
_banks_cache: dict = {"banks": None}
_banks_lock = asyncio.Lock()


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
            # Monnify's own transaction reference — distinct from the
            # paymentReference we generated, and the value refunds must be
            # initiated against (see initiate_refund).
            "transaction_reference": rb.get("transactionReference", ""),
            "raw": rb,
        }

    # ------------------------------------------------------------------ #
    # Disbursement (Phase 3)
    # ------------------------------------------------------------------ #
    async def _call(
        self, method: str, url: str, action: str, *, params=None, json=None
    ) -> dict:
        """
        Low-level authed request. Raises InternalServerException on transport/parse
        errors but does NOT raise on a 4xx — the caller inspects `requestSuccessful`
        / `responseMessage` so validation failures (e.g. an invalid account) can be
        surfaced as clean user-facing messages rather than opaque 500s.
        """
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.request(
                    method,
                    url,
                    headers=await self._authed_headers(),
                    params=params,
                    json=json,
                )
        except InternalServerException:
            raise
        except Exception:
            logger.exception("Monnify %s transport error", action)
            raise InternalServerException(
                f"Could not reach the payment provider to {action}"
            )
        try:
            return resp.json()
        except Exception:
            logger.error("Monnify %s returned non-JSON (HTTP %s)", action, resp.status_code)
            raise InternalServerException(
                f"The payment provider returned an invalid response for {action}"
            )

    async def get_banks(self) -> list[dict]:
        if _banks_cache["banks"] is not None:
            return _banks_cache["banks"]
        async with _banks_lock:
            if _banks_cache["banks"] is not None:
                return _banks_cache["banks"]
            body = await self._call("GET", f"{self.base_url}/api/v1/banks", "list banks")
            if not body.get("requestSuccessful"):
                logger.error("Monnify get-banks rejected: %s", body.get("responseMessage"))
                raise InternalServerException("Could not retrieve the bank list")
            banks = [
                {"code": b.get("code"), "name": b.get("name")}
                for b in (body.get("responseBody") or [])
                if b.get("code")
            ]
            _banks_cache["banks"] = banks
            return banks

    async def name_enquiry(self, account_number: str, bank_code: str) -> dict:
        body = await self._call(
            "GET",
            f"{self.base_url}/api/v2/disbursements/account/validate",
            "validate account",
            params={"accountNumber": account_number, "bankCode": bank_code},
        )
        if not body.get("requestSuccessful"):
            # 404 / validation failure — a user-facing "bad account", not a 500.
            raise BadRequestException(
                body.get("responseMessage")
                or "Could not verify that account. Check the number and bank."
            )
        rb = body.get("responseBody") or {}
        name = rb.get("accountName")
        if not name:
            raise BadRequestException(
                "The account name could not be resolved for that account."
            )
        return {
            "account_name": name,
            "account_number": rb.get("accountNumber", account_number),
            "bank_code": rb.get("bankCode", bank_code),
        }

    async def wallet_balance(self) -> dict:
        body = await self._call(
            "GET",
            f"{self.base_url}/api/v2/disbursements/wallet-balance",
            "fetch wallet balance",
            params={"accountNumber": settings.monnify_wallet_account_number},
        )
        if not body.get("requestSuccessful"):
            logger.error("Monnify wallet-balance rejected: %s", body.get("responseMessage"))
            raise InternalServerException("Could not fetch the disbursement wallet balance")
        rb = body.get("responseBody") or {}
        return {"available_kobo": _naira_to_kobo(rb.get("availableBalance", 0) or 0), "raw": rb}

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
        payload = {
            "amount": _kobo_to_naira(amount_kobo),
            "reference": reference,
            "narration": narration,
            "destinationBankCode": bank_code,
            "destinationAccountNumber": account_number,
            "destinationAccountName": account_name,
            "currency": "NGN",
            "sourceAccountNumber": settings.monnify_wallet_account_number,
            "async": True,
        }
        body = await self._call(
            "POST",
            f"{self.base_url}/api/v2/disbursements/single",
            "initiate transfer",
            json=payload,
        )
        if not body.get("requestSuccessful"):
            # Rejected (bad account, duplicate reference, etc.) — surface the reason.
            raise BadRequestException(
                body.get("responseMessage") or "The transfer could not be initiated."
            )
        rb = body.get("responseBody") or {}
        return {
            "status": rb.get("status", ""),
            "fee_kobo": _naira_to_kobo(rb.get("totalFee", 0) or 0),
            "raw": rb,
        }

    async def authorize_transfer(self, reference: str, otp: str) -> dict:
        body = await self._call(
            "POST",
            f"{self.base_url}/api/v2/disbursements/single/validate-otp",
            "authorize transfer",
            json={"reference": reference, "authorizationCode": otp},
        )
        if not body.get("requestSuccessful"):
            raise BadRequestException(
                body.get("responseMessage") or "The OTP could not be validated."
            )
        rb = body.get("responseBody") or {}
        return {
            "status": rb.get("status", ""),
            "fee_kobo": _naira_to_kobo(rb.get("totalFee", 0) or 0),
            "raw": rb,
        }

    async def resend_transfer_otp(self, reference: str) -> dict:
        body = await self._call(
            "POST",
            f"{self.base_url}/api/v2/disbursements/single/resend-otp",
            "resend OTP",
            json={"reference": reference},
        )
        if not body.get("requestSuccessful"):
            raise BadRequestException(
                body.get("responseMessage") or "Could not resend the OTP."
            )
        return {"raw": body.get("responseBody") or {}}

    async def get_transfer_status(self, reference: str) -> dict:
        body = await self._call(
            "GET",
            f"{self.base_url}/api/v2/disbursements/single/summary",
            "check transfer status",
            params={"reference": reference},
        )
        if not body.get("requestSuccessful"):
            raise InternalServerException("Could not fetch the transfer status")
        rb = body.get("responseBody") or {}
        return {
            "status": rb.get("status", ""),
            "fee_kobo": _naira_to_kobo(rb.get("fee", 0) or 0),
            "monnify_reference": rb.get("transactionReference", ""),
            "description": rb.get("transactionDescription", ""),
            "raw": rb,
        }

    # ------------------------------------------------------------------ #
    # Direct Debit (recurring contributions)
    # ------------------------------------------------------------------ #
    async def create_mandate(
        self,
        *,
        mandate_reference: str,
        amount_kobo: int,
        customer_name: str,
        customer_phone: str,
        customer_email: str,
        customer_address: str,
        account_number: str,
        bank_code: str,
        description: str,
        start_date,
        end_date,
        redirect_url: str,
    ) -> dict:
        payload = {
            "contractCode": self.contract_code,
            "mandateReference": mandate_reference,
            "mandateAmount": _kobo_to_naira(amount_kobo),
            "autoRenew": True,
            "customerCancellation": True,
            "customerName": customer_name,
            "customerPhoneNumber": customer_phone,
            "customerEmailAddress": customer_email,
            "customerAddress": customer_address,
            "customerAccountNumber": account_number,
            "customerAccountBankCode": bank_code,
            "mandateDescription": description,
            "mandateStartDate": start_date.strftime("%Y-%m-%dT%H:%M:%S"),
            "mandateEndDate": end_date.strftime("%Y-%m-%dT%H:%M:%S"),
            "redirectUrl": redirect_url,
        }
        body = await self._call(
            "POST",
            f"{self.base_url}/api/v1/direct-debit/mandate/create",
            "create mandate",
            json=payload,
        )
        if not body.get("requestSuccessful"):
            raise BadRequestException(
                body.get("responseMessage") or "The mandate could not be created."
            )
        rb = body.get("responseBody") or {}
        mandate_code = rb.get("mandateCode")
        if not mandate_code:
            raise InternalServerException("The payment provider returned no mandate code")
        return {
            "mandate_code": mandate_code,
            "status": rb.get("mandateStatus", ""),
            # Best-known field for the customer-facing bank authorization link —
            # confirm exactly which field this is once sandbox testing runs.
            "authorization_link": rb.get("redirectUrl", ""),
            "raw": rb,
        }

    async def debit_mandate(
        self,
        *,
        mandate_code: str,
        payment_reference: str,
        amount_kobo: int,
        narration: str,
        customer_email: str,
    ) -> dict:
        payload = {
            "paymentReference": payment_reference,
            "mandateCode": mandate_code,
            "debitAmount": _kobo_to_naira(amount_kobo),
            "narration": narration,
            "customerEmail": customer_email,
        }
        body = await self._call(
            "POST",
            f"{self.base_url}/api/v1/direct-debit/mandate/debit",
            "debit mandate",
            json=payload,
        )
        if not body.get("requestSuccessful"):
            raise BadRequestException(
                body.get("responseMessage") or "The debit could not be initiated."
            )
        rb = body.get("responseBody") or {}
        return {"status": rb.get("transactionStatus", ""), "raw": rb}

    async def get_debit_status(self, payment_reference: str) -> dict:
        body = await self._call(
            "GET",
            f"{self.base_url}/api/v1/direct-debit/mandate/debit-status",
            "check debit status",
            params={"paymentReference": payment_reference},
        )
        if not body.get("requestSuccessful"):
            raise InternalServerException("Could not fetch the debit status")
        rb = body.get("responseBody") or {}
        return {
            "status": rb.get("transactionStatus", ""),
            "transaction_reference": rb.get("transactionReference", ""),
            "raw": rb,
        }

    async def cancel_mandate(self, mandate_code: str) -> dict:
        body = await self._call(
            "PATCH",
            f"{self.base_url}/api/v1/direct-debit/mandate/cancel-mandate/{mandate_code}",
            "cancel mandate",
        )
        if not body.get("requestSuccessful"):
            raise BadRequestException(
                body.get("responseMessage") or "The mandate could not be cancelled."
            )
        rb = body.get("responseBody") or {}
        return {"status": rb.get("mandateStatus", ""), "raw": rb}

    # ------------------------------------------------------------------ #
    # Refunds
    # ------------------------------------------------------------------ #
    async def initiate_refund(
        self,
        *,
        transaction_reference: str,
        refund_reference: str,
        amount_kobo: int,
        reason: str,
        customer_note: str,
    ) -> dict:
        payload = {
            "transactionReference": transaction_reference,
            "refundReference": refund_reference,
            "refundAmount": _kobo_to_naira(amount_kobo),
            "refundReason": reason[:64],
            "customerNote": customer_note[:16],
        }
        body = await self._call(
            "POST",
            f"{self.base_url}/api/v1/refunds/initiate-refund",
            "initiate refund",
            json=payload,
        )
        if not body.get("requestSuccessful"):
            raise BadRequestException(
                body.get("responseMessage") or "The refund could not be initiated."
            )
        rb = body.get("responseBody") or {}
        return {
            "status": rb.get("refundStatus", ""),
            "refund_type": rb.get("refundType", ""),
            "monnify_reference": rb.get("reference", ""),
            "raw": rb,
        }

    async def get_refund_status(self, refund_reference: str) -> dict:
        body = await self._call(
            "GET",
            f"{self.base_url}/api/v1/refunds/{refund_reference}",
            "check refund status",
        )
        if not body.get("requestSuccessful"):
            raise InternalServerException("Could not fetch the refund status")
        rb = body.get("responseBody") or {}
        return {
            "status": rb.get("refundStatus", ""),
            "refund_type": rb.get("refundType", ""),
            "monnify_reference": rb.get("reference", ""),
            "raw": rb,
        }
