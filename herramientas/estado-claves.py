"""Muestra que claves cargaron, sin revelarlas.

Sirve para el workflow: si una clave llega vacia o cortada, se ve en el log.

Uso: python herramientas/estado-claves.py
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402

CLAVES = [
    ("DEEPSEEK_API_KEY", config.LLAVE),
    ("TELEGRAM_BOT_TOKEN", config.TELEGRAM_TOKEN),
    ("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT),
    ("YT_CLIENT_ID", config.YT_CLIENT_ID),
    ("YT_CLIENT_SECRET", config.YT_CLIENT_SECRET),
    ("YT_REFRESH_TOKEN", config.YT_REFRESH),
    ("VOICEBOX_URL", config.VOICEBOX_URL),
    ("VOICEBOX_PROFILE", config.VOICEBOX_PROFILE),
]


def main():
    for nombre, valor in CLAVES:
        estado = "ok" if valor else "VACIA"
        print(f"{nombre:<20} {len(valor):>4} caracteres  {estado}")
    print(f"{'modelo':<20} {config.MODELO}")
    print(f"{'base':<20} {config.BASE_URL}")
    print(f"{'voz':<20} {config.VOZ} {config.VOZ_RITMO}")
    faltan = [n for n, v in CLAVES[:3] if not v]
    if faltan:
        print(f"\nFALTAN CLAVES: {', '.join(faltan)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
