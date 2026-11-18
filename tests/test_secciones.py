"""Seccion y region: casos que motivaron el cambio, la revision con IA y la medicion."""
import json
from pathlib import Path

import pytest

import secciones

ORO = json.loads((Path(__file__).resolve().parent.parent / "herramientas" / "secciones-oro.json")
                 .read_text(encoding="utf-8"))


@pytest.mark.parametrize("titulo,esperado", [
    ("El FBI alerta por ARTEX, una IA que podría acelerar los ciberataques", "ciencia"),
    ("Muere motociclista tras percance en Prolongación Colón en Tlaquepaque", "seguridad"),
    ("Filas de más de 2 horas de espera para cruzar a Calexico este lunes", "migracion"),
    ("Tribunal de Tijuana condena a exfuncionario por peculado", "justicia"),
    ("Resultados del sorteo Tris hoy 17 de noviembre", "industria"),
])
def test_casos_que_fallaban(titulo, esperado):
    assert secciones.clasificar(titulo)[0] == esperado


@pytest.mark.parametrize("titulo,fuente,esperado", [
    ("Irán ataca sistema de radar militar de EU en Baréin", "mx", "mundo"),
    ("Sheinbaum inaugura nueva era México-China tras su encuentro con Xi Jinping", "mx", "mx"),
    ("Pierden su patrimonio por un cortocircuito", "mx", "mx"),
    ("Isolated tribe emerges", "uk", "mundo"),
])
def test_region_por_contenido(titulo, fuente, esperado):
    assert secciones.region(titulo, "", fuente) == esperado


def test_politica_de_otro_pais_es_mundo():
    assert secciones.clasificar("Trump nominates Chris LaNeve as army chief", "", "uk") == ("mundo", "mundo")


def test_no_empeora_contra_las_250_clasificadas_a_mano():
    """Red de seguridad: si un cambio de palabras baja de aqui, algo se rompio."""
    t = r = 0
    for n in ORO:
        sec, reg = secciones.clasificar(n["title"], n["excerpt"], n["region_fuente"])
        t += n["temas"] == "*" or sec in n["temas"]
        r += reg in n["regiones"]
    assert t / len(ORO) >= 0.88, f"seccion {t}/{len(ORO)}"
    assert r / len(ORO) >= 0.96, f"region {r}/{len(ORO)}"


def test_ia_valida_inventada_y_politica_de_fuera():
    def llm(sis, usr):
        return json.dumps({"r": [{"i": 0, "s": "economia", "g": "mundo"}, {"i": 1, "s": "politica", "g": "mundo"},
                                 {"i": 2, "s": "inventada", "g": "mx"}]})
    items = [{"id": "a", "title": "Nvidia cae"}, {"id": "b", "title": "Trump en Asia"}, {"id": "c", "title": "x"}]
    r = secciones.con_ia(items, llm)
    assert r["a"] == ("economia", "mundo") and r["b"] == ("mundo", "mundo") and "c" not in r


def test_ia_usa_cache():
    llamadas = []

    def llm(sis, usr):
        llamadas.append(1)
        return json.dumps({"r": [{"i": 0, "s": "salud", "g": "mx"}]})
    secciones.con_ia([{"id": "a", "title": "x"}], llm)
    secciones.con_ia([{"id": "a", "title": "x"}], llm)
    assert len(llamadas) == 1


def test_ia_caida_no_truena():
    def falla(sis, usr):
        raise RuntimeError("sin red")
    assert secciones.con_ia([{"id": "z", "title": "y"}], falla) == {}


def test_refinar_solo_las_mejores_en_una_llamada():
    items = [{"id": f"i{k}", "title": f"Noticia {k}", "link": f"l{k}", "source_name": "M", "weight": 4.0,
              "also": [], "tags": ["industria"], "region": "mx", "published": "2026-11-18T10:00:00Z",
              "image": ""} for k in range(30)]
    vistos = []

    def llm(sis, usr):
        n = usr.count("\n") + 1
        vistos.append(n)
        return json.dumps({"r": [{"i": i, "s": "salud", "g": "mundo"} for i in range(n)]})
    assert secciones.refinar(items, n=25, llamar=llm) == 25 and vistos == [25]
    assert sum(1 for x in items if x.get("seccion_por") == "ia" and x["region"] == "mundo") == 25


def test_el_radar_guarda_seccion_y_regiones(monkeypatch):
    import aggregate
    from datetime import datetime, timezone
    rss = """<?xml version="1.0"?><rss><channel>
<item><title>Irán ataca radar de EU en Baréin</title><link>https://ej.mx/1</link>
<pubDate>Tue, 18 Nov 2026 10:00:00 GMT</pubDate><description>Ataque.</description></item>
<item><title>Sheinbaum presenta reforma electoral</title><link>https://ej.mx/2</link>
<pubDate>Tue, 18 Nov 2026 11:00:00 GMT</pubDate><description>En Palacio Nacional.</description></item>
</channel></rss>""".encode("utf-8")
    monkeypatch.setattr(aggregate, "fetch", lambda url, retries=2: rss)
    fijo = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(aggregate, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: fijo)}))
    src = [{"name": "Medio MX", "short": "MMX", "url": "https://ej.mx/rss", "weight": 4, "lang": "es",
            "region": "mx", "kind": "news", "mirror": False}]
    items, _ = aggregate.build(src, 2)
    r = {i["title"][:10]: (i["tags"][0], i["region"], i["region_fuente"]) for i in items}
    assert r["Irán ataca"] == ("mundo", "mundo", "mx")
    assert r["Sheinbaum "] == ("politica", "mx", "mx")
    assert all("updated" in i for i in items)
