"""El orquestador: fechas, YouTube, franjas automaticas, caso especial, cupo y reintentos."""
from datetime import timedelta
from pathlib import Path

import pytest

import config
import franjas
import orquestador as orq
from conftest import html_roto, noticia, utc_de


@pytest.fixture
def comandos(monkeypatch):
    """Registra lo que el orquestador intenta correr, sin correrlo."""
    hechos = []
    monkeypatch.setattr(orq, "correr", lambda c, avisar=True: hechos.append(c) or True)
    return hechos


# ------------------------------------------------------------------ armar_video
def test_fechas_en_hora_de_tijuana(comandos, reloj, monkeypatch, tmp_path):
    reloj(2026, 11, 17, 20, 30)            # ya es 18 en UTC
    subidas = []
    monkeypatch.setattr(orq, "subir_a_youtube", lambda v, g: subidas.append((v, g)) or None)
    monkeypatch.setattr(orq.bot, "mandar_video", lambda *a, **k: None)
    video = orq.RAIZ / "docs" / "videos" / "2026-11-17-elegida.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    creado = not video.exists()
    video.touch()
    try:
        orq.armar_video(["https://ejemplo.mx/nota"])
    finally:
        if creado:
            video.unlink()
    g = comandos[0]
    assert g[g.index("--json") + 1].endswith("2026-11-17-elegida.json") and "--link" in g
    assert all(str(c[-1]).endswith("2026-11-17-elegida.json") for c in comandos[1:])
    assert str(subidas[0][1]).endswith("2026-11-17-elegida.json")


def test_sin_enlace_no_publica_otra_historia(comandos, tg):
    assert orq.armar_video([""]) is False and not comandos


def test_youtube_recibe_el_guion_y_es_privado_por_defecto(monkeypatch):
    monkeypatch.setattr(config, "YT_CLIENT_ID", "id")
    monkeypatch.setattr(config, "YT_CLIENT_SECRET", "s")
    monkeypatch.setattr(config, "YT_REFRESH", "r")
    monkeypatch.delenv("YT_PRIVACIDAD", raising=False)
    visto = {}

    class R:
        returncode, stderr = 0, ""
        stdout = "listo: https://youtube.com/shorts/abc"

    monkeypatch.setattr(orq.subprocess, "run", lambda c, **k: visto.setdefault("c", c) and R())
    assert orq.subir_a_youtube(Path("v.mp4"), Path("g.json")) == "https://youtube.com/shorts/abc"
    c = visto["c"]
    assert c[c.index("--guion") + 1] == "g.json" and c[c.index("--privacidad") + 1] == "private"


def test_aviso_de_error_con_traceback_escapado(tg):
    orq.correr(["-c", "raise SystemExit('<module> & roto')"])
    texto = tg.mensajes()[-1]["text"]
    assert "&lt;module&gt; &amp; roto" in texto and not html_roto(texto)


# ------------------------------------------------------------------ /nota y cupo
def test_nota_sin_cupo(comandos, tg, reloj):
    reloj(2026, 11, 18, 15, 10)
    estado = {"franjas": {"2026-11-18-madrugada": "x", "2026-11-18-manana": "x"}}
    for i in range(4):
        franjas.registrar_subida(f"v{i}", "t")
    assert orq.nota_a_mano("tema", estado) is False and not comandos
    assert "no cabe" in tg.mensajes()[-1]["text"]


def test_subir_asi_corre_nota_con_subir(comandos, tg, monkeypatch):
    monkeypatch.setattr(franjas, "cupo_para_nota", lambda e: 2)
    tg.toca("subir:2026-11-17-1834-nota")
    orq.atender_telegram({"franjas": {}})
    assert comandos[0][-2:] == ["--subir", "2026-11-17-1834-nota"]


# ------------------------------------------------------------------ franjas
@pytest.fixture
def videos(monkeypatch):
    hechos = []

    def armar(links, previos=(), **k):
        hechos.append((list(links), list(previos), k))
        return True
    monkeypatch.setattr(orq, "armar_video", armar)
    return hechos


@pytest.fixture
def sin_ia(monkeypatch):
    import secciones
    monkeypatch.setattr(secciones, "refinar", lambda items, **k: 0)


TARDE = franjas.franja_por_nombre("tarde")
CLAVE = "2026-11-18-tarde"


def normales():
    return [noticia("Sheinbaum anuncia reforma electoral en Palacio Nacional", "a/1", utc_de(2026, 11, 18, 13),
                    medios=["B", "C", "D"]),
            noticia("Trump amenaza con aranceles a Canadá", "d/4", utc_de(2026, 11, 18, 12, 30))]


def grandes():
    return [noticia("Explosión en refinería de Salina Cruz deja heridos", "x/1", utc_de(2026, 11, 18, 13),
                    medios=list("ABCDEFGHIJKL")),
            noticia("Renuncia el secretario de Hacienda Ramírez", "y/2", utc_de(2026, 11, 18, 14),
                    medios=list("MNOPQRSTUVWX"))]


def test_franja_normal_publica_sola(comandos, videos, sin_ia, latest, reloj):
    ahora = reloj(2026, 11, 18, 15, 10)
    latest(normales())
    estado = {"franjas": {}}
    orq.correr_franja(estado, CLAVE, TARDE, ahora)
    assert videos and videos[-1][0][0] == "a/1"
    assert estado["franjas"][CLAVE].startswith("automatica")


def test_franja_pasa_reservas(comandos, videos, sin_ia, latest, reloj):
    ahora = reloj(2026, 11, 18, 15, 10)
    latest(normales() + [noticia(f"Otra historia número {i} de Monterrey", f"o/{i}", utc_de(2026, 11, 18, 14))
                         for i in range(3)])
    orq.correr_franja({"franjas": {}}, CLAVE, TARDE, ahora)
    assert len(videos[-1][2]["reservas"]) == 2


@pytest.fixture
def especial(comandos, videos, sin_ia, latest, reloj, tg):
    ahora = reloj(2026, 11, 18, 15, 10)
    latest(grandes())
    estado = {"franjas": {}}
    orq.correr_franja(estado, CLAVE, TARDE, ahora)
    return estado, ahora


def test_caso_especial_pregunta(especial, videos, tg):
    estado, ahora = especial
    texto = tg.mensajes()[-1]["text"]
    assert not videos and estado.get("pendiente")
    assert "alto impacto" in texto and "15:40" in texto and not html_roto(texto)
    assert orq.franja_pendiente(estado, ahora)[0] is None          # no se vuelve a correr


def test_caso_especial_sin_respuesta_publica_la_mejor(especial, videos):
    estado, ahora = especial
    assert orq.revisar_pendiente(estado, ahora + timedelta(minutes=20)) is False and not videos
    orq.revisar_pendiente(estado, ahora + timedelta(minutes=31))
    assert videos and "sin respuesta" in estado["franjas"][CLAVE] and "pendiente" not in estado


def test_caso_especial_eliges_tu(especial, videos, tg):
    estado, _ = especial
    n = 1 + [o["link"] for o in estado["pendiente"]["opciones"]].index("y/2")
    tg.toca(f"pub:{estado['pendiente']['lote']}:n{n}")
    orq.atender_telegram(estado)
    assert videos[-1][0] == ["y/2"] and "elegiste" in estado["franjas"][CLAVE]


def test_caso_especial_ninguna_salta_la_franja(especial, videos, tg):
    estado, _ = especial
    tg.toca(f"pub:{estado['pendiente']['lote']}:nada")
    orq.atender_telegram(estado)
    assert not videos and "saltada" in estado["franjas"][CLAVE]


def test_reintento_y_rendicion(comandos, sin_ia, latest, reloj, tg, monkeypatch):
    ahora = reloj(2026, 11, 18, 15, 10)
    latest(normales())
    monkeypatch.setattr(orq, "armar_video", lambda *a, **k: False)
    estado = {"franjas": {}}
    orq.correr_franja(estado, CLAVE, TARDE, ahora)
    assert not estado["franjas"].get(CLAVE) and estado["intentos"][CLAVE] == 1
    orq.correr_franja(estado, CLAVE, TARDE, ahora)
    assert "fallida" in estado["franjas"][CLAVE] and "no salio" in tg.mensajes()[-1]["text"]


def test_franja_sin_noticias_avisa_y_cierra(comandos, videos, sin_ia, latest, reloj, tg):
    ahora = reloj(2026, 11, 18, 15, 10)
    latest([noticia("Banxico recorta la tasa", "c/3", utc_de(2026, 11, 18, 8))])
    estado = {"franjas": {}}
    orq.correr_franja(estado, CLAVE, TARDE, ahora)
    assert not videos and "sin noticias" in estado["franjas"][CLAVE]
