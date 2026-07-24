"""
PaymentProvider — thin boundary around all outbound PSP calls.

The prototype ships a single implementation (MonnifyProvider). This interface
keeps Monnify-specific request/response shapes out of the flow logic and makes
the V1 Java port a mechanical re-implementation.

Collection methods (initialize_transaction, verify_transaction) are used from
Phase 1. Disbursement methods (get_banks, name_enquiry, wallet_balance,
initiate_transfer, authorize_transfer) are declared here now and implemented in
Phase 3 — MonnifyProvider raises NotImplementedException for them until then.

All amounts crossing this boundary are in **kobo** (the app's internal unit).
Implementations convert to/from the provider's own unit internally.
"""
from abc import ABC, abstractmethod


class PaymentProvider(ABC):
    # ------------------------------------------------------------------ #
    # Collections (Phase 1)
    # ------------------------------------------------------------------ #
    @abstractmethod
    async def initialize_transaction(
        self,
        *,
        reference: str,
        amount_kobo: int,
        customer_name: str,
        customer_email: str,
        redirect_url: str,
    ) -> dict:
        """
        Initialize a hosted-checkout transaction.

        Returns a normalized dict:
            {"checkout_url": str, "transaction_reference": str}
        Raises on provider failure.
        """
        ...

    @abstractmethod
    async def verify_transaction(self, reference: str) -> dict:
        """
        Server-side verify by our merchant payment reference. This is the
        authoritative check before settlement — never trust a browser callback.

        Returns a normalized dict:
            {"status": str, "amount_kobo": int, "raw": dict}
        where `status` is the provider's payment status
        (e.g. PAID / PENDING / FAILED / EXPIRED / REVERSED).
        Raises on provider failure.
        """
        ...

    # ------------------------------------------------------------------ #
    # Disbursement (Phase 3 — signatures defined now, implemented later)
    # ------------------------------------------------------------------ #
    @abstractmethod
    async def get_banks(self) -> list[dict]:
        """Return the list of supported banks (code + name)."""
        ...

    @abstractmethod
    async def get_direct_debit_banks(self) -> list[dict]:
        """
        Return the fixed set of banks this provider supports for Direct Debit
        mandates — a small subset of get_banks(), not every disbursement-capable
        bank. Returns [{"code": str, "name": str}, ...].
        """
        ...

    @abstractmethod
    async def name_enquiry(self, account_number: str, bank_code: str) -> dict:
        """
        Resolve the true account holder name for an account/bank pair.
        Returns {"account_name": str, "account_number": str, "bank_code": str}.
        """
        ...

    @abstractmethod
    async def wallet_balance(self) -> dict:
        """Return the disbursement wallet balance: {"available_kobo": int, "raw": dict}."""
        ...

    @abstractmethod
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
        """
        Initiate a single transfer (async). With MFA on, resolves to
        PENDING_AUTHORIZATION. Returns {"status": str, "raw": dict}.
        """
        ...

    @abstractmethod
    async def authorize_transfer(self, reference: str, otp: str) -> dict:
        """Authorize a PENDING_AUTHORIZATION transfer with the emailed OTP."""
        ...

    @abstractmethod
    async def resend_transfer_otp(self, reference: str) -> dict:
        """Request a fresh OTP for a PENDING_AUTHORIZATION transfer."""
        ...

    @abstractmethod
    async def get_transfer_status(self, reference: str) -> dict:
        """
        Poll a single transfer's status (reconciliation fallback for a missed
        webhook). Returns {"status": str, "fee_kobo": int,
        "monnify_reference": str, "description": str, "raw": dict}.
        """
        ...

    # ------------------------------------------------------------------ #
    # Direct Debit (recurring contributions)
    # ------------------------------------------------------------------ #
    @abstractmethod
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
        """
        Create a direct-debit mandate. Returns a normalized dict:
            {"mandate_code": str, "status": str, "authorization_link": str, "raw": dict}
        Raises on provider failure.
        """
        ...

    @abstractmethod
    async def debit_mandate(
        self,
        *,
        mandate_code: str,
        payment_reference: str,
        amount_kobo: int,
        narration: str,
        customer_email: str,
    ) -> dict:
        """
        Attempt a single debit against an activated mandate. Resolves async —
        returns {"status": str, "raw": dict} where status is typically PENDING;
        call get_debit_status to resolve the outcome.
        """
        ...

    @abstractmethod
    async def get_debit_status(self, payment_reference: str) -> dict:
        """Poll a debit's outcome. Returns {"status": str, "raw": dict}."""
        ...

    @abstractmethod
    async def cancel_mandate(self, mandate_code: str) -> dict:
        """Request cancellation of a mandate. Returns {"status": str, "raw": dict}."""
        ...

    # ------------------------------------------------------------------ #
    # Refunds
    # ------------------------------------------------------------------ #
    @abstractmethod
    async def initiate_refund(
        self,
        *,
        transaction_reference: str,
        refund_reference: str,
        amount_kobo: int,
        reason: str,
        customer_note: str,
    ) -> dict:
        """
        Initiate a refund (full or partial) against a settled collection.
        Returns {"status": str, "refund_type": str, "monnify_reference": str, "raw": dict}.
        """
        ...

    @abstractmethod
    async def get_refund_status(self, refund_reference: str) -> dict:
        """Poll a refund's outcome. Returns {"status": str, "raw": dict}."""
        ...


# In-process singleton factory. Mirrors the base's single-worker singleton
# pattern (e.g. intent_service._gemini_flash). Import lazily to avoid a cycle.
_provider: PaymentProvider | None = None


def get_payment_provider() -> PaymentProvider:
    global _provider
    if _provider is None:
        from app.services.monnify_provider import MonnifyProvider

        _provider = MonnifyProvider()
    return _provider
