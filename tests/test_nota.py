"""/nota: elige la historia que pediste, lee varios articulos y no sube notas cortas."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import nota
import orquestador as orq
import telegram

PEDIDO = "google menciona que estan usando ia automatizadas para hackeos"


def it(titulo, link, cuerpo=""):
    return {"title": titulo, "link": link, "body": cuerpo, "published": "2026-11-17T20:00:00+00:00"}


RESULTADOS = [
    it("FBI alerta por ARTEX, una IA que podría acelerar los ciberataques", "g/fbi1"),
    it("El FBI advierte sobre ARTEX y los ciberataques con inteligencia artificial", "g/fbi2"),
    it("ARTEX: el FBI lanza alerta por nueva herramienta de IA", "g/fbi3"),
    it("Google detecta hackers que usan IA de forma automatizada para sus ataques", "g/goo1"),
    it("Google advierte: grupos de hackeo ya usan inteligencia artificial automatizada", "g/goo2"),
    it("Sheinbaum presenta el Plan México en APEC", "g/mx1"),
]


def test_palabras_clave_del_pedido():
    assert nota.terminos(PEDIDO) == ["google", "ia", "automatizadas", "hackeos"]


def test_gana_lo_que_pediste_no_lo_mas_cubierto():
    grupos = nota.agrupar([dict(x) for x in RESULTADOS], nota.terminos(PEDIDO))
    assert grupos[0][0]["link"].startswith("g/goo") and len(grupos[0]) == 2
    assert any(len(g) == 3 and g[0]["link"].startswith("g/fbi") for g in grupos)


def test_caso_real_del_empate():
    reales = [it("Google enciende las alarmas: la IA podría lanzar ciberataques sin ayuda humana", "r/g1"),
              it("Google: la IA convierte parches en ataques automatizados contra sistemas sin actualizar", "r/g2"),
              it("Alerta FBI por ARTEX, IA que hackea empresas en menos de tres horas", "r/f1"),
              it("El FBI emite alerta por ARTEX, la IA que hackea empresas", "r/f2")]
    g = nota.agrupar([dict(x) for x in reales], nota.terminos(PEDIDO))
    assert g[0][0]["link"].startswith("r/g")
    assert g[0][0]["_coincide_grupo"] > g[1][0]["_coincide_grupo"]


class Args:
    tema, prueba, sin_verificar = "lluvia de meteoros leonidas", False, False


def test_sin_coincidencias_ofrece_opciones_sin_gastar(tg, monkeypatch):
    monkeypatch.setattr(nota, "buscar_tema", lambda t: nota.agrupar([dict(x) for x in RESULTADOS], nota.terminos(t)))
    llamadas = []
    monkeypatch.setattr(nota.guion, "llamar_llm", lambda *a, **k: llamadas.append(1) or "{}")
    assert nota.construir(Args) is None and not llamadas
    botones = tg.botones()
    assert "No encontre" in tg.mensajes()[-1]["text"] and botones[0].endswith(":n1")
    tg.toca(botones[0])
    d = telegram.recoger(texto_libre=True)
    assert d["accion"] == "nota_manual" and d["texto"].startswith("g/")


def test_horas_reales():
    hace2 = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    assert 1.9 <= nota.horas_desde(hace2) <= 2.1 and nota.horas_desde(None) == 99.0


def test_lee_hasta_tres_articulos(monkeypatch):
    arts = {"u1": "uno " * 50, "u2": "", "u3": "tres " * 50, "u4": "cuatro " * 50, "u5": "cinco " * 50}
    monkeypatch.setattr(nota, "resolver_enlace", lambda l, c: (l, ""))
    monkeypatch.setattr(nota.material, "articulo", lambda u: {"texto": arts[u], "descripcion": "", "imagen": "",
                                                               "titulo": "", "palabras": len(arts[u].split())})
    leidos, _ = nota.reunir_material(list(arts), None)
    assert [a["url_real"] for a in leidos] == ["u1", "u3", "u4"]
    assert "[Fuente 2:" in nota.cuerpo_combinado(leidos)


@pytest.fixture
def publicar(tg, monkeypatch, tmp_path):
    subidas, videos = [], []
    monkeypatch.setattr(nota, "subir_a_youtube", lambda v, g: subidas.append(v) or "https://youtube.com/shorts/x")
    monkeypatch.setattr(nota.telegram_mod, "mandar_video", lambda v, t="": videos.append(t))

    def con(palabras, **k):
        d = tmp_path / "2026-11-17-1834-nota.json"
        d.write_text(json.dumps({"palabras": palabras, "tema": "x", "historias": []}))
        nota.publicar_y_avisar(d, Path("v.mp4"), "tema", **k)
    return con, subidas, videos


def test_nota_corta_no_se_sube(publicar, tg):
    con, subidas, videos = publicar
    con(40)
    assert not subidas and "No lo subi" in videos[-1]
    assert "subir:2026-11-17-1834-nota" in tg.botones()


def test_nota_normal_se_sube(publicar):
    con, subidas, videos = publicar
    con(170)
    assert subidas and "shorts/x" in videos[-1]


def test_modo_prueba_nunca_sube(publicar):
    con, subidas, videos = publicar
    con(170, prueba=True)
    assert not subidas and "prueba" in videos[-1]


def test_orquestador_respeta_cupo_en_nota(tg, monkeypatch):
    corridas = []
    monkeypatch.setattr(orq, "correr", lambda c, avisar=True: corridas.append(c) or True)
    monkeypatch.setattr(orq.franjas, "cupo_para_nota", lambda e: 1)
    tg.escribe("/nota sismo en Oaxaca")
    orq.atender_telegram({"franjas": {}})
    assert corridas and corridas[0][-1] == "sismo en Oaxaca"


# ------------------------------------------------------------------ /notavideo
def test_notavideo_manda_video_titulo_y_descripcion_sin_subir(tg, monkeypatch, tmp_path):
    videos, subidas = [], []
    monkeypatch.setattr(nota.telegram_mod, "mandar_video", lambda v, t="": videos.append(t))
    monkeypatch.setattr(nota, "subir_a_youtube", lambda v, g: subidas.append(v) or "x")
    d = tmp_path / "2026-11-18-0940-nota.json"
    d.write_text(json.dumps({"palabras": 170, "tema": "nvidia",
                             "historias": [{"titulo": "Nvidia busca CEO", "link": "https://elpais.com/n"}],
                             "guion": {"titulo": "Nvidia busca nuevo CEO sin Jensen Huang", "gancho": "g"}}))
    nota.entregar_a_mano(d, Path("v.mp4"), "nvidia")
    textos = [m["text"] for m in tg.mensajes()]
    assert not subidas and "No lo subi" in videos[-1]
    assert any("Nvidia busca nuevo CEO sin Jensen Huang" in t for t in textos)
    assert any("Fuentes: https://elpais.com/n" in t and "sintetico" in t for t in textos)
    assert "subir:2026-11-18-0940-nota" in tg.botones()
    assert orq.franjas.subidas_hoy() == 0
    assert orq.franjas.publicadas_de(nota.config.ahora())[-1]["origen"] == "a mano"


def test_notavideo_no_gasta_cupo(tg, monkeypatch):
    corridas = []
    monkeypatch.setattr(orq, "correr", lambda c, avisar=True: corridas.append(c) or True)
    monkeypatch.setattr(orq.franjas, "cupo_para_nota", lambda e: 0)   # dia lleno
    tg.escribe("/notavideo sismo en Oaxaca")
    orq.atender_telegram({"franjas": {}})
    assert corridas and corridas[0][-2:] == ["sismo en Oaxaca", "--solo-video"]


def test_nota_sin_cupo_sugiere_notavideo(tg, monkeypatch):
    monkeypatch.setattr(orq, "correr", lambda c, avisar=True: pytest.fail("no debia correr"))
    monkeypatch.setattr(orq.franjas, "cupo_para_nota", lambda e: 0)
    tg.escribe("/nota sismo en Oaxaca")
    orq.atender_telegram({"franjas": {}})
    assert "/notavideo" in tg.mensajes()[-1]["text"]


def test_opciones_de_notavideo_siguen_sin_subir(tg, monkeypatch):
    monkeypatch.setattr(nota, "buscar_tema", lambda t: nota.agrupar([dict(x) for x in RESULTADOS], nota.terminos(t)))
    monkeypatch.setattr(nota.guion, "llamar_llm", lambda *a, **k: "{}")

    class A(Args):
        solo_video = True
    assert nota.construir(A) is None
    assert "/notavideo" in tg.mensajes()[-1]["text"]
    tg.toca(tg.botones()[0])
    assert telegram.recoger(texto_libre=True)["accion"] == "nota_video"


# ------------------------------------------------------------------ lo que pediste
def test_el_guionista_sabe_que_pediste(monkeypatch):
    prompts = []
    monkeypatch.setattr(nota.guion, "llamar_llm", lambda sistema, usuario, *a, **k: prompts.append(usuario) or "{}")
    mat = [{"n": 1, "seccion": "MUNDO", "titular": "Foto oficial de Sheinbaum junto a Trump, Putin y Xi",
            "entradilla": "", "cuerpo_del_articulo": "x " * 80}]
    nota.escribir_guion(mat, sin_verificar=True, titulo="t", pedido="Putin en APEC 2026")
    assert prompts and prompts[0].startswith('LO QUE PIDIO EL EDITOR: "Putin en APEC 2026"')


def test_con_enlace_no_hay_pedido():
    assert nota.pedido_del_editor("https://elpais.com/x") == ""


def test_busqueda_con_errata_y_palabras_sueltas_prueba_variantes(monkeypatch):
    """'sheinbuan vs DEA y CIA' no trae nada tal cual: se reintenta sin el ruido."""
    import aggregate
    pedidas = []

    def fetch(url, *a, **k):
        pedidas.append(url)
        return url

    def parse(url, fuente):
        # solo responde cuando la consulta ya no trae la errata
        return [dict(x) for x in RESULTADOS] if "sheinbuan" not in url else []

    monkeypatch.setattr(aggregate, "fetch", fetch)
    monkeypatch.setattr(aggregate, "parse_feed", parse)
    grupos = nota.buscar_tema("sheinbuan vs DEA y CIA")
    assert grupos and len(pedidas) >= 2
    assert nota.consultas("sheinbuan vs DEA y CIA")[:2] == ["sheinbuan vs DEA y CIA", "sheinbuan dea cia"]
