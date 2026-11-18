"""Control por Telegram: /estado, /pausa, /reanudar, /saltar, /ayuda y el resumen diario."""
import json
from datetime import datetime

import pytest

import config
import franjas
import orquestador as orq
import telegram
from conftest import TZ, html_roto


@pytest.fixture
def sin_videos(monkeypatch):
    """Ni franjas ni videos de verdad: se registra lo que se intento."""
    monkeypatch.setattr("sys.argv", ["orquestador.py"])
    hechos = {"franjas": [], "comandos": []}
    monkeypatch.setattr(orq, "correr_franja", lambda e, clave, f, a, prueba=False: hechos["franjas"].append(clave) or True)
    monkeypatch.setattr(orq, "correr", lambda c, avisar=True: hechos["comandos"].append(c) or True)
    monkeypatch.setattr(orq, "revisar_pendiente", lambda e, a: hechos["franjas"].append("pendiente") or True)
    return hechos


def ultimo(tg):
    texto = tg.mensajes()[-1]["text"]
    assert not html_roto(texto), texto
    return texto


# ------------------------------------------------------------------ lectura de comandos
def test_comando_con_nombre_del_bot():
    assert telegram._comando("/pausa@ElAhoritaBot 3h") == ("pausa", "3h")
    assert telegram._comando("hola") == (None, "")


def test_atiende_todos_los_mensajes_en_orden(tg):
    tg.escribe("/estado")
    tg.escribe("/nota sismo en Oaxaca")
    tg.escribe("/pausa hoy")
    acciones = [d["accion"] for d in telegram.recoger_todas()]
    assert acciones == ["estado", "nota_manual", "pausa"]


def test_ayuda_y_comandos_desconocidos(tg):
    tg.escribe("/ayuda")
    tg.escribe("/inventado")
    assert telegram.recoger_todas() == []
    assert sum("/saltar" in m["text"] for m in tg.mensajes()) == 2


def test_chat_ajeno_no_controla_nada(tg):
    tg.escribe("/pausa", chat="999")
    assert telegram.recoger_todas() == []


# ------------------------------------------------------------------ /pausa y /reanudar
@pytest.mark.parametrize("arg,hasta", [
    ("", None),
    ("3h", datetime(2026, 11, 18, 13, 0, tzinfo=TZ)),
    ("2d", datetime(2026, 11, 20, 10, 0, tzinfo=TZ)),
    ("hoy", datetime(2026, 11, 18, 23, 59, tzinfo=TZ)),
    ("mañana", datetime(2026, 11, 19, 23, 59, tzinfo=TZ)),
])
def test_pausa(tg, reloj, arg, hasta):
    ahora = reloj(2026, 11, 18, 10, 0)
    estado = {}
    orq.pausar(estado, arg, ahora)
    guardado = estado["pausa"]["hasta"]
    assert (datetime.fromisoformat(guardado) if guardado else None) == hasta
    assert "pausa" in ultimo(tg) and "/nota sigue funcionando" in ultimo(tg)


def test_pausa_que_no_se_entiende(tg, reloj):
    estado = {}
    orq.pausar(estado, "un ratito", reloj(2026, 11, 18, 10, 0))
    assert "pausa" not in estado and "No entendi" in ultimo(tg)


def test_en_pausa_la_franja_no_sale_pero_nota_si(tg, reloj, sin_videos, monkeypatch):
    reloj(2026, 11, 18, 12, 5)
    monkeypatch.setattr(franjas, "cupo_para_nota", lambda e, a=None: 2)
    orq.guardar({"pausa": {"desde": "x", "hasta": None}, "franjas": {}})
    tg.escribe("/nota choque en la garita")
    orq.main()
    assert sin_videos["comandos"] and sin_videos["comandos"][0][-1] == "choque en la garita"
    orq.main()                                  # siguiente pasada: le toca a la franja
    estado = orq.cargar()
    assert not sin_videos["franjas"] and estado["franjas"]["2026-11-18-manana"].startswith("pausada")


def test_en_pausa_el_caso_pendiente_no_se_publica(tg, reloj, sin_videos):
    reloj(2026, 11, 18, 15, 50)
    orq.guardar({"pausa": {"desde": "x", "hasta": None}, "franjas": {},
                 "pendiente": {"clave": "2026-11-18-tarde", "nombre": "tarde", "lote": "1",
                               "publica_a": "2026-11-18T15:40:00-08:00", "opciones": []}})
    orq.main()
    estado = orq.cargar()
    assert "pendiente" not in sin_videos["franjas"] and estado["franjas"]["2026-11-18-tarde"].startswith("pausada")


def test_la_pausa_se_acaba_sola(tg, reloj, sin_videos):
    reloj(2026, 11, 18, 12, 5)
    orq.guardar({"pausa": {"desde": "x", "hasta": "2026-11-18T12:00:00-08:00"}, "franjas": {}})
    orq.main()
    assert sin_videos["franjas"] == ["2026-11-18-manana"]
    assert any("Se acabo la pausa" in m["text"] for m in tg.mensajes())


def test_reanudar(tg, reloj):
    ahora = reloj(2026, 11, 18, 13, 0)
    estado = {"pausa": {"desde": "x", "hasta": None}, "franjas": {"2026-11-18-manana": "pausada"}}
    orq.reanudar(estado, "", ahora)
    assert "pausa" not in estado and "Sigue la de la tarde" in ultimo(tg)
    orq.reanudar(estado, "", ahora)
    assert "No habia pausa" in ultimo(tg)


# ------------------------------------------------------------------ /saltar
def test_saltar_la_proxima(tg, reloj):
    ahora = reloj(2026, 11, 18, 13, 0)
    estado = {"franjas": {"2026-11-18-madrugada": "x", "2026-11-18-manana": "x"}}
    orq.saltar(estado, "", ahora)
    assert estado["franjas"]["2026-11-18-tarde"].startswith("saltada")
    assert "tarde" in ultimo(tg)


def test_saltar_una_con_nombre_y_su_pendiente(tg, reloj):
    ahora = reloj(2026, 11, 18, 15, 20)
    estado = {"franjas": {}, "pendiente": {"clave": "2026-11-18-tarde"}}
    orq.saltar(estado, "tarde", ahora)
    assert "pendiente" not in estado and estado["franjas"]["2026-11-18-tarde"].startswith("saltada")


def test_saltar_de_noche_es_la_madrugada_de_manana(tg, reloj):
    ahora = reloj(2026, 11, 18, 23, 0)
    estado = {"franjas": {}}
    orq.saltar(estado, "", ahora)
    assert "2026-11-19-madrugada" in estado["franjas"]


def test_saltar_algo_que_no_existe(tg, reloj):
    estado = {"franjas": {}}
    orq.saltar(estado, "siesta", reloj(2026, 11, 18, 13, 0))
    assert estado["franjas"] == {} and "¿Cual?" in ultimo(tg)


# ------------------------------------------------------------------ /estado
def test_estado(tg, reloj, voicebox):
    ahora = reloj(2026, 11, 18, 15, 20)
    franjas.registrar_subida("v1", "t")
    estado = {"franjas": {"2026-11-18-madrugada": "automatica 05:07", "2026-11-18-manana": "fallida 12:40"},
              "pendiente": {"clave": "2026-11-18-tarde", "nombre": "tarde", "publica_a": "2026-11-18T15:40:00-08:00"}}
    voicebox("ok")
    orq.mostrar_estado(estado, "", ahora)
    texto = ultimo(tg)
    assert "✅ automatica" in texto and "❌ fallida" in texto and "esperando tu eleccion" in texto
    assert "Subidas hoy: 1 de 6" in texto and "Voicebox: responde" in texto
    assert "Proxima: noche" in texto


def test_estado_sin_voicebox(tg, reloj):
    orq.mostrar_estado({"franjas": {}}, "", reloj(2026, 11, 18, 9, 0))
    assert "sin configurar" in ultimo(tg)


# ------------------------------------------------------------------ resumen diario
@pytest.fixture
def dia_con_cosas(reloj):
    reloj(2026, 11, 18, 5, 7)
    franjas.registrar_publicada([{"titulo": "Sismo en Oaxaca", "link": "a"}], "franja-madrugada",
                                "https://youtube.com/shorts/x1")
    reloj(2026, 11, 18, 13, 5)
    franjas.registrar_evento("voz_respaldo", "ConnectionRefusedError")
    franjas.registrar_subida("x1", "Sismo")


def test_resumen_no_sale_antes_de_tiempo(tg, reloj, dia_con_cosas):
    estado = {"franjas": {}}
    assert orq.resumen_diario(estado, reloj(2026, 11, 18, 20, 30)) is False
    assert orq.resumen_diario(estado, reloj(2026, 11, 18, 21, 10)) is False   # la noche no ha cerrado


def test_resumen_cuando_cierra_la_noche_y_una_sola_vez(tg, reloj, dia_con_cosas):
    estado = {"franjas": {"2026-11-18-noche": "automatica 20:06"}}
    assert orq.resumen_diario(estado, reloj(2026, 11, 18, 21, 10)) is True
    texto = ultimo(tg)
    assert "Publicado (1)" in texto and "Sismo en Oaxaca" in texto and "shorts/x1" in texto
    assert "Voicebox no respondio" in texto and "Subidas: 1 de 6" in texto
    assert "Sigue: madrugada" in texto
    assert orq.resumen_diario(estado, reloj(2026, 11, 18, 21, 15)) is False


def test_resumen_a_las_22_aunque_la_noche_no_cierre(tg, reloj, dia_con_cosas):
    assert orq.resumen_diario({"franjas": {}}, reloj(2026, 11, 18, 22, 5)) is True


def test_resumen_dia_vacio(tg, reloj):
    orq.resumen_diario({"franjas": {}}, reloj(2026, 11, 18, 22, 5))
    assert "no se publico nada" in ultimo(tg)


# ------------------------------------------------------------------ menu y bitacora
def test_menu_de_comandos_se_registra_una_vez(tg, reloj, sin_videos):
    reloj(2026, 11, 18, 17, 0)
    orq.main()
    orq.main()
    registros = [p for m, p in tg.enviados if m == "setMyCommands"]
    assert len(registros) == 1
    assert {c["command"] for c in json.loads(registros[0]["commands"])} >= {"nota", "estado", "pausa", "saltar"}


def test_voz_de_respaldo_queda_en_la_bitacora(tmp_path, monkeypatch, puerto_cerrado, tg, reloj, tono):
    import subprocess
    import voz
    reloj(2026, 11, 18, 5, 3)
    monkeypatch.setattr(voz, "BUILD", tmp_path / "build")
    monkeypatch.setattr(voz, "con_edge_tts", lambda t, s: subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(tono), str(s)], check=True) and [])
    monkeypatch.setattr(config, "VOICEBOX_URL", puerto_cerrado)
    monkeypatch.setattr(config, "VOICEBOX_PROFILE", "carla-1")
    voz.generar_voz({"_nombre": "x", "gancho": "Hola.", "notas": [], "cierre": "Adios."}, "voicebox")
    assert [e["tipo"] for e in franjas.eventos_de(config.ahora())] == ["voz_respaldo"]


# ------------------------------------------------------------------ migracion del sistema anterior
ESTADO_VIEJO = {"franjas": {"2026-11-17-mediodia": "2026-11-17T12:18:23-08:00",
                            "2026-11-17-tarde": "2026-11-17T15:18:47-08:00",
                            "2026-11-17-noche": "2026-11-17T20:01:24-08:00"}, "videos": []}


def test_migracion_del_estado_viejo(reloj):
    reloj(2026, 11, 17, 23, 25)
    orq.ESTADO.write_text(json.dumps(ESTADO_VIEJO))
    estado = orq.cargar()
    assert estado["franjas"] == {"2026-11-17-manana": "candidatas (sistema anterior) 12:18",
                                 "2026-11-17-tarde": "candidatas (sistema anterior) 15:18",
                                 "2026-11-17-noche": "candidatas (sistema anterior) 20:01"}
    assert estado["resumen"] == "2026-11-17" and "videos" not in estado
    assert orq.migrar(estado) is estado and estado["franjas"]["2026-11-17-tarde"].startswith("candidatas")


def test_primera_pasada_tras_el_merge(tg, reloj, sin_videos):
    """23:25 del dia del merge: nada se publica, no llega resumen, /estado se ve bien."""
    reloj(2026, 11, 17, 23, 25)
    orq.ESTADO.write_text(json.dumps(ESTADO_VIEJO))
    tg.escribe("/estado")
    orq.main()
    textos = [m["text"] for m in tg.mensajes()]
    assert not sin_videos["franjas"] and not any("resumen" in t for t in textos)
    estado_msg = [t for t in textos if "estado</b>" in t][0]
    assert "📋 candidatas (sistema anterior) 12:18" in estado_msg and "Proxima: madrugada, mie 18" in estado_msg
    reloj(2026, 11, 18, 21, 10)                    # al dia siguiente si llega
    estado = orq.cargar()
    estado["franjas"]["2026-11-18-noche"] = "automatica 20:05"
    assert orq.resumen_diario(estado, config.ahora()) is True
