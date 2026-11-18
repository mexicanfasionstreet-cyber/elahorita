"""Temas sensibles: nunca salen solos; sin respuesta, sale la siguiente no sensible."""
import json
from datetime import timedelta

import pytest

import franjas
import guion
import orquestador as orq
import publicar
import secciones
from conftest import html_roto, noticia, utc_de


@pytest.mark.parametrize("titulo,esperado", [
    ("Abandonan cabeza humana en una cubeta de plástico en Culiacán", "grafica"),
    ("Hallan fosa clandestina con 12 cuerpos en Jalisco", "grafica"),
    ("Depardieu asume condena por agredir sexualmente a dos mujeres", "sexual_menores"),
    ("Sentencian a líder de la CTM en Quintana Roo por trata de personas", "sexual_menores"),
    ("Matan a niña de 8 años en ataque armado en Guanajuato", "sexual_menores"),
    ("Joven se quitó la vida en Mexicali; Fiscalía investiga", "suicidio"),
    # no sensibles: un homicidio sin esos elementos, usos legales de "violacion", menores sin dano
    ("Matan en Costa Rica a periodista que denunciaba casos de narcotráfico", ""),
    ("Muere motociclista tras percance en Tlaquepaque", ""),
    ("Violación de derechos humanos: CNDH emite recomendación", ""),
    ("Juez acusa violación al debido proceso", ""),
    ("Niños de Tijuana ganan olimpiada de matemáticas", ""),
])
def test_detector_por_palabras(titulo, esperado):
    assert secciones.sensible(titulo) == esperado


def test_ia_marca_sensibles_y_descarta_categorias_inventadas():
    def llm(sis, usr):
        return json.dumps({"r": [{"i": 0, "s": "seguridad", "g": "mx", "k": "grafica"},
                                 {"i": 1, "s": "seguridad", "g": "mx", "k": "morbo"}]})
    r = secciones.con_ia([{"id": "a", "title": "x"}, {"id": "b", "title": "y"}], llm)
    assert r["a"][2] == "grafica" and r["b"][2] == ""


def test_cache_de_antes_se_vuelve_a_preguntar():
    secciones.CACHE_IA.write_text(json.dumps({"a": ["seguridad", "mx"]}))
    llamadas = []

    def llm(sis, usr):
        llamadas.append(1)
        return json.dumps({"r": [{"i": 0, "s": "seguridad", "g": "mx", "k": "suicidio"}]})
    assert secciones.con_ia([{"id": "a", "title": "x"}], llm)["a"][2] == "suicidio" and llamadas


def test_refinar_marca_por_ia_o_por_palabras():
    items = [{"id": "a", "title": "Abandonan cabeza humana en Culiacán", "link": "a", "source_name": "M",
              "weight": 4.0, "also": [], "tags": ["industria"], "published": "2026-11-18T10:00:00Z", "image": ""}]

    def llm(sis, usr):          # la IA no la marca; las palabras si
        return json.dumps({"r": [{"i": 0, "s": "seguridad", "g": "mx", "k": ""}]})
    secciones.refinar(items, llamar=llm)
    assert items[0]["sensible"] == "grafica"


# ------------------------------------------------------------------ franja
TARDE = franjas.franja_por_nombre("tarde")
CLAVE = "2026-11-18-tarde"


@pytest.fixture
def franja(monkeypatch, latest, reloj, tg):
    """Corre la franja de la tarde con estas noticias; devuelve (estado, videos, ahora)."""
    monkeypatch.setattr(orq, "correr", lambda c, avisar=True: True)
    monkeypatch.setattr(secciones, "refinar", lambda items, **k: 0)
    videos = []
    monkeypatch.setattr(orq, "armar_video", lambda links, previos=(), **k: videos.append((list(links), k)) or True)

    def correr(items):
        ahora = reloj(2026, 11, 18, 15, 10)
        latest(items)
        estado = {"franjas": {}}
        orq.correr_franja(estado, CLAVE, TARDE, ahora)
        return estado, videos, ahora
    return correr


SENSIBLE = noticia("Hallan fosa clandestina con 12 cuerpos en Jalisco", "s/1", utc_de(2026, 11, 18, 14),
                   medios=["A", "B", "C", "D"])
NORMAL = noticia("Sheinbaum presenta reforma electoral", "n/1", utc_de(2026, 11, 18, 13))
OTRA = noticia("Banxico mantiene la tasa de interés en Monterrey", "n/2", utc_de(2026, 11, 18, 13, 30))


def test_sensible_no_sale_sola_y_pregunta(franja, tg):
    estado, videos, _ = franja([SENSIBLE, NORMAL])
    texto = tg.mensajes()[-1]["text"]
    assert not videos and estado["pendiente"]["motivo"] == "sensible"
    assert "tema sensible" in texto and "⚠️ sensible: violencia grafica" in texto and not html_roto(texto)
    assert "Sheinbaum presenta reforma electoral" in texto           # la alternativa
    assert [o["link"] for o in estado["pendiente"]["sin_respuesta"]] == ["n/1"]


def test_sin_respuesta_sale_la_no_sensible(franja):
    estado, videos, ahora = franja([SENSIBLE, NORMAL])
    orq.revisar_pendiente(estado, ahora + timedelta(minutes=31))
    assert videos[-1][0] == ["n/1"] and "sin respuesta" in estado["franjas"][CLAVE]


def test_si_la_apruebas_sale_la_sensible(franja, tg):
    estado, videos, _ = franja([SENSIBLE, NORMAL])
    tg.toca(f"pub:{estado['pendiente']['lote']}:n1")
    orq.atender_telegram(estado)
    assert videos[-1][0] == ["s/1"] and "elegiste" in estado["franjas"][CLAVE]


def test_solo_sensibles_sin_respuesta_no_sale_nada(franja, tg):
    estado, videos, ahora = franja([SENSIBLE])
    assert "no hay opcion sin tema sensible" in tg.mensajes()[-1]["text"]
    orq.revisar_pendiente(estado, ahora + timedelta(minutes=31))
    assert not videos and "solo sensibles" in estado["franjas"][CLAVE]


def test_caso_especial_sin_respuesta_evita_la_sensible(franja):
    grande_sensible = noticia("Masacre en bar de Celaya deja 11 muertos", "g/1", utc_de(2026, 11, 18, 14),
                              medios=list("ABCDEFGHIJKL"))
    grande = noticia("Renuncia el secretario de Hacienda Ramírez", "g/2", utc_de(2026, 11, 18, 14),
                     medios=list("MNOPQRSTUVWX"))
    estado, videos, ahora = franja([grande_sensible, grande])
    assert estado["pendiente"]["motivo"] == "especial"
    orq.revisar_pendiente(estado, ahora + timedelta(minutes=31))
    assert videos[-1][0] == ["g/2"]


def test_sin_sensibles_publica_solo_y_las_reservas_nunca_son_sensibles(franja):
    menor = noticia("Hallan fosa clandestina en Zacatecas", "s/1", utc_de(2026, 11, 18, 12, 5))
    tercera = noticia("Profeco revisa precios del Buen Fin en Tijuana", "n/3", utc_de(2026, 11, 18, 12, 10))
    estado, videos, _ = franja([NORMAL, OTRA, menor, tercera])
    assert videos and "s/1" not in videos[-1][0]
    assert "s/1" not in videos[-1][1]["reservas"] and "n/3" in videos[-1][1]["reservas"]
    assert estado["franjas"][CLAVE].startswith("automatica")


# ------------------------------------------------------------------ redaccion y YouTube
def test_reglas_de_redaccion_cuidadosa():
    assert "nada de detalles graficos" in guion.SISTEMA
    assert "800 911 2000" in guion.SISTEMA and "nunca el metodo" in guion.SISTEMA
    assert "menores victimas" in guion.SISTEMA
    assert "800 911 2000" in guion.SISTEMA_VERIFICADOR       # el verificador no la borra


def test_descripcion_lleva_linea_de_ayuda_si_es_suicidio(tmp_path):
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"guion": {"gancho": "x", "gancho_pantalla": "X"},
                             "historias": [{"link": "https://a.mx/1", "sensible": "suicidio"}]}))
    _, desc = publicar.textos(tmp_path / "v.mp4", g)
    assert "800 911 2000" in desc
    g.write_text(json.dumps({"guion": {"gancho": "x"}, "historias": [{"link": "https://a.mx/1", "sensible": ""}]}))
    assert "800 911 2000" not in publicar.textos(tmp_path / "v.mp4", g)[1]
