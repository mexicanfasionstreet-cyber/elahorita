"""Configuracion compartida: lee `.env` y expone los valores del proyecto."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent

# Todo el proyecto vive en hora de Tijuana. El runner de GitHub esta en UTC: si un
# script fecha sus archivos con datetime.now() y otro con la hora de Tijuana, desde
# las 16:00 (00:00 UTC) cada uno busca el archivo del otro con un dia distinto.
TZ = ZoneInfo("America/Tijuana")


def ahora():
    """La hora actual en Tijuana. Usar siempre esta, nunca datetime.now() a secas."""
    return datetime.now(TZ)


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

VOZ = os.environ.get("CAPSULA_VOZ", "es-MX-DaliaNeural")
VOZ_RITMO = os.environ.get("CAPSULA_VOZ_RITMO", "+10%")

YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "").strip()
YT_REFRESH = os.environ.get("YT_REFRESH_TOKEN", "").strip()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

VOICEBOX_URL = os.environ.get("VOICEBOX_URL", "").rstrip("/")
VOICEBOX_PROFILE = (os.environ.get("VOICEBOX_PROFILE_ID", "")
                    or os.environ.get("VOICEBOX_PROFILE", "")).strip()
VOICEBOX_ENGINE = os.environ.get("VOICEBOX_ENGINE", "").strip()   # vacio = el del perfil
VOICEBOX_TIMEOUT = int(os.environ.get("VOICEBOX_TIMEOUT", "90") or 90)

# palabras por segundo de la voz en español, para estimar duración antes de grabar
PALABRAS_POR_SEGUNDO = 2.7
