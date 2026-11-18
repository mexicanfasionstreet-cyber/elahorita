"""Fotos de fondo: solo con licencia libre, con credito, y nunca la del medio."""
import json

import capsula
import fotos
import publicar


def wiki(paginas_es=None, commons=None, busqueda=None):
    """Respuestas falsas de Wikipedia y Commons."""
    llamadas = []

    def llamar(api, params):
        llamadas.append((api, params))
        if "commons" in api:
            return {"query": {"pages": [{"imageinfo": [commons]}]}} if commons else {"query": {"pages": []}}
        if "es.wikipedia" in api:
            if "generator" in params:
                return {"query": {"pages": busqueda or []}}
            return {"query": {"pages": paginas_es or [{"missing": True}]}}
        return {"query": {"pages": [{"missing": True}]}}
    llamar.llamadas = llamadas
    return llamar


def ii(licencia="CC BY-SA 4.0", ancho=2000, artista='<a href="x">NVIDIA Corp</a>', nonfree="false"):
    return {"url": "https://upload.wikimedia.org/a.jpg", "thumburl": "https://upload.wikimedia.org/1280px-a.jpg",
            "width": ancho, "descriptionurl": "https://commons.wikimedia.org/wiki/File:a.jpg",
            "extmetadata": {"LicenseShortName": {"value": licencia}, "Artist": {"value": artista},
                            "NonFree": {"value": nonfree}}}


def test_foto_libre_con_credito():
    info = fotos.buscar("Jensen Huang", wiki([{"title": "Jensen Huang", "pageimage": "Jensen_Huang.jpg"}], ii()))
    assert info["url"].endswith("1280px-a.jpg")
    assert info["credito"] == "NVIDIA Corp (CC BY-SA 4.0), Wikimedia Commons"


def test_licencia_no_libre_se_descarta():
    pag = [{"title": "X", "pageimage": "x.jpg"}]
    assert fotos.buscar("X", wiki(pag, ii(licencia="Fair use"))) is None
    assert fotos.buscar("X", wiki(pag, ii(nonfree="true"))) is None
    assert fotos.buscar("X", wiki(pag, ii(licencia="Public domain"))) is not None


def test_logos_mapas_y_fotos_chicas_no():
    assert fotos.buscar("Nvidia", wiki([{"title": "Nvidia", "pageimage": "Nvidia_logo.svg"}], ii())) is None
    assert fotos.buscar("X", wiki([{"title": "X", "pageimage": "x.jpg"}], ii(ancho=400))) is None


def test_busqueda_que_trae_a_otra_persona_no_cuenta():
    llamar = wiki(busqueda=[{"title": "Lionel Messi", "pageimage": "messi.jpg"}], commons=ii())
    assert fotos.buscar("Hakeem Jeffries", llamar) is None
    llamar = wiki(busqueda=[{"title": "Hakeem Jeffries (político)", "pageimage": "hj.jpg"}], commons=ii())
    assert fotos.buscar("Hakeem Jeffries", llamar) is not None


def test_tema_sensible_va_sin_foto():
    llamar = wiki([{"title": "Tijuana", "pageimage": "tj.jpg"}], ii())
    h = fotos.para_historias([{"sensible": "violencia"}, {}],
                             {"notas": [{"foto": "Tijuana"}, {"foto": "Tijuana"}]}, llamar)
    assert h[0]["foto"] == {} and h[1]["foto"]["url"]


def test_sin_red_no_truena():
    assert fotos.buscar("Jensen Huang") is None      # conftest corta la red


def test_credito_de_fotos_en_la_descripcion(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSICA_CREDITO", "Pista X de Autor Y")
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"guion": {"titulo": "t"}, "historias": [
        {"link": "https://a", "foto": {"credito": "NVIDIA Corp (CC BY-SA 4.0), Wikimedia Commons"}},
        {"link": "https://b", "foto": {}}]}))
    desc = publicar.textos(tmp_path / "v.mp4", g)[1]
    assert "Fotos: NVIDIA Corp (CC BY-SA 4.0), Wikimedia Commons" in desc
    assert "Música: Pista X de Autor Y" in desc


def test_sin_foto_libre_va_el_fondo_de_diseno(tmp_path):
    im = capsula.foto("", tmp_path / "x.img", "POLITICA")
    assert im.size == (capsula.ANCHO, capsula.ALTO)


def test_el_montaje_ya_no_usa_la_foto_del_medio():
    fuente = (capsula.RAIZ / "capsula.py").read_text(encoding="utf-8")
    assert 'get("imagen_url")' not in fuente and '.get("image", "")\n        return' not in fuente
