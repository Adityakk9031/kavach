"""Settings loaded from .env. Every tunable lives here so nothing is hard-coded elsewhere."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DecoyIdentity(BaseSettings):
    """Clearly fake details the takeover persona may say. Never real data."""

    name: str = "Ramesh Kumar"
    city: str = "Nagpur"
    bank: str = "State Bank"
    # Obviously invalid account and phone numbers, flagged as decoys in every log.
    account_last4: str = "0000"
    phone: str = "nine nine nine nine nine, zero zero zero zero zero"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- secrets ---
    assemblyai_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- language (English only in v1; Hindi planned once TTS-1 ships it) ---
    language: str = "english"  # TTS `language` takes the full name
    stt_language_codes: list[str] = Field(default_factory=lambda: ["en"])

    # --- AssemblyAI hosts ---
    tts_ws_url: str = "wss://tts.us.assemblyai.com/v1/ws"
    tts_http_url: str = "https://tts.us.assemblyai.com/v1/speech"
    stt_ws_url: str = "wss://streaming.assemblyai.com/v3/ws"
    llm_gateway_url: str = "https://llm-gateway.assemblyai.com/v1"

    # --- models ---
    stt_model: str = "universal-3-6-pro"
    stt_mode: str = "balanced"
    detector_model: str = "qwen3.5-4b-32k-fast"
    detector_reasoning_effort: str = ""  # only sent when set and supported
    detector_fallback_model: str = "gemma-4-31b"
    persona_model: str = "qwen3.5-4b-32k-fast"
    script_gen_model: str = "gemma-4-31b"

    # --- voices ---
    kavach_warning_voice_id: str = ""  # cloned family voice (US data zone)
    persona_voice_id: str = "aai-gunnar"
    fallback_warning_voice_id: str = "aai-peter"

    # --- audio ---
    sample_rate: int = 16000

    # --- detection ---
    risk_threshold: int = 70
    risk_rise: float = 0.7
    risk_decay_per_turn: float = 4.0
    detector_window_turns: int = 6
    detector_timeout_s: float = 2.5

    # --- warning text ---
    parent_address: str = "Papa"
    family_member_name: str = "your son"

    # --- alerts ---
    max_alerts_per_call: int = 3

    # --- storage ---
    db_path: str = "data/kavach.db"
    reports_dir: str = "data/reports"

    decoy: DecoyIdentity = Field(default_factory=DecoyIdentity)

    def missing_secrets(self) -> list[str]:
        """Names of required secrets that are not set yet."""
        required = {
            "ASSEMBLYAI_API_KEY": self.assemblyai_api_key,
            "KAVACH_WARNING_VOICE_ID": self.kavach_warning_voice_id,
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "TELEGRAM_CHAT_ID": self.telegram_chat_id,
        }
        return [name for name, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
