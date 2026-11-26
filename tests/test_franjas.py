"""Que se publica en cada franja: ventanas, seguimientos, casos especiales y cupo."""
from datetime import datetime

import pytest

import config
import franjas
from conftest import TZ, noticia, utc_de

AHORA = datetime(2026, 11, 18, 15, 10, tzinfo=TZ)
TARDE = franjas.franja_por_nombre("tarde")


def test_ventanas_de_cada_franja():
    v = {n: franjas.inicio_ventana(franjas.franja_por_nombre(n), AHORA)
         for n in ("madrugada", "manana", "tarde", "noche")}
    assert v["madrugada"] == datetime(2026, 11, 17, 20, 0, tzinfo=TZ)   # 20:00 de ayer
    assert (v["manana"].hour, v["tarde"].hour, v["noche"].hour) == (5, 12, 15)


def test_franja_actual():
    assert franjas.franja_actual(AHORA)[1] == "tarde"
    assert franjas.franja_actual(AHORA.replace(hour=17, minute=5)) is None


@pytest.fixture
def items():
    return [
        noticia("Sheinbaum anuncia reforma electoral en Palacio Nacional", "a/1", utc_de(2026, 11, 18, 13),
                medios=["B", "C", "D"]),
        noticia("Sismo de magnitud 6 sacude Oaxaca y Guerrero", "b/2", utc_de(2026, 11, 18, 9),
                utc_de(2026, 11, 18, 14), medios=["E", "F"]),
        noticia("Banxico recorta la tasa de interés", "c/3", utc_de(2026, 11, 18, 8)),
        noticia("Trump amenaza con aranceles a Canadá", "d/4", utc_de(2026, 11, 18, 12, 30)),
    ]


PUBLICADA_SISMO = [{"cuando": datetime(2026, 11, 18, 8, 30, tzinfo=TZ).isoformat(),
                    "titulo": "Sismo de magnitud 6 sacude Oaxaca", "link": "b/2",
                    "entidades": ["sismo", "oaxaca"]}]


def test_fuera_de_ventana_no_entra(items):
    titulos = [f["title"] for f in franjas.candidatas(items, TARDE, AHORA, [])]
    assert "Banxico recorta la tasa de interés" not in titulos


def test_seguimiento_si_hay_notas_nuevas(items):
    filas = franjas.candidatas(items, TARDE, AHORA, PUBLICADA_SISMO)
    sismo = [f for f in filas if f["link"] == "b/2"]
    assert sismo and sismo[0]["seguimiento_de"].startswith("Sismo")


def test_no_repite_sin_novedad(items):
    items[1]["updated"] = utc_de(2026, 11, 18, 8, 10)       # antes del video de las 08:30
    assert all(f["link"] != "b/2" for f in franjas.candidatas(items, TARDE, AHORA, PUBLICADA_SISMO))


def fila(score, peso):
    return {"score": score, "peso_cobertura": peso, "title": f"t{score}", "link": f"l{score}", "medios": 9}


def test_caso_especial():
    assert not franjas.es_especial([fila(90, 40), fila(80, 20), fila(70, 10)])
    assert franjas.es_especial([fila(90, 40), fila(85, 38), fila(70, 10)])


def test_una_o_dos_notas():
    assert len(franjas.elegir([fila(90, 1), fila(70, 1)])) == 1
    assert len(franjas.elegir([fila(90, 1), fila(85, 1)])) == 2


def test_cupo_de_nota(reloj):
    ahora = reloj(2026, 11, 18, 15, 10)
    estado = {"franjas": {"2026-11-18-madrugada": "x", "2026-11-18-manana": "x"}}
    for i in range(2):
        franjas.registrar_subida(f"v{i}", "t")
    assert franjas.franjas_restantes(estado, ahora) == 2
    assert franjas.cupo_para_nota(estado, ahora) == 2
    for i in range(2):
        franjas.registrar_subida(f"w{i}", "t")
    assert franjas.cupo_para_nota(estado, ahora) == 0


def test_registrar_publicada_guarda_entidades(reloj):
    reloj(2026, 11, 18, 12, 20)
    franjas.registrar_publicada([{"titulo": "Sismo sacude Oaxaca", "link": "b/2"}], "franja-manana")
    guardada = franjas._leer(franjas.PUBLICADAS, [])[0]
    assert guardada["link"] == "b/2" and "oaxaca" in guardada["entidades"]
    assert config.ahora().isoformat(timespec="seconds") == guardada["cuando"]


def test_misma_muerte_en_otro_idioma_no_se_repite(items):
    """BBC en espanol (20:03) y NPR en ingles (05:02) son la misma noticia."""
    items.append(noticia("Andy Taylor, guitarist of new wave icons Duran Duran, dies at 65",
                         "npr/1", utc_de(2026, 11, 18, 12, 30)))
    previa = [{"cuando": datetime(2026, 11, 17, 20, 3, tzinfo=TZ).isoformat(),
               "titulo": "Muere a los 65 años el guitarrista de la banda de pop Duran Duran",
               "link": "bbc/1", "entidades": ["duran", "muere"]}]
    madrugada = franjas.franja_por_nombre("madrugada")
    ahora = datetime(2026, 11, 18, 5, 2, tzinfo=TZ)
    assert any(f["link"] == "npr/1" for f in franjas.candidatas(items, madrugada, ahora, []))
    assert all(f["link"] != "npr/1" for f in franjas.candidatas(items, madrugada, ahora, previa))


def test_seguimiento_reciente_no_sale(items):
    """Contada hace 2 horas: aunque haya notas nuevas, no se repite el tema."""
    reciente = [dict(PUBLICADA_SISMO[0],
                     cuando=datetime(2026, 11, 18, 12, 50, tzinfo=TZ).isoformat())]
    assert all(f["link"] != "b/2" for f in franjas.candidatas(items, TARDE, AHORA, reciente))
