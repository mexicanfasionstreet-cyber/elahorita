"""Base comun de las pruebas de El Ahorita.

Reglas que se cumplen solas en cada prueba (fixture `aislado`):
  - nada toca los archivos de estado reales (datos/*.json): van a una carpeta temporal;
  - nada sale a la red: Telegram, DeepSeek, YouTube y Voicebox estan simulados o apagados;
  - la hora es la de Tijuana y se puede fijar con `reloj`.

Correr:  python -m pytest            (o:  python -m pytest -k franjas -q)
Requiere ffmpeg en el PATH (lo usan voz, subtitulos y capsula).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402

TZ = config.TZ
CHAT = "111"


# ------------------------------------------------------------------ aislamiento
@pytest.fixture(autouse=True)
def aislado(tmp_path, monkeypatch):
    import franjas
    import orquestador
    import secciones
    import telegram

    for nombre, valor in [("TELEGRAM_TOKEN", "x"), ("TELEGRAM_CHAT", CHAT), ("LLAVE", ""),
                          ("YT_CLIENT_ID", ""), ("YT_CLIENT_SECRET", ""), ("YT_REFRESH", ""),
                          ("VOICEBOX_URL", ""), ("VOICEBOX_PROFILE", ""), ("VOICEBOX_ENGINE", "")]:
        monkeypatch.setattr(config, nombre, valor)
    monkeypatch.setattr(telegram, "ESTADO", tmp_path / "telegram.json")
    monkeypatch.setattr(orquestador, "ESTADO", tmp_path / "orquestador.json")
    monkeypatch.setattr(franjas, "PUBLICADAS", tmp_path / "publicadas.json")
    monkeypatch.setattr(franjas, "SUBIDAS", tmp_path / "subidas.json")
    monkeypatch.setattr(franjas, "EVENTOS", tmp_path / "eventos.json")
    monkeypatch.setattr(secciones, "CACHE_IA", tmp_path / "secciones-ia.json")
    monkeypatch.setattr(orquestador, "guardar_offset", lambda: None)

    def sin_red(metodo, **params):
        raise AssertionError(f"la prueba intento llamar a Telegram de verdad: {metodo}")
    monkeypatch.setattr(telegram, "_llamar", sin_red)
    antes = {p.name: p.stat().st_mtime for p in (RAIZ / "datos").glob("*.json")}
    yield tmp_path
    despues = {p.name: p.stat().st_mtime for p in (RAIZ / "datos").glob("*.json")}
    tocados = sorted(n for n in despues if antes.get(n) != despues[n])
    assert not tocados, f"la prueba escribio en datos/ del repo: {tocados}"


@pytest.fixture
def reloj(monkeypatch):
    """reloj(2026, 11, 18, 15, 10) fija la hora de Tijuana que ve todo el robot."""
    def fijar(*partes):
        momento = datetime(*partes, tzinfo=TZ)
        monkeypatch.setattr(config, "ahora", lambda: momento)
        return momento
    return fijar


# ------------------------------------------------------------------ Telegram simulado
_ETIQUETAS_OK = re.compile(r"</?(b|i|pre|code)>")
_ENTIDAD_OK = re.compile(r"&(amp|lt|gt|quot);")


def html_roto(texto):
    """Lo que haria que Telegram rechazara un mensaje en modo HTML."""
    limpio = _ENTIDAD_OK.sub("", _ETIQUETAS_OK.sub("", texto or ""))
    return "<" in limpio or "&" in limpio


class TelegramFalso:
    def __init__(self):
        self.enviados, self.updates, self._id = [], [], 1000

    def __call__(self, metodo, **params):
        self.enviados.append((metodo, params))
        if metodo == "getUpdates":
            salida, self.updates = self.updates, []
            return salida
        if metodo == "sendMessage" and params.get("parse_mode") == "HTML" and html_roto(params["text"]):
            raise SystemExit("Telegram respondio 400: Bad Request: can't parse entities")
        return {"message_id": 1}

    def mensajes(self):
        return [p for m, p in self.enviados if m == "sendMessage"]

    def botones(self, mensaje=None):
        mensaje = mensaje or self.mensajes()[-1]
        teclado = json.loads(mensaje.get("reply_markup") or "{}").get("inline_keyboard", [])
        return [b["callback_data"] for fila in teclado for b in fila]

    def toca(self, dato, chat=CHAT):
        self._id += 1
        self.updates.append({"update_id": self._id, "callback_query": {
            "id": "c", "data": dato, "message": {"chat": {"id": int(chat)}}}})

    def escribe(self, texto, chat=CHAT):
        self._id += 1
        self.updates.append({"update_id": self._id,
                             "message": {"text": texto, "chat": {"id": int(chat)}}})


@pytest.fixture
def tg(monkeypatch):
    import telegram
    falso = TelegramFalso()
    monkeypatch.setattr(telegram, "_llamar", falso)
    return falso


# ------------------------------------------------------------------ audio y Voicebox
@pytest.fixture(scope="session")
def tono(tmp_path_factory):
    """4 s de audio wav (lo que entregaria Voicebox)."""
    ruta = tmp_path_factory.mktemp("audio") / "tono.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=4",
                    "-ar", "24000", str(ruta)], check=True)
    return ruta


class _Voicebox(BaseHTTPRequestHandler):
    """Rutas reales de jamiepine/voicebox: /health /profiles /generate /history/{id} /audio/{id}."""
    wav, modo, gens = b"", "ok", {}

    def log_message(self, *a):
        pass

    def _json(self, codigo, obj):
        cuerpo = json.dumps(obj).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._json(200, {"status": "healthy", "gpu_available": True})
        if self.path == "/profiles":
            return self._json(200, [{"id": "carla-1", "name": "Carla-News"}])
        if self.path.startswith("/history/"):
            g = self.gens.get(self.path.rsplit("/", 1)[-1])
            if not g:
                return self._json(404, {"detail": "Generation not found"})
            g["vistas"] += 1
            if g["vistas"] >= 2:
                g["status"] = "failed" if self.modo == "falla" and g["n"] >= 2 else "completed"
            return self._json(200, {"id": g["id"], "status": g["status"],
                                    "error": "CUDA out of memory" if g["status"] == "failed" else None})
        if self.path.startswith("/audio/"):
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.end_headers()
            return self.wfile.write(self.wav)
        return self._json(404, {"detail": "Not Found"})

    def do_POST(self):  # noqa: N802
        datos = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/generate":
            return self._json(404, {"detail": "Not Found"})
        if "engine" in datos and datos["engine"] not in ("qwen", "chatterbox", "luxtts"):
            return self._json(422, {"detail": [{"msg": "String should match pattern"}]})
        if datos.get("profile_id") != "carla-1":
            return self._json(404, {"detail": "Profile not found"})
        gid = str(uuid.uuid4())
        self.gens[gid] = {"id": gid, "status": "generating", "vistas": 0, "n": len(self.gens) + 1}
        return self._json(200, {"id": gid, "status": "generating"})


@pytest.fixture
def voicebox(tono, monkeypatch):
    """voicebox("ok" | "falla", audio=ruta) levanta un Voicebox falso y configura al robot."""
    servidores = []

    import time
    dormir = time.sleep
    # el robot espera 1.5 s entre consultas a Voicebox; en las pruebas no hace falta
    monkeypatch.setattr(time, "sleep", lambda s: dormir(min(s, 0.02)))

    def levantar(modo="ok", audio=None):
        wav = (audio or tono).read_bytes()
        manejador = type("H", (_Voicebox,), {"wav": wav, "modo": modo, "gens": {}})
        srv = ThreadingHTTPServer(("127.0.0.1", 0), manejador)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servidores.append(srv)
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        monkeypatch.setattr(config, "VOICEBOX_URL", url)
        monkeypatch.setattr(config, "VOICEBOX_PROFILE", "carla-1")
        monkeypatch.setattr(config, "VOICEBOX_TIMEOUT", 20)
        return url

    yield levantar
    for srv in servidores:
        srv.shutdown()


@pytest.fixture
def puerto_cerrado():
    """Una URL donde no escucha nadie (PC apagada)."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{puerto}"


@pytest.fixture
def whisper_falso(monkeypatch):
    """Whisper 'oye' el guion palabra por palabra, repartido en el audio."""
    import alinear
    import voz

    def transcribir(audio, texto=""):
        palabras = alinear.tokens_del_guion(texto)
        paso = voz.duracion(audio) / max(len(palabras), 1)
        return [("ciento" if p == "115" else p.lower(), i * paso, i * paso + paso * 0.9)
                for i, p in enumerate(palabras)]
    monkeypatch.setattr(alinear, "transcribir", transcribir)
    return transcribir


# ------------------------------------------------------------------ datos de noticias
def utc_de(*partes):
    """Hora de Tijuana -> ISO en UTC, como vienen las fechas en latest.json."""
    return datetime(*partes, tzinfo=TZ).astimezone(timezone.utc).isoformat()


def noticia(titulo, link, publicada, actualizada=None, medios=(), peso=4.0, seccion="politica",
            region="mx"):
    return {"title": titulo, "link": link, "published": publicada,
            "updated": actualizada or publicada, "source_name": link.split("/")[0],
            "weight": peso, "also": list(medios), "tags": [seccion], "region": region,
            "image": "http://img", "excerpt": ""}


@pytest.fixture
def latest(tmp_path, monkeypatch):
    """latest(items) escribe un latest.json temporal y apunta ahi a quien lo lee."""
    import guion
    import orquestador

    def escribir(items):
        raiz = tmp_path / "raiz"
        (raiz / "docs" / "data").mkdir(parents=True, exist_ok=True)
        ruta = raiz / "docs" / "data" / "latest.json"
        ruta.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(orquestador, "RAIZ", raiz)
        monkeypatch.setattr(guion, "RANKING", ruta)
        return ruta
    return escribir


@pytest.fixture(autouse=True)
def sin_wikipedia(monkeypatch):
    """Ninguna prueba sale a Wikipedia: sin red, cada nota va con fondo de diseño."""
    import fotos

    def _sin_red(*a, **k):
        raise OSError("sin red en pruebas")
    monkeypatch.setattr(fotos, "_get", _sin_red)
