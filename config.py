"""Configuracion compartida: lee `.env` y expone los valores del proyecto."""
from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def cargar_env(ruta=None):
    ruta = Path(ruta) if ruta else RAIZ / ".env"
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


cargar_env()

LLAVE = os.environ.get("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
MODELO = os.environ.get("LLM_MODEL", "deepseek-chat")

VOZ = os.environ.get("CAPSULA_VOZ", "es-MX-JorgeNeural")
VOZ_RITMO = os.environ.get("CAPSULA_VOZ_RITMO", "+10%")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

VOICEBOX_URL = os.environ.get("VOICEBOX_URL", "").rstrip("/")
VOICEBOX_PROFILE = os.environ.get("VOICEBOX_PROFILE_ID", "")
VOICEBOX_TIMEOUT = int(os.environ.get("VOICEBOX_TIMEOUT", "90") or 90)

# palabras por segundo de la voz en español, para estimar duración antes de grabar
PALABRAS_POR_SEGUNDO = 2.7
