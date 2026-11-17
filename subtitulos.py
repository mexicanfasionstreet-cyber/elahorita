"""Subtitulos con la palabra activa en pastilla roja, sincronizados al audio.

edge-tts entrega el tiempo de cada palabra, asi que se sabe exactamente cuando se
pronuncia. Se dibuja una banda transparente de 1080x260 por cada estado (una
palabra activa) y se manda a ffmpeg por tuberia a 30 fps; el resultado es un video
con transparencia que capsula.py pega encima de la imagen.

Uso: python subtitulos.py    (lee build/<guion>/voz.json y escribe subtitulos.mp4)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ.parent / ".deps"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ANCHO, ALTO_BANDA = 1080, 260
FPS = 30
Y_BANDA = 1300          # donde se pega la banda sobre el video
LINEA_BASE = 150         # linea base del texto dentro de la banda

ROJO = (225, 6, 0)
BLANCO = (255, 255, 255)

# Se usa la estatica: con la variable, PIL mide distinto de lo que dibuja y los
# subtitulos se salian de cuadro. Archivo Black es el peso 800/900 de la familia.
FUENTE = RAIZ / "marca" / "fuentes" / "ArchivoBlack-Regular.ttf"
TAM_FUENTE = 62
MAX_ANCHO = ANCHO - 180
MAX_PALABRAS = 6


def fuente(tam=TAM_FUENTE, peso=None):
    try:
        return ImageFont.truetype(str(FUENTE), tam)
    except Exception:  # noqa: BLE001
        try:
            return ImageFont.truetype(str(RAIZ / "marca" / "fuentes"
                                          / "Archivo-Variable.ttf"), tam)
        except Exception:  # noqa: BLE001
            return ImageFont.load_default()


def paginas(palabras, por_renglon=5):
    """Agrupa las palabras en renglones cortos; el tamano se ajusta al dibujar."""
    salida, actual = [], []
    for p in palabras:
        if actual and len(actual) >= por_renglon:
            salida.append(actual)
            actual = [p]
        else:
            actual.append(p)
    if actual:
        salida.append(actual)
    return salida


def tamano_que_cabe(bloque, tope=MAX_ANCHO, tam_max=TAM_FUENTE, tam_min=34):
    """Baja el tamano de letra hasta que el renglon quepa en el ancho."""
    for tam in range(tam_max, tam_min - 1, -2):
        f = fuente(tam)
        ancho = sum(f.getlength(p["texto"]) for p in bloque) + f.getlength(" ") * (len(bloque) - 1)
        if ancho <= tope:
            return tam, f, ancho
    f = fuente(tam_min)
    ancho = sum(f.getlength(p["texto"]) for p in bloque) + f.getlength(" ") * (len(bloque) - 1)
    return tam_min, f, ancho


def dibujar(bloque, activa):
    """Banda transparente con el renglon; la palabra `activa` va en pastilla roja."""
    im = Image.new("RGBA", (ANCHO, ALTO_BANDA), (0, 0, 0, 0))
    if not bloque:
        return im
    d = ImageDraw.Draw(im)
    tam, f, ancho_total = tamano_que_cabe(bloque)
    espacios = f.getlength(" ")
    x = (ANCHO - ancho_total) / 2
    for i, p in enumerate(bloque):
        ancho = f.getlength(p["texto"])
        if i == activa:
            d.rounded_rectangle(
                [x - 12, LINEA_BASE - tam - 8, x + ancho + 12, LINEA_BASE + 14],
                radius=10, fill=ROJO)
        d.text((x, LINEA_BASE - tam), p["texto"], font=f, fill=BLANCO)
        x += ancho + espacios
    return im


def estados(segmentos):
    """Lista de (t0, t1, bloque, indice_activo). Los huecos van con bloque vacio."""
    plan, anterior = [], 0.0
    for seg in segmentos:
        if seg["id"] == "cierre" or not seg.get("palabras"):
            continue
        inicio = float(seg["inicio"])
        if inicio > anterior + 0.01:
            plan.append((anterior, inicio, [], -1))
        for bloque in paginas(seg["palabras"]):
            for i, p in enumerate(bloque):
                t0 = float(p["abs"])
                t1 = t0 + max(0.12, float(p.get("dur", 0.3)))
                if i + 1 < len(bloque):
                    t1 = min(t1, float(bloque[i + 1]["abs"]))
                plan.append((t0, t1, bloque, i))
            anterior = max(anterior, float(bloque[-1]["abs"]) + float(bloque[-1].get("dur", 0.3)))
        fin_seg = inicio + float(seg["dur"])
        if fin_seg > anterior:
            plan.append((anterior, min(fin_seg, anterior + 0.25), [], -1))
            anterior = fin_seg
    plan.sort(key=lambda x: x[0])
    return plan


def construir(nombre):
    carpeta = RAIZ / "build" / nombre
    datos = json.loads((carpeta / "voz.json").read_text(encoding="utf-8"))
    segs = datos["segmentos"]
    total = float(datos["total_seg"])
    plan = estados(segs)

    # estados unicos en cache: se dibuja cada uno una vez
    cache, claves = {}, []
    for t0, t1, bloque, activa in plan:
        clave = tuple(p["texto"] for p in bloque) + (activa,)
        if clave not in cache:
            cache[clave] = dibujar(bloque, activa)
            buf = carpeta / "subs"
            buf.mkdir(exist_ok=True)
            ruta = buf / f"{len(cache):03d}.png"
            cache[clave].save(ruta, "PNG")
            cache[clave] = ruta
        claves.append((t0, t1, cache[clave], bool(bloque)))

    transparente = carpeta / "subs" / "vacio.png"
    if not transparente.exists():
        dibujar([], -1).save(transparente, "PNG")

    salida = carpeta / "subtitulos.mov"
    frames = max(1, int(round(total * FPS)))
    orden = sorted(claves, key=lambda x: x[0])

    def png_en(t):
        elegido = transparente
        for t0, t1, ruta, tiene in orden:
            if t0 <= t < t1:
                elegido = ruta if tiene else transparente
                break
            if t0 > t:
                break
        return elegido

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(FPS),
         "-i", "-", "-c:v", "prores_ks", "-profile:v", "4444",
         "-pix_fmt", "yuva444p10le", str(salida)],
        stdin=subprocess.PIPE)
    repetido, anterior = None, None
    for i in range(frames):
        ruta = png_en(i / FPS)
        if ruta != anterior:
            anterior = ruta
            repetido = ruta.read_bytes()
        proc.stdin.write(repetido)
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise SystemExit("ffmpeg fallo al montar los subtitulos")

    print(f"subtitulos: {len(cache)} estados · {frames} cuadros · {total:.1f} s")
    print(f"salida -> {salida}")
    return salida


if __name__ == "__main__":
    nombre = sys.argv[1] if len(sys.argv) > 1 else "2026-11-17-dia"
    construir(nombre)
