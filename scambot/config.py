"""Settings for the demo scammer server. It is separate from Kavach: it only borrows the AssemblyAI settings."""

from app.config import Settings


class BotSettings(Settings):
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_target_number: str = ""  # the ONLY number this server will ever ring: the owner's own phone
    public_base_url: str = ""  # the https address Twilio can reach this server on
    scammer_voice_id: str = "aai-michael"
