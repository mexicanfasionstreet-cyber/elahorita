"""Titulos de YouTube: los escribe el guionista, se verifican y nunca se aplanan."""
import json

import guion
import publicar


def _textos(tmp_path, g):
    ruta = tmp_path / "g.json"
    ruta.write_text(json.dumps({"guion": g, "historias": []}))
    return publicar.textos(tmp_path / "2026-11-18-franja-manana.mp4", ruta)[0]


def test_usa_el_titulo_del_guionista_tal_cual(tmp_path):
    t = _textos(tmp_path, {"titulo": "La junta de Nvidia busca nuevo CEO y le cierra la puerta a Jensen Huang.",
                           "gancho_pantalla": "NVIDIA SIN HUANG"})
    assert t == "La junta de Nvidia busca nuevo CEO y le cierra la puerta a Jensen Huang"


def test_sin_titulo_usa_el_titular_de_la_primera_nota(tmp_path):
    t = _textos(tmp_path, {"gancho_pantalla": "NVIDIA SIN HUANG",
                           "notas": [{"pantalla": "Nvidia descarta el regreso de Jensen Huang"}]})
    assert t == "Nvidia descarta el regreso de Jensen Huang"


def test_rotulo_en_mayusculas_no_sale_gritando(tmp_path):
    assert _textos(tmp_path, {"gancho_pantalla": "SISMO EN OAXACA"}) == "Sismo en oaxaca"


def test_titulo_largo_se_corta_en_palabra():
    t = publicar.limpiar_titulo("Sheinbaum " + "anuncia un plan nacional " * 8)
    assert len(t) <= 95 and t.endswith("…") and not t[:-1].endswith(" ")


def test_el_verificador_no_se_come_el_titulo():
    antes = {"titulo": "Nvidia busca CEO", "gancho_pantalla": "NVIDIA", "notas": [{"pantalla": "p", "texto": "a"}]}
    corregido = guion.conservar_rotulos(antes, {"gancho": "g", "notas": [{"texto": "b"}]})
    assert corregido["titulo"] == "Nvidia busca CEO" and corregido["notas"][0]["pantalla"] == "p"
    # si el verificador lo corrigio, manda su version
    corregido = guion.conservar_rotulos(antes, {"titulo": "Nvidia evalua CEO", "notas": []})
    assert corregido["titulo"] == "Nvidia evalua CEO"


def test_plantilla_sin_ia_lleva_el_titular_del_medio():
    g = guion.plantilla([{"title": "Cae la Bolsa en Nueva York", "excerpt": "x", "seccion": "economia"}])
    assert guion.completar_rotulos(g)["titulo"] == "Cae la Bolsa en Nueva York"


def test_el_prompt_pide_titulo_y_el_verificador_lo_revisa():
    assert '"titulo"' in guion.SISTEMA and "nunca todo en mayusculas" in guion.SISTEMA
    assert '"titulo"' in guion.SISTEMA_VERIFICADOR
