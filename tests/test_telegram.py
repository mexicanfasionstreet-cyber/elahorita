"""Mesa de edicion: solo tu chat, botones con lote, HTML escapado."""
import json

import pytest

import config
import telegram
from conftest import html_roto


def candidatas_de(prefijo):
    return lambda n=3: [{"title": f"Historia {prefijo}{i} AT&T <x>", "link": f"https://{prefijo}/{i}",
                         "seccion": "politica", "score": 90 - i, "medios": 3, "imagen": True,
                         "horas": 1.0} for i in range(1, 4)]


@pytest.fixture
def dos_listas(tg, reloj, monkeypatch):
    """Lista de las 12:05 y lista de las 15:05; devuelve sus lotes."""
    monkeypatch.setattr(telegram, "candidatas", candidatas_de("a"))
    reloj(2026, 11, 17, 12, 5)
    telegram.mandar_candidatas()
    lote_12 = tg.botones()[0].split(":")[1]
    monkeypatch.setattr(telegram, "candidatas", candidatas_de("b"))
    reloj(2026, 11, 17, 15, 5)
    telegram.mandar_candidatas()
    lote_15 = tg.botones()[0].split(":")[1]
    return lote_12, lote_15


def test_titulares_se_escapan_en_html(tg, reloj, monkeypatch):
    monkeypatch.setattr(telegram, "candidatas", candidatas_de("a"))
    reloj(2026, 11, 17, 12, 5)
    telegram.mandar_candidatas()
    msg = tg.mensajes()[-1]
    assert msg["parse_mode"] == "HTML"
    assert "AT&amp;T &lt;x&gt;" in msg["text"] and not html_roto(msg["text"])


def test_boton_de_lista_vieja_publica_su_propia_historia(tg, dos_listas):
    lote_12, _ = dos_listas
    tg.toca(f"pub:{lote_12}:n1")
    decision = telegram.recoger(texto_libre=True)
    assert decision["accion"] == "publicar"
    assert decision["historia"]["link"] == "https://a/1"      # no la de las 15:05
    assert decision["lote"] == lote_12


def test_boton_formato_viejo_caduca(tg, dos_listas):
    tg.toca("pub:n1")
    assert telegram.recoger(texto_libre=True) is None
    assert "caduco" in tg.mensajes()[-1]["text"]


def test_ninguna_hoy(tg, dos_listas):
    _, lote_15 = dos_listas
    tg.toca(f"pub:{lote_15}:nada")
    assert telegram.recoger(texto_libre=True) == {"accion": "ninguna", "lote": lote_15}


def test_chat_ajeno_se_ignora(tg, dos_listas):
    _, lote_15 = dos_listas
    tg.escribe("/nota hackeame", chat="999")
    tg.toca(f"pub:{lote_15}:n1", chat="999")
    assert telegram.recoger(texto_libre=True) is None


def test_tu_chat_si_funciona(tg):
    tg.escribe("/nota garita Otay")
    assert telegram.recoger(texto_libre=True) == {"accion": "nota_manual", "texto": "garita Otay"}


def test_sin_chat_configurado_no_obedece_a_nadie(tg, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT", "")
    tg.escribe("/nota algo")
    assert telegram.recoger(texto_libre=True) is None


def test_html_roto_se_reenvia_en_texto_plano(tg):
    telegram.mandar("<b>Fallo</b> en AT&T")
    modos = [p.get("parse_mode") for m, p in tg.enviados if m == "sendMessage"]
    assert modos == ["HTML", None]
    assert tg.mensajes()[-1]["text"] == "Fallo en AT&T"


def test_lotes_en_el_mismo_minuto_no_chocan(reloj):
    reloj(2026, 11, 17, 12, 5)
    a = telegram.guardar_lote([{"titulo": "a"}])
    b = telegram.guardar_lote([{"titulo": "b"}])
    assert a != b
    lotes = json.loads(telegram.ESTADO.read_text())["lotes"]
    assert lotes[a]["n1"]["titulo"] == "a" and lotes[b]["n1"]["titulo"] == "b"


def test_boton_subir_asi(tg):
    tg.toca("subir:2026-11-17-1834-nota")
    assert telegram.recoger(texto_libre=True) == {"accion": "subir", "guion": "2026-11-17-1834-nota"}


def test_boton_subir_con_nombre_raro_se_ignora(tg):
    tg.toca("subir:../../etc")
    assert telegram.recoger(texto_libre=True) is None
