"""Monta la capsula vertical: diapositivas con Pillow y video con ffmpeg.

Cada segmento del guion (gancho, notas, cierre) se vuelve una diapositiva: la foto
del articulo, un degradado para que el texto se lea, la seccion arriba y el
titular abajo. ffmpeg hace un zoom lento sobre cada foto y pega el audio.

Uso:
    python capsula.py                      # monta el guion y la voz mas recientes
    python capsula.py --sin-musica
    python capsula.py --solo-diapositivas   # no monta video (revisar el diseno)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import textwrap
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ.parent / ".deps"))

import config  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

BUILD = RAIZ / "build"
SALIDA = RAIZ / "docs" / "videos"
MUSICA = RAIZ / "musica" / "fondo.mp3"

ANCHO, ALTO = 1080, 1920
FPS = 30
SILENCIO = 0.28
MARGEN = 72

NEGRO = (14, 14, 14)        # #0E0E0E
BLANCO = (255, 255, 255)
ROJO = (225, 6, 0)          # #E10600, el rojo alerta de la marca
GRIS = (163, 163, 163)      # #A3A3A3, texto secundario sobre negro
ACENTO = ROJO

MARGEN_X = 65               # zona segura lateral
Y_BANDA_SUBS = 1300         # altura donde se pega la banda de subtitulos
TOPE_Y = 160                # interfaz de YouTube arriba
PISO_Y = 1500               # interfaz de YouTube abajo (1920 - 420)

MARCA_DIR = RAIZ / "marca"
FUENTES = MARCA_DIR / "fuentes"
F_TITULAR = FUENTES / "Anton-Regular.ttf"
F_SUB = FUENTES / "Archivo-Variable.ttf"
F_SUB_BLACK = FUENTES / "ArchivoBlack-Regular.ttf"
SELLO = "EL AHORITA"
LOGO = MARCA_DIR / "Logos" / "logo-horizontal-blanco.png"

ETIQUETAS = MARCA_DIR / "Etiquetas"
TAGS = {
    "mexico": ETIQUETAS / "tag-mexico.png",
    "mundo": ETIQUETAS / "tag-mundo.png",
    "ultima": ETIQUETAS / "tag-ultima-hora.png",
    "hasta": ETIQUETAS / "tag-hasta-ahorita.png",
}
OVERLAY = MARCA_DIR / "Shorts" / "overlay-marca-de-agua.png"
CIERRE = MARCA_DIR / "Shorts" / "cierre.png"
ALTO_TAG = 72
ALPHA_CAJA = 200           # opacidad de la caja del titular (0-255); 200 = se ve la foto
LINEA_ROJA = "ultima"      # "ultima" = ultima linea en rojo; "segunda" = la de en medio


def _hex_a_rgb(valor, defecto=ROJO):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(valor or "").strip())
    if not m:
        return defecto
    n = int(m.group(1), 16)
    return ((n >> 16) & 255, (n >> 8) & 255, n & 255)


def cargar_marca():
    """Lee marca/ajustes.json si existe: permite cambiar acento, sello y logo."""
    global ROJO, ACENTO, SELLO, LOGO
    ruta = MARCA_DIR / "ajustes.json"
    if not ruta.exists():
        return
    try:
        cfg = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    SELLO = cfg.get("sello") or SELLO
    if cfg.get("acento"):
        ROJO = ACENTO = _hex_a_rgb(cfg["acento"])
    if cfg.get("logo"):
        LOGO = RAIZ / cfg["logo"]


cargar_marca()


# ------------------------------------------------------------------ imagenes
def descargar(url, destino: Path, intentos=3):
    """Baja la imagen. Muchos CDN bloquean peticiones sin Referer ni Accept,
    y desde un servidor de GitHub es mas facil que las bloqueen."""
    if not url or not url.startswith("http"):
        return None
    partes = urllib.parse.urlsplit(url)
    cabeceras = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
        "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
        "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
        "Referer": f"{partes.scheme}://{partes.netloc}/",
    }
    for intento in range(intentos):
        try:
            req = urllib.request.Request(url, headers=cabeceras)
            with urllib.request.urlopen(req, timeout=25) as r:
                datos = r.read(8_000_000)
            if len(datos) < 2000:      # un pixel o una pagina de error
                raise ValueError("imagen demasiado pequena")
            destino.write_bytes(datos)
            return destino
        except Exception as e:  # noqa: BLE001
            if intento == intentos - 1:
                print(f"  aviso: no se pudo bajar la foto ({type(e).__name__})")
            else:
                import time as _t
                _t.sleep(1.5)
    return None


def foto(url, destino: Path):
    """Imagen de fondo: la del articulo, o un degradado de marca si no hay."""
    if descargar(url, destino):
        try:
            im = Image.open(destino).convert("RGB")
            return imresize_cover(im, (ANCHO, ALTO))
        except Exception:  # noqa: BLE001
            pass
    return degradado()


def imresize_cover(im, size):
    w, h = size
    esc = max(w / im.width, h / im.height)
    im = im.resize((max(1, int(im.width * esc + 0.5)), max(1, int(im.height * esc + 0.5))),
                   Image.LANCZOS)
    x = (im.width - w) // 2
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def degradado():
    """Fondo de marca para cuando no hay foto: negro que baja a rojo profundo,
    para que se lea como diseño y no como un error."""
    im = Image.new("RGB", (ANCHO, ALTO), NEGRO)
    d = ImageDraw.Draw(im)
    for y in range(ALTO):
        t = (y / ALTO) ** 1.6
        d.line([(0, y), (ANCHO, y)],
               fill=(int(14 + 62 * t), int(14 + 8 * t), int(14 + 6 * t)))
    return im


# ------------------------------------------------------------------ tipografia
def fuente(ruta, tam, peso=None):
    """Carga una fuente; con las variables de Archivo fija el grosor."""
    try:
        f = ImageFont.truetype(str(ruta), tam)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()
    if peso:
        try:
            f.set_variation_by_axes([100, peso])   # Archivo: [wdth, wght]
        except Exception:  # noqa: BLE001
            pass
    return f


def envolver(texto, fnt, ancho_max, max_lineas=3):
    """Corta el texto en lineas que quepan, sin partir palabras."""
    palabras, lineas, actual = texto.split(), [], ""
    for p in palabras:
        prueba = f"{actual} {p}".strip()
        if fnt.getlength(prueba) <= ancho_max or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    return lineas[:max_lineas]


def ajustar_titular(texto, ancho_max, alto_max, max_lineas=3):
    """Baja el tamano hasta que el titular quepa (Anton 78 px como punto de partida)."""
    for tam in range(78, 43, -4):
        fnt = fuente(F_TITULAR, tam)
        lineas = envolver(texto, fnt, ancho_max, max_lineas)
        if len(lineas) <= max_lineas and len(lineas) * int(tam * 1.08) <= alto_max:
            return fnt, lineas, tam
    fnt = fuente(F_TITULAR, 44)
    return fnt, envolver(texto, fnt, ancho_max, max_lineas), 44


def etiqueta_de(kicker, es_mexico=True, horas=99.0, medios=1):
    """Que etiqueta toca: ultima hora si es reciente y la cubren varios medios;
    si no, Mexico o mundo segun de donde venga la historia."""
    if horas <= 3 and medios >= 3:
        return "ultima"
    return "mexico" if es_mexico else "mundo"


def pegar_png(im, ruta, xy, alto=None):
    """Pega un PNG con transparencia, escalado a la altura pedida."""
    try:
        capa = Image.open(ruta).convert("RGBA")
    except Exception:  # noqa: BLE001
        return im
    if alto:
        capa = capa.resize((max(1, int(capa.width * alto / capa.height)), alto),
                           Image.LANCZOS)
    im = im.convert("RGBA")
    im.alpha_composite(capa, (int(xy[0]), int(xy[1])))
    return im.convert("RGB")


def titular_en_pantalla(texto, max_palabras=18):
    """Respaldo: primera frase del guion, cortada por coma si se pasa."""
    frases = re.split(r"(?<=[.!?])\s+", (texto or "").strip())
    frase = (frases[0] if frases and frases[0] else (texto or "")).strip()
    palabras = frase.split()
    if len(palabras) <= max_palabras:
        return frase
    recorte = " ".join(palabras[:max_palabras])
    if "," in recorte:
        recorte = recorte[:recorte.rfind(",")]
    return recorte.rstrip(" ,.;:") + "…"


# ------------------------------------------------------------------ diapositiva
def oscurecer(im, desde=0.34):
    """Degradado negro de abajo hacia arriba, para que los subtitulos se lean."""
    capa = Image.new("L", (1, ALTO), 0)
    px = capa.load()
    inicio = int(ALTO * (1 - desde))
    for y in range(ALTO):
        v = 0 if y < inicio else int(226 * ((y - inicio) / max(1, ALTO - inicio)) ** 1.25)
        px[0, y] = max(0, min(255, v))
    negro = Image.new("RGB", im.size, (0, 0, 0))
    return Image.composite(negro, im, capa.resize(im.size))


def diapositiva(fondo, kicker, titular, fuente_txt="", es_mexico=True,
                horas=99.0, medios=1):
    """Una diapositiva segun el manual: foto a sangre, marca arriba a la izquierda,
    etiqueta de seccion, caja negra con el titular (una linea en rojo) y la fuente."""
    im = oscurecer(fondo.copy())
    d = ImageDraw.Draw(im)

    # etiqueta de seccion: PNG de marca si existe, texto si no
    cual = etiqueta_de(kicker, es_mexico, horas, medios)
    y_etq = 212
    ruta_tag = TAGS.get(cual)
    if ruta_tag and ruta_tag.exists():
        im = pegar_png(im, ruta_tag, (MARGEN_X, y_etq), ALTO_TAG)
        d = ImageDraw.Draw(im)
    else:
        txt_etq = {"mexico": "AHORITA EN MÉXICO", "mundo": "AHORITA EN EL MUNDO",
                   "ultima": "ULTIMA HORA", "hasta": "HASTA AHORITA"}.get(cual, "")
        f_etq = fuente(F_TITULAR, 46)
        ancho_etq = f_etq.getlength(txt_etq)
        fondo, texto = (BLANCO, NEGRO) if cual == "mundo" else (ROJO, BLANCO)
        d.rectangle([MARGEN_X, y_etq, MARGEN_X + ancho_etq + 44, y_etq + ALTO_TAG],
                    fill=fondo)
        d.text((MARGEN_X + 22, y_etq + 12), txt_etq, font=f_etq, fill=texto)

    # caja del titular
    ancho_caja = ANCHO - 2 * MARGEN_X
    f_tit, lineas, tam = ajustar_titular(titular.upper(), ancho_caja - 68, 300)
    alto_linea = int(tam * 1.08)
    alto_caja = 44 + len(lineas) * alto_linea + (82 if fuente_txt else 22)
    y0 = y_etq + 66 + 16
    # la caja va semitransparente para que no tape el rostro de la foto
    capa = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(capa).rounded_rectangle(
        [MARGEN_X, y0, MARGEN_X + ancho_caja, y0 + alto_caja],
        radius=12, fill=(*NEGRO, ALPHA_CAJA))
    im = Image.alpha_composite(im.convert("RGBA"), capa).convert("RGB")
    d = ImageDraw.Draw(im)

    # una linea clave en rojo (configurable con LINEA_ROJA)
    if LINEA_ROJA == "segunda":
        i_roja = 1 if len(lineas) >= 2 else -1
    else:
        i_roja = len(lineas) - 1 if len(lineas) >= 2 else -1
    y = y0 + 30
    for i, linea in enumerate(lineas):
        d.text((MARGEN_X + 34, y), linea, font=f_tit,
               fill=ROJO if i == i_roja else BLANCO)
        y += alto_linea
    if fuente_txt:
        d.text((MARGEN_X + 34, y + 18), f"Fuente: {fuente_txt}",
               font=fuente(F_SUB, 30, 600), fill=GRIS)

    # marca de agua de la marca, encima de todo
    if OVERLAY.exists():
        im = pegar_png(im, OVERLAY, (0, 0))
    else:
        d2 = ImageDraw.Draw(im)
        d2.ellipse([MARGEN_X, 138, MARGEN_X + 22, 160], fill=ROJO)
        d2.text((MARGEN_X + 34, 128), SELLO, font=fuente(F_TITULAR, 46), fill=BLANCO)
    return im


# ------------------------------------------------------------------ montaje
def segmentos(manifiesto):
    return manifiesto["segmentos"]


def datos_por_link():
    """Imagen y nombre del medio para cada historia, por su enlace."""
    datos = json.loads((RAIZ / "docs" / "data" / "latest.json").read_text(encoding="utf-8"))
    items = datos["items"] if isinstance(datos, dict) and "items" in datos else datos
    salida = {}
    for i in items:
        try:
            dt = datetime.fromisoformat(str(i.get("published", "")).replace("Z", "+00:00"))
            horas = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
        except Exception:  # noqa: BLE001
            horas = 99.0
        salida[i.get("link")] = {
            "image": i.get("image", ""),
            "medio": i.get("source_name", ""),
            "region": i.get("region", "mx"),
            "horas": horas,
            "medios": 1 + len(i.get("also") or []),
        }
    return salida


def construir(args):
    guiones = sorted((RAIZ / "docs" / "guiones").glob("*.json"))
    if not guiones:
        raise SystemExit("no hay guion")
    ruta_guion = Path(args.guion) if args.guion else guiones[-1]
    datos = json.loads(ruta_guion.read_text(encoding="utf-8"))
    guion = datos.get("guion", datos)
    nombre = ruta_guion.stem

    carpeta = BUILD / nombre
    manifiesto_path = carpeta / "voz.json"
    if not manifiesto_path.exists():
        raise SystemExit(f"falta la voz: corre antes `python voz.py` ({manifiesto_path})")
    manifiesto = json.loads(manifiesto_path.read_text(encoding="utf-8"))
    segs = segmentos(manifiesto)

    por_link = datos_por_link()
    historias = datos.get("historias", [])
    slides_dir = carpeta / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    # texto en pantalla: el titular corto que escribio el modelo; si falta,
    # se recorta la primera frase del guion (que ya esta en español)
    textos = {}
    for s in segs:
        if s["id"] == "cierre":
            textos[s["id"]] = "Las noticias que importan, todos los días."
        else:
            textos[s["id"]] = (s.get("pantalla") or "").strip() \
                or titular_en_pantalla(s.get("texto", ""))

    def foto_de(seg_id):
        """Foto del segmento: el gancho usa la de la primera nota."""
        if seg_id.startswith("nota"):
            idx = int(seg_id[4:]) - 1
        elif seg_id == "gancho":
            idx = 0
        else:
            return ""
        if 0 <= idx < len(historias):
            h = historias[idx]
            if h.get("imagen_url"):
                return h["imagen_url"]          # nota pedida a mano
            return por_link.get(h.get("link"), {}).get("image", "")
        return ""

    def medio_de(url):
        try:
            host = urllib.parse.urlparse(url or "").netloc.lower()
        except Exception:  # noqa: BLE001
            return ""
        host = host.replace("www.", "")
        nombre = host.split(".")[0].replace("-", " ")
        return nombre.title() if nombre else ""

    rutas = []
    for i, s in enumerate(segs):
        destino = slides_dir / f"{i:02d}-{s['id']}.png"
        if s["id"] == "cierre":
            # la tarjeta de cierre va tal cual, sin etiqueta ni caja de titular
            if CIERRE.exists():
                im = Image.open(CIERRE).convert("RGB").resize((ANCHO, ALTO), Image.LANCZOS)
            else:
                im = diapositiva(degradado(), s["kicker"], textos.get("cierre", ""))
            im.save(destino, "PNG")
            rutas.append(destino)
            print(f"  diapositiva {destino.name} (cierre de marca)")
            continue
        base = foto(foto_de(s["id"]), slides_dir / f"{i:02d}-fuente.img")
        fuente_txt, es_mx, horas, medios = "", True, 99.0, 1
        idx = int(s["id"][4:]) - 1 if s["id"].startswith("nota") else 0
        if 0 <= idx < len(historias):
            h = historias[idx]
            info = por_link.get(h.get("link"), {})
            if s["id"].startswith("nota"):
                fuente_txt = info.get("medio") or h.get("medio") or medio_de(h.get("link"))
            es_mx = (h.get("region") or info.get("region", "mx")) == "mx"
            horas = float(h.get("horas", info.get("horas", 99.0)))
            medios = int(h.get("medios", info.get("medios", 1)))
        kicker = s["kicker"]
        if s["id"] == "gancho" and len(segs) > 1:
            kicker = segs[1]["kicker"]
        im = diapositiva(base, kicker, textos.get(s["id"], ""), fuente_txt,
                         es_mx, horas, medios)
        im.save(destino, "PNG")
        rutas.append(destino)
        print(f"  diapositiva {destino.name}")

    if args.solo_diapositivas:
        print(f"\ndiapositivas en {slides_dir}")
        return 0

    # video mudo: zoom lento por segmento y concatenado
    trozos = []
    for i, (s, png) in enumerate(zip(segs, rutas)):
        dur = round(float(s["dur"]) + SILENCIO, 3)
        trozo = carpeta / f"{i:02d}-{s['id']}.mp4"
        vf = (f"scale={ANCHO * 2}:{ALTO * 2}:force_original_aspect_ratio=increase,"
              f"crop={ANCHO * 2}:{ALTO * 2},"
              f"zoompan=z='min(1.0+0.00035*on,1.12)':x='iw/2-(iw/zoom/2)'"
              f":y='ih/2-(ih/zoom/2)':d=1:s={ANCHO}x{ALTO}:fps={FPS},"
              f"format=yuv420p")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1",
                        "-framerate", str(FPS), "-t", str(dur),
                        "-i", str(png), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "22", "-r", str(FPS), str(trozo)], check=True)
        trozos.append(trozo)
        print(f"  video {trozo.name} ({dur} s)")

    lista = carpeta / "trozos.txt"
    lista.write_text("".join(f"file '{t.as_posix()}'\n" for t in trozos), encoding="utf-8")
    mudo = carpeta / "mudo.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lista), "-c", "copy", str(mudo)], check=True)

    # subtitulos con la palabra activa en pastilla roja
    subs = None
    if not args.sin_subtitulos:
        try:
            import subtitulos as _subs
            subs = Path(_subs.construir(nombre))
        except Exception as e:  # noqa: BLE001
            print(f"  aviso: sin subtitulos ({type(e).__name__}: {e})")

    # audio: voz + musica de fondo, y la capa de subtitulos encima del video
    voz = Path(manifiesto["segmentos"][0]["audio"]).parent.parent / "voz-completa.mp3"
    salida = SALIDA / f"{nombre}.mp4"
    salida.parent.mkdir(parents=True, exist_ok=True)

    entradas = ["-i", str(mudo), "-i", str(voz)]
    siguiente = 2                     # indice del proximo -i (0 y 1 ya usados)
    idx_musica = idx_subs = None
    if MUSICA.exists() and not args.sin_musica:
        idx_musica = siguiente
        entradas += ["-stream_loop", "-1", "-i", str(MUSICA)]
        siguiente += 1
    if subs and subs.exists():
        idx_subs = siguiente
        entradas += ["-i", str(subs)]
        siguiente += 1

    filtros, mapas = [], ["-map", "0:v"]
    if idx_subs is not None:
        filtros.append(f"[0:v][{idx_subs}:v]overlay=0:{Y_BANDA_SUBS}:format=auto[v]")
        mapas = ["-map", "[v]"]
    if idx_musica is not None:
        filtros.append(f"[{idx_musica}:a]volume=0.16,afade=t=in:st=0:d=0.6[m]")
        filtros.append("[1:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]")
        mapas += ["-map", "[a]"]
    else:
        mapas += ["-map", "1:a"]

    orden = ["ffmpeg", "-y", "-v", "error", *entradas]
    if filtros:
        orden += ["-filter_complex", ";".join(filtros)]
    orden += mapas
    if idx_subs is not None:
        orden += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]
    else:
        orden += ["-c:v", "copy"]
    orden += ["-c:a", "aac", "-b:a", "192k", "-shortest", str(salida)]
    subprocess.run(orden, check=True)

    # portada y textos para publicar
    portada = SALIDA / f"{nombre}-portada.jpg"
    Image.open(rutas[0]).convert("RGB").save(portada, "JPEG", quality=88)
    dur_total = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(salida)], capture_output=True, text=True)
    print(f"\nvideo -> {salida}")
    print(f"portada -> {portada}")
    print(f"duracion: {float(dur_total.stdout.strip() or 0):.1f} s")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guion", default="")
    ap.add_argument("--sin-musica", action="store_true")
    ap.add_argument("--solo-diapositivas", action="store_true")
    ap.add_argument("--sin-subtitulos", action="store_true")
    args = ap.parse_args()
    return construir(args)


if __name__ == "__main__":
    sys.exit(main())
