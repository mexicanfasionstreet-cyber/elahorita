"""Vigilante: avisa si el robot deja de correr o falla seguido, y cuando se recupera."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("vigilante", RAIZ / "herramientas" / "vigilante.py")
vig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vig)

AHORA = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)      # 10:00 en Tijuana


def pasada(hace_min, conclusion="success", status="completed", n=0):
    t = AHORA - timedelta(minutes=hace_min)
    iso = t.isoformat().replace("+00:00", "Z")
    return {"created_at": iso, "updated_at": (t + timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            "status": status, "conclusion": conclusion if status == "completed" else None,
            "html_url": f"https://github.com/x/actions/runs/{n or hace_min}"}


def cada5(desde, hasta, conclusion="success"):
    return [pasada(m, conclusion) for m in range(desde, hasta, 5)]


def test_todo_bien_no_hace_nada():
    r = vig.revisar(cada5(2, 200), AHORA)
    assert r["avisos"] == [] and r["despachar"] is False


def test_silencio_despacha_y_avisa():
    r = vig.revisar(cada5(42, 300), AHORA)
    assert r["despachar"] is True
    assert len(r["avisos"]) == 1 and "no ha corrido en 42 min" in r["avisos"][0]
    assert "09:18" in r["avisos"][0]          # ultima pasada en hora de Tijuana


def test_silencio_largo_despacha_pero_no_repite_fuera_de_ventana():
    r = vig.revisar(cada5(95, 400), AHORA)    # 95 min: entre el aviso de 30 y el de 2 h
    assert r["despachar"] is True and r["avisos"] == []


@pytest.mark.parametrize("minutos,toca", [(29, False), (30, True), (59, True), (60, False), (125, True),
                                          (300, False), (370, True), (720, True), (800, False), (1445, True)])
def test_ventanas_de_aviso(minutos, toca):
    assert vig.toca_avisar(minutos) is toca


def test_si_hay_una_en_curso_no_despacha():
    r = vig.revisar([pasada(40, status="in_progress")] + cada5(45, 300), AHORA)
    assert r["despachar"] is False and r["avisos"] == []


def test_fallas_seguidas_avisan_con_enlace():
    pasadas = [pasada(m, "failure", n=1000 + m) for m in range(3, 38, 5)] + cada5(38, 300)
    r = vig.revisar(pasadas, AHORA)
    assert len(r["avisos"]) == 1
    assert "Las ultimas 7 pasadas del robot fallaron" in r["avisos"][0] and "runs/1003" in r["avisos"][0]
    assert r["despachar"] is False


def test_dos_fallas_no_avisan():
    r = vig.revisar([pasada(3, "failure"), pasada(8, "failure")] + cada5(13, 300), AHORA)
    assert r["avisos"] == []


def test_canceladas_no_cuentan_como_falla():
    pasadas = [pasada(3, "cancelled"), pasada(8, "failure"), pasada(13, "failure")] + cada5(18, 300)
    assert vig.revisar(pasadas, AHORA)["avisos"] == []


def test_recupera_tras_fallas():
    pasadas = [pasada(3)] + [pasada(m, "failure") for m in range(8, 40, 5)] + cada5(40, 300)
    r = vig.revisar(pasadas, AHORA)
    assert any("volvio a correr bien" in a and "fallas seguidas" in a for a in r["avisos"])


def test_recupera_tras_silencio():
    r = vig.revisar([pasada(4)] + cada5(80, 300), AHORA)
    assert any("volvio a correr bien" in a and "sin pasadas" in a for a in r["avisos"])


def test_recuperacion_vieja_no_se_repite():
    pasadas = cada5(2, 60) + [pasada(m, "failure") for m in range(60, 90, 5)] + cada5(90, 300)
    assert vig.revisar(pasadas, AHORA)["avisos"] == []


def test_mensajes_sin_html_roto():
    from conftest import html_roto
    pasadas = [pasada(m, "failure", n=7) for m in range(33, 68, 5)] + cada5(68, 300)
    for aviso in vig.revisar(pasadas, AHORA)["avisos"]:
        assert not html_roto(aviso)
