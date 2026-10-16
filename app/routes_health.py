"""Health probe route.

Extracted from main.py (2026-10-16 split).
"""
from fastapi import APIRouter

from . import llm_client, whisper

router = APIRouter()


@router.get("/api/health")
def health():
    return {
        "ok": True,
        "llm": llm_client.health(),
        "whisper": {"available": "lazy", "model": whisper.MODEL_NAME},
    }
