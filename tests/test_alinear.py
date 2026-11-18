"""Tiempos por palabra para la voz de Voicebox: Whisper pone los tiempos, el guion el texto."""
import alinear


def oidas(lista):
    return [(w, t, t + 0.28) for w, t in lista]


GUION = "En San Ysidro, la espera llega a 115 minutos. ¡Así está!"
OIDO = oidas([("en", 0.0), ("san", 0.3), ("isidro", 0.6), ("la", 0.9), ("espera", 1.2), ("llega", 1.5),
              ("a", 1.8), ("ciento", 2.1), ("quince", 2.4), ("minutos", 2.7), ("asi", 3.0), ("esta", 3.3)])


def test_tokens_sin_puntuacion():
    assert alinear.tokens_del_guion(GUION) == ["En", "San", "Ysidro", "la", "espera", "llega", "a", "115",
                                               "minutos", "Así", "está"]


def test_alineacion_con_whisper():
    g = alinear.tokens_del_guion(GUION)
    r, _ = alinear.alinear(g, OIDO, 3.8)
    t = {p["texto"]: p for p in r}
    assert abs(t["minutos"]["t0"] - 2.7) < 1e-6 and abs(t["espera"]["t0"] - 1.2) < 1e-6
    assert 2.08 <= t["115"]["t0"] <= 2.2 and t["115"]["t0"] + t["115"]["dur"] <= 2.71   # oido "ciento quince"
    assert 0.29 < t["Ysidro"]["t0"] < 0.9
    assert all(r[i]["t0"] <= r[i + 1]["t0"] for i in range(len(r) - 1))
    assert [p["texto"] for p in r] == g                    # en pantalla, el texto del guion


def test_palabra_final_no_oida():
    r, _ = alinear.alinear(["Hola", "mundo", "adios"], oidas([("hola", 0.1), ("mundo", 0.5)]), 2.0)
    assert r[2]["t0"] >= 0.78 and r[2]["t0"] + r[2]["dur"] <= 2.0001


def test_sin_transcripcion():
    assert alinear.alinear(["Hola"], [], 2.0) == ([], 0.0)


def test_muletillas_se_ignoran():
    r, prop = alinear.alinear(["Uno", "dos"], oidas([("eh", 0.0), ("uno", 0.4), ("este", 0.8), ("dos", 1.2)]), 1.6)
    assert abs(r[0]["t0"] - 0.4) < 1e-6 and abs(r[1]["t0"] - 1.2) < 1e-6 and prop == 1.0


def test_decodifica_con_ffmpeg(tono):
    muestras = alinear._muestras(tono)
    assert muestras.dtype.name == "float32" and abs(len(muestras) / 16000 - 4.0) < 0.05
