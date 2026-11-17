"""Prueba que la clave de DeepSeek responde, sin mostrarla.

Lee `.env` de la raiz del proyecto y hace una llamada minima al modelo.
Uso: python herramientas/probar-clave.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def cargar_env(ruta=RAIZ / ".env"):
    if not ruta.exists():
        raise SystemExit(f"no existe {ruta}")
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    cargar_env()
    clave = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not clave:
        raise SystemExit("DEEPSEEK_API_KEY vacia en .env")
    print(f"clave cargada: {len(clave)} caracteres, empieza por {clave[:3]}...")

    base = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    modelo = os.environ.get("LLM_MODEL", "deepseek-chat")
    cuerpo = json.dumps({
        "model": modelo,
        "messages": [
            {"role": "system", "content": "Responde solo con la palabra OK."},
            {"role": "user", "content": "confirma"},
        ],
        "max_tokens": 8,
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions", data=cuerpo,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {clave}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            datos = json.load(r)
    except urllib.error.HTTPError as e:
        detalle = e.read()[:300].decode("utf-8", "replace")
        raise SystemExit(f"la API respondio {e.code}: {detalle}")
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"no se pudo conectar: {type(e).__name__}: {e}")

    texto = datos["choices"][0]["message"]["content"].strip()
    uso = datos.get("usage", {})
    print(f"OK · modelo {datos.get('model')} · respuesta: {texto!r}")
    print(f"tokens: {uso.get('prompt_tokens')} entrada + {uso.get('completion_tokens')} salida")
    return 0


if __name__ == "__main__":
    sys.exit(main())
