"""Guion: seguimientos, notas sin material, reservas y reintento del verificador."""
import json
import sys

import pytest

import guion

FILAS = {k: {"title": t, "link": k, "seccion": "cultura", "medios": 5, "score": 90, "excerpt": ""}
         for k, t in [("frida", "Frida Kahlo subasta frenada"), ("nvidia", "Nvidia no restituira a Huang"),
                      ("ine", "Renuncian titulares del INE"), ("fen", "China rechaza señalamientos de EU")]}
TEXTO = {"frida": "", "nvidia": "palabra " * 400, "ine": "", "fen": "palabra " * 300}


@pytest.fixture
def correr(monkeypatch, tmp_path):
    lecturas, prompts = [], []

    def art(u):
        lecturas.append(u)
        return {"texto": TEXTO[u], "descripcion": "", "palabras": len(TEXTO[u].split())}

    def llm(sis, usr, timeout=120):
        if "editor de datos" in sis:
            return json.dumps({"problemas": [], "guion_corregido": None})
        prompts.append(usr)
        return json.dumps({"gancho": "g", "gancho_pantalla": "G",
                           "notas": [{"kicker": "X", "pantalla": "p", "texto": "t."}], "cierre": "c"})

    monkeypatch.setattr(guion, "articulo", art)
    monkeypatch.setattr(guion, "historia_por_link", lambda l: dict(FILAS[l]) if l in FILAS else None)
    monkeypatch.setattr(guion, "asegurar_imagen", lambda f: f)
    monkeypatch.setattr(guion, "llamar_llm", llm)
    monkeypatch.setattr("time.sleep", lambda s: None)
    salida = tmp_path / "g.json"

    def run(*args):
        lecturas.clear()
        prompts.clear()
        monkeypatch.setattr(sys, "argv", ["guion.py", *args, "--json", str(salida)])
        guion.main()
        return json.loads(salida.read_text()), lecturas, prompts
    return run


def test_primera_sin_material_se_quita(correr):
    d, lecturas, prompts = correr("--link", "frida", "--link", "nvidia")
    assert [h["link"] for h in d["historias"]] == ["nvidia"]
    assert "Nvidia" in prompts[0] and "Frida" not in prompts[0]
    assert lecturas.count("frida") == 2                      # un reintento antes de quitarla


def test_reserva_cuando_ninguna_tiene_material(correr):
    d, _, _ = correr("--link", "frida", "--link", "ine", "--reserva", "nvidia", "--reserva", "fen")
    assert [h["link"] for h in d["historias"]] == ["nvidia"]


def test_sin_material_en_ninguna_se_queda_la_primera(correr):
    d, _, _ = correr("--link", "frida", "--reserva", "ine")
    assert [h["link"] for h in d["historias"]] == ["frida"]


def test_seguimiento_en_el_prompt(correr):
    _, _, prompts = correr("--link", "nvidia", "--previo", "Huang dejo Nvidia")
    assert "SEGUIMIENTO" in prompts[0] and "Huang dejo Nvidia" in prompts[0]


def test_verificador_reintenta_si_el_json_viene_roto(monkeypatch):
    respuestas = iter(['{"problemas": ["x" "y"], ',
                       json.dumps({"problemas": ["frase :: motivo"],
                                   "guion_corregido": {"gancho": "g2", "notas": [], "cierre": "c"}})])
    monkeypatch.setattr(guion, "llamar_llm", lambda s, u, timeout=120: next(respuestas))
    problemas, corregido = guion.verificar({"gancho": "g"}, [])
    assert problemas == ["frase :: motivo"] and corregido["gancho"] == "g2"


def test_prohibido_delatar_el_material():
    assert "el material" in guion.SISTEMA and "el titular" in guion.SISTEMA
