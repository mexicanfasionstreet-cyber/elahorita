"""Plan de tomas de cada segmento: que imagen va en pantalla y cuando.

Antes cada nota era una sola imagen fija (hasta 50 s). Ahora cada nota se parte
en tomas de 3 a 5 s que se alternan:

    principal  la diapositiva con el titular (foto + caja), zoom que entra o sale
    limpia     la misma foto sin caja, con paneo lateral
    foto2      la segunda foto libre de la nota (lugar, institucion), con paneo
    dato       tarjeta con la cifra o el hecho clave, en el momento en que la
               voz lo dice (tiempos de Whisper / edge-tts)

Un dato que no se encuentra en lo narrado no sale: asi nunca aparece en
pantalla algo que la voz (y el verificador) no dijo.

Todo aqui es calculo puro (sin imagenes ni ffmpeg) para poder probarlo.
"""
from __future__ import annotations

import math
import re
import unicodedata

TOMA_MAX = 5.0          # ninguna toma dura mas que esto
TOMA_MIN = 1.6          # una toma mas corta que esto se pega a la anterior
DATO_DUR = 3.0          # lo que dura una tarjeta de dato en pantalla
DATO_SEPARACION = 4.0   # entre el inicio de una tarjeta y el de la siguiente
DATO_DESDE = 2.2        # la primera toma de la nota (con su titular) va primero
DATO_ANTES = 0.25       # la tarjeta entra un poco antes de que la voz lo diga
MAX_DATOS = 3

_VACIAS = {"de", "del", "la", "las", "el", "los", "en", "y", "a", "al", "un", "una",
           "por", "con", "que", "se", "su", "sus", "para", "mas", "es", "lo"}


def _tok(texto):
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"(?<=\d)[,.](?=\d{3}\b)", "", t)         # 1,500 -> 1500
    return re.findall(r"[a-z0-9]+", t)


def _clave(dato):
    """Palabras del dato que identifican cuando se dice: cifras primero."""
    toks = _tok(dato)
    cifras = [t for t in toks if t.isdigit()]
    resto = [t for t in toks if not t.isdigit() and t not in _VACIAS and len(t) >= 3]
    return cifras + sorted(resto, key=len, reverse=True)


def momento_del_dato(dato, palabras):
    """Segundo (dentro del segmento) en que la voz dice el dato, o None.

    `palabras` son las del manifiesto de voz: {"texto", "t0"}. Cuenta como dicho
    si la palabra clave principal aparece y, en las siguientes palabras, al
    menos la mitad de las demas claves.
    """
    claves = _clave(dato)
    if not claves or not palabras:
        return None
    dichas = [(_tok(p.get("texto"))[:1] or [""])[0] for p in palabras]
    largo = len(_tok(dato)) + 4
    necesarias = max(1, math.ceil(len(claves) / 2))
    for i, w in enumerate(dichas):
        if w != claves[0]:
            continue
        ventana = set(dichas[max(0, i - largo):i + largo])
        if sum(c in ventana for c in claves) >= necesarias:
            return float(palabras[i].get("t0", 0.0))
    return None


def _partir(t0, t1, tipos, motor):
    """Rellena [t0, t1] con tomas de hasta TOMA_MAX s, alternando tipos."""
    hueco = t1 - t0
    if hueco <= 0.01:
        return []
    n = max(1, math.ceil(hueco / TOMA_MAX - 1e-9))
    while n > 1 and hueco / n < TOMA_MIN:
        n -= 1
    paso = hueco / n
    salida = []
    for k in range(n):
        tipo = tipos[next(motor) % len(tipos)]
        salida.append({"tipo": tipo, "t0": round(t0 + k * paso, 3),
                       "t1": round(t0 + (k + 1) * paso, 3)})
    return salida


def _contador():
    i = 0
    while True:
        yield i
        i += 1


def planear(dur, datos=(), palabras=(), hay_foto=True, hay_foto2=False, es_gancho=False):
    """Lista de tomas {tipo, t0, t1, mov[, dato]} que cubre [0, dur] sin huecos."""
    dur = round(float(dur), 3)
    if es_gancho or dur <= TOMA_MAX:
        return [{"tipo": "principal", "t0": 0.0, "t1": dur,
                 "mov": "golpe" if es_gancho else "acerca"}]

    # tarjetas de dato en el momento en que se dicen, sin encimarse
    tarjetas = []
    for dato in list(datos)[:MAX_DATOS]:
        t = momento_del_dato(dato, palabras)
        if t is None:
            continue
        t = max(DATO_DESDE, t - DATO_ANTES)
        if t > dur - 1.2:
            continue
        if tarjetas and t - tarjetas[-1][0] < DATO_SEPARACION:
            continue
        tarjetas.append((round(t, 3), dato))
    tarjetas.sort()

    # entre tarjetas: titular, foto limpia y segunda foto, alternados
    relleno = ["principal"]
    if hay_foto:
        relleno.append("limpia")
    if hay_foto2:
        relleno.append("foto2")
    motor = _contador()

    tomas, cursor = [], 0.0
    for t, dato in tarjetas:
        fin = min(dur, t + DATO_DUR)
        tomas += _partir(cursor, t, relleno, motor)
        tomas.append({"tipo": "dato", "t0": t, "t1": round(fin, 3), "dato": dato})
        cursor = fin
    tomas += _partir(cursor, dur, relleno, motor)

    # una toma demasiado corta se pega a la anterior
    limpias = []
    for tm in tomas:
        if limpias and tm["t1"] - tm["t0"] < TOMA_MIN and tm["tipo"] != "dato":
            limpias[-1]["t1"] = tm["t1"]
            continue
        limpias.append(tm)
    if limpias:
        limpias[0]["tipo"] = "principal" if limpias[0]["tipo"] != "dato" else "dato"
        limpias[-1]["t1"] = dur

    # movimiento de camara: el titular entra o sale; las fotos se pasean
    giro = {"principal": ["acerca", "aleja"], "limpia": ["derecha", "izquierda"],
            "foto2": ["izquierda", "derecha"], "dato": ["suave"]}
    cuenta = {}
    for tm in limpias:
        k = cuenta.get(tm["tipo"], 0)
        tm["mov"] = giro[tm["tipo"]][k % len(giro[tm["tipo"]])]
        cuenta[tm["tipo"]] = k + 1
    return limpias


def zoompan(mov, frames, ancho, alto, fps):
    """Filtro de ffmpeg para el movimiento de una toma (la imagen entra al doble)."""
    n = max(1, frames)
    centro = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    if mov == "golpe":           # entra de golpe y se asienta: el primer segundo pega
        z = "if(lt(on,14),1.22-0.22*on/14,1.0+0.0005*(on-14))"
        pos = centro
    elif mov == "aleja":
        z = f"1.14-0.12*on/{n}"
        pos = centro
    elif mov == "derecha":
        z = "1.16"
        pos = f"x='(iw-iw/zoom)*on/{n}':y='ih/2-(ih/zoom/2)'"
    elif mov == "izquierda":
        z = "1.16"
        pos = f"x='(iw-iw/zoom)*(1-on/{n})':y='ih/2-(ih/zoom/2)'"
    elif mov == "suave":
        z = f"1.0+0.05*on/{n}"
        pos = centro
    else:                        # acerca
        z = f"1.02+0.12*on/{n}"
        pos = centro
    return (f"scale={ancho * 2}:{alto * 2}:force_original_aspect_ratio=increase,"
            f"crop={ancho * 2}:{alto * 2},"
            f"zoompan=z='{z}':{pos}:d=1:s={ancho}x{alto}:fps={fps},format=yuv420p")
