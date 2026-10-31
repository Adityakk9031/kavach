"""FastAPI entry point. Run with: uv run uvicorn app.main:app --reload"""

from importlib.metadata import version

from fastapi import FastAPI

from app.config import get_settings

app = FastAPI(title="Kavach", version="0.1.0")


@app.get("/health")
def health() -> dict:
    """Liveness plus config readiness. Reports which secrets are missing, never their values."""
    settings = get_settings()
    missing = settings.missing_secrets()
    return {
        "status": "ok",
        "ready": not missing,
        "missing_secrets": missing,
        "language": settings.language,
        "stt_model": settings.stt_model,
        "detector_model": settings.detector_model,
        "assemblyai_sdk": version("assemblyai"),
    }
