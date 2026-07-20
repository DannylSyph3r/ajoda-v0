from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str
    readonly_database_url: str = ""  # Phase 11 — not used yet

    # WhatsApp / Meta
    meta_phone_number_id: str
    meta_access_token: str
    meta_verify_token: str
    meta_app_secret: str  # X-Hub-Signature-256 webhook verification

    # Monnify (PSP — collections + disbursement). Sandbox base by default; flip to
    # https://api.monnify.com for live via env. No separate webhook-signing secret —
    # Monnify signs webhooks with the Secret Key.
    monnify_base_url: str = "https://sandbox.monnify.com"
    monnify_api_key: str = ""
    monnify_secret_key: str = ""
    monnify_contract_code: str = ""
    monnify_wallet_account_number: str = ""  # disbursement wallet / transfer source
    # Wallet-side buffer (kobo) added to the amount when checking disbursement-wallet
    # sufficiency, since the exact Monnify transfer fee is only known after initiation.
    monnify_transfer_fee_buffer_kobo: int = 20000  # ₦200

    # AI
    gemini_api_key: str = ""

    # Auth
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Internal
    internal_cron_secret: str
    frontend_url: str = ""
    prod_url: str = ""

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    @property
    def sync_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql://", 1)
        return url.replace("+asyncpg", "")

    @property
    def sync_readonly_database_url(self) -> str:
        """
        Normalise READONLY_DATABASE_URL to a psycopg2-compatible sync URL.
        Strips +asyncpg driver if present and normalises the postgres:// prefix.
        Deviation D26: added to support the synchronous readonly engine for ADK.
        """
        url = self.readonly_database_url
        if not url:
            return ""
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        url = url.replace("+asyncpg", "")
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()