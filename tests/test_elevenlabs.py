"""ElevenLabs: voz principal con tiempos por palabra, respaldo y avisos."""
import base64
import io
import json
import urllib.error

import pytest

import config
import voz
from tests.test_voz import GUION, entorno, guion  # noqa: F401  (fixture)


def respuesta(texto, tono_bytes):
    """Lo que devuelve /with-timestamps: audio + un tiempo por caracter."""
    chars = list(texto)
    ini = [round(i * 0.06, 3) for i in range(len(chars))]
    return {"audio_base64": base64.b64encode(tono_bytes).decode(),
            "alignment": {"characters": chars, "character_start_times_seconds": ini,
                          "character_end_times_seconds": [t + 0.06 for t in ini]}}


@pytest.fixture
def eleven(monkeypatch, tono):
    monkeypatch.setattr(config, "ELEVENLABS_KEY", "sk_prueba")
    monkeypatch.setattr(config, "ELEVENLABS_VOZ", "voz123")
    datos = tono.read_bytes()
    pedidos = []

    def falsa(cuerpo):
        pedidos.append(cuerpo)
        return respuesta(cuerpo["text"], datos)
    return falsa, pedidos


def test_palabras_desde_caracteres():
    al = {"characters": list("Hola, mundo"), "character_start_times_seconds": [i * 0.1 for i in range(11)],
          "character_end_times_seconds": [i * 0.1 + 0.1 for i in range(11)]}
    p = voz._palabras_de_alineacion(al)
    assert [x["texto"] for x in p] == ["Hola,", "mundo"]
    assert p[1]["t0"] == 0.6 and abs(p[1]["dur"] - 0.5) < 1e-6


def test_genera_audio_y_tiempos(eleven, tmp_path):
    falsa, pedidos = eleven
    palabras = voz.con_elevenlabs("Hola desde El Ahorita.", tmp_path / "a.mp3", llamar=falsa)
    assert (tmp_path / "a.mp3").stat().st_size > 1000
    assert [p["texto"] for p in palabras] == ["Hola", "desde", "El", "Ahorita."]
    assert pedidos[0]["model_id"] == config.ELEVENLABS_MODELO


def test_reintenta_si_esta_saturado(eleven, tmp_path, monkeypatch):
    falsa, _ = eleven
    monkeypatch.setattr("time.sleep", lambda s: None)
    veces = []

    def floja(cuerpo):
        veces.append(1)
        if len(veces) == 1:
            raise urllib.error.HTTPError("u", 429, "busy", {}, io.BytesIO(b'{"detail":"busy"}'))
        return falsa(cuerpo)
    voz.con_elevenlabs("Hola.", tmp_path / "a.mp3", llamar=floja)
    assert len(veces) == 2


def test_error_de_cuenta_se_dice_tal_cual(eleven, tmp_path):
    def sin_creditos(cuerpo):
        raise urllib.error.HTTPError("u", 401, "x", {}, io.BytesIO(b'{"detail":{"status":"quota_exceeded"}}'))
    with pytest.raises(RuntimeError, match="401.*quota_exceeded"):
        voz.con_elevenlabs("Hola.", tmp_path / "a.mp3", llamar=sin_creditos)


def test_todo_el_video_con_elevenlabs(entorno, eleven, monkeypatch, tg):  # noqa: F811
    falsa, pedidos = eleven
    original = voz.con_elevenlabs
    monkeypatch.setattr(voz, "con_elevenlabs", lambda t, s: original(t, s, llamar=falsa))
    segs, total = voz.generar_voz(guion(), "elevenlabs")
    assert {s["voz"] for s in segs} == {"elevenlabs"}
    assert all(s["palabras"] for s in segs) and total.exists()
    assert len(pedidos) == len(segs)
    assert not tg.mensajes()                                    # sin avisos


def test_si_falla_todo_va_con_respaldo_y_avisa(entorno, eleven, monkeypatch, tg):  # noqa: F811
    def cae(texto, salida):
        raise RuntimeError("ElevenLabs 401: invalid_api_key")
    monkeypatch.setattr(voz, "con_elevenlabs", cae)
    segs, _ = voz.generar_voz(guion(), "elevenlabs")
    assert {s["voz"] for s in segs} == {"edge-tts"}
    assert "ElevenLabs no respondio" in tg.mensajes()[-1]["text"]


def test_elevenlabs_va_primero(monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_KEY", "sk")
    monkeypatch.setattr(config, "ELEVENLABS_VOZ", "v")
    monkeypatch.setattr(config, "VOICEBOX_URL", "http://x")
    monkeypatch.setattr(config, "VOICEBOX_PROFILE", "p")
    assert voz.proveedor_auto() == "elevenlabs"
    monkeypatch.setattr(config, "ELEVENLABS_KEY", "")
    assert voz.proveedor_auto() == "voicebox"
