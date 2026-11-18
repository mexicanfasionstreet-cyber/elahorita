"""Voz: cliente de Voicebox con la API real, todo o nada, avisos y el script de prueba."""
import importlib.util
import json
import types
from pathlib import Path

import pytest

import config
import voz

GUION = {"_nombre": "prueba-vb", "gancho": "Hola.", "gancho_pantalla": "HOLA",
         "notas": [{"kicker": "MX", "texto": "Nota uno."}], "cierre": "Adios."}


@pytest.fixture
def entorno(tmp_path, monkeypatch, tono, whisper_falso, tg):
    """Build temporal y edge-tts falso (copia el tono y da tiempos)."""
    import subprocess
    monkeypatch.setattr(voz, "BUILD", tmp_path / "build")

    def edge(texto, salida):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tono), str(salida)], check=True)
        return [{"texto": "x", "t0": 0, "dur": 0.3}]
    monkeypatch.setattr(voz, "con_edge_tts", edge)
    return tmp_path


def guion():
    return json.loads(json.dumps(GUION))


def test_engine_viejo_se_rechaza_con_detalle(voicebox, monkeypatch, tmp_path):
    voicebox("ok")
    monkeypatch.setattr(config, "VOICEBOX_ENGINE", "qwen3-tts")
    with pytest.raises(RuntimeError, match="422"):
        voz.con_voicebox("hola", tmp_path / "x.mp3")


def test_servidor_sano_todo_con_voicebox(entorno, voicebox, tg):
    voicebox("ok")
    segs, total = voz.generar_voz(guion(), "voicebox")
    assert all(s["voz"] == "voicebox" and s["palabras"] for s in segs)   # con tiempos de Whisper
    assert abs(voz.duracion(segs[0]["audio"]) - 4.0) < 0.2 and total.exists()   # wav -> mp3
    assert not tg.mensajes()


def test_falla_a_la_mitad_todo_pasa_a_respaldo(entorno, voicebox, tg):
    voicebox("falla")
    segs, _ = voz.generar_voz(guion(), "voicebox")
    assert all(s["voz"] == "edge-tts" for s in segs)
    assert "CUDA out of memory" in tg.mensajes()[-1]["text"]


def test_pc_apagada(entorno, puerto_cerrado, monkeypatch, tg):
    monkeypatch.setattr(config, "VOICEBOX_URL", puerto_cerrado)
    monkeypatch.setattr(config, "VOICEBOX_PROFILE", "carla-1")
    segs, _ = voz.generar_voz(guion(), "voicebox")
    assert all(s["voz"] == "edge-tts" for s in segs) and tg.mensajes()


def test_sin_whisper_sale_con_carla_y_avisa(entorno, voicebox, monkeypatch, tg):
    import alinear
    voicebox("ok")

    def roto(audio, texto=""):
        raise ImportError("no hay faster_whisper")
    monkeypatch.setattr(alinear, "transcribir", roto)
    segs, _ = voz.generar_voz(guion(), "voicebox")
    assert all(s["voz"] == "voicebox" and not s["palabras"] for s in segs)
    assert "Subtitulos incompletos" in tg.mensajes()[-1]["text"]


@pytest.fixture
def probar(entorno, monkeypatch):
    raiz = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("probar_voicebox", raiz / "herramientas" / "probar-voicebox.py")
    pv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pv)
    monkeypatch.setattr(pv, "RAIZ", entorno)
    (entorno / "build").mkdir(exist_ok=True)
    enviados = []
    monkeypatch.setattr(pv.telegram, "mandar_video", lambda r, t="": enviados.append(("video", t)))
    monkeypatch.setattr(pv.telegram, "mandar_audio", lambda r, t="": enviados.append(("audio", t)))
    corridas = []

    class Hecho:
        returncode, stdout, stderr = 0, "", ""

    # solo el subprocess del script (voz.py usa el suyo, real, para ffmpeg)
    monkeypatch.setattr(pv, "subprocess", types.SimpleNamespace(run=lambda c, **k: corridas.append(c) or Hecho()))
    monkeypatch.setattr("sys.argv", ["probar-voicebox.py"])
    return pv, enviados, corridas


def test_script_de_prueba_completo(probar, voicebox):
    pv, enviados, corridas = probar
    voicebox("ok")
    assert pv.main() == 0
    assert [Path(c[1]).name for c in corridas] == ["voz.py", "capsula.py"]
    assert enviados[-1][0] == "video" and "Carla-News" in enviados[-1][1]


def test_script_perfil_equivocado(probar, voicebox, monkeypatch, tg):
    pv, _, _ = probar
    voicebox("ok")
    monkeypatch.setattr(config, "VOICEBOX_PROFILE", "otro")
    assert pv.main() == 1 and "Carla-News: carla-1" in tg.mensajes()[-1]["text"]


def test_script_sin_conexion(probar, puerto_cerrado, monkeypatch, tg):
    pv, _, _ = probar
    monkeypatch.setattr(config, "VOICEBOX_URL", puerto_cerrado)
    monkeypatch.setattr(config, "VOICEBOX_PROFILE", "carla-1")
    assert pv.main() == 1 and "conexion" in tg.mensajes()[-1]["text"]
