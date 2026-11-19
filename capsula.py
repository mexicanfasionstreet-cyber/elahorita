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
import tomas as tomas_mod  # noqa: E402
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
ALTO_BARRA = 10             # barra de progreso roja, arriba
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
    # Wikimedia pide un User-Agent que diga quien eres; los CDN de medios, uno de navegador
    wiki = partes.netloc.endswith("wikimedia.org")
    cabeceras = {
        "User-Agent": ("ElAhoritaBot/1.0 (https://github.com/mexicanfasionstreet-cyber/elahorita)"
                       if wiki else
                       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
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


def foto(url, destino: Path, kicker=""):
    """Fondo: la foto libre de la nota (fotos.py), o el fondo de diseño si no hay."""
    if descargar(url, destino):
        try:
            return encuadrar(Image.open(destino).convert("RGB"))
        except Exception:  # noqa: BLE001
            pass
    return fondo_diseno(kicker)


ANCHO_NITIDO = 1000         # menos que esto, a pantalla completa se veria borrosa
Y_FOTO_ANGOSTA = 520        # donde empieza una foto angosta: debajo de la caja del titular


def encuadrar(im):
    """Foto grande: a sangre. Foto angosta (retrato recortado de Wikipedia): nitida
    a todo lo ancho, sobre la misma foto desenfocada y oscura que llena el resto."""
    if im.width >= ANCHO_NITIDO:
        return imresize_cover(im, (ANCHO, ALTO))
    from PIL import ImageEnhance
    fondo = imresize_cover(im, (ANCHO, ALTO)).filter(ImageFilter.GaussianBlur(34))
    fondo = ImageEnhance.Brightness(fondo).enhance(0.45)
    esc = ANCHO / im.width
    frente = im.resize((ANCHO, max(1, int(im.height * esc + 0.5))), Image.LANCZOS)
    if frente.height > ALTO:
        y = (frente.height - ALTO) // 3            # recorta mas abajo: la cara suele ir arriba
        frente = frente.crop((0, y, ANCHO, y + ALTO))
    # la cara suele ir en el tercio de arriba de un retrato: se baja la foto para que
    # quede libre debajo de la caja del titular; lo que sobra abajo (el cuerpo) se corta
    fondo.paste(frente, (0, Y_FOTO_ANGOSTA))
    return fondo


def fondo_diseno(kicker=""):
    """Fondo de marca para notas sin foto libre: el degradado con la seccion en
    letras gigantes y franjas diagonales, para que se lea como diseño y no como hueco."""
    im = degradado()
    palabra = (kicker or SELLO).strip().upper()[:12] or SELLO
    capa = Image.new("RGBA", (ANCHO * 2, ALTO * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    for x in range(-ALTO * 2, ANCHO * 2, 90):          # franjas finas a 30 grados
        d.line([(x, ALTO * 2), (x + int(ALTO * 2 * 0.58), 0)], fill=(255, 255, 255, 10), width=14)
    fnt = fuente(F_TITULAR, 330)
    paso = int(330 * 1.02)
    for fila, y in enumerate(range(0, ALTO * 2, paso)):
        x = -(fila % 2) * 260
        color = (*ROJO, 46) if fila % 3 == 1 else (255, 255, 255, 18)
        d.text((x, y), (palabra + "  ") * 4, font=fnt, fill=color)
    capa = capa.rotate(12, resample=Image.BICUBIC)
    capa = capa.crop((ANCHO // 2, ALTO // 2, ANCHO // 2 + ANCHO, ALTO // 2 + ALTO))
    return Image.alpha_composite(im.convert("RGBA"), capa).convert("RGB")


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
                horas=99.0, medios=1, con_caja=True):
    """Una diapositiva segun el manual: foto a sangre, marca arriba a la izquierda,
    etiqueta de seccion, caja negra con el titular (una linea en rojo) y la fuente.
    Sin caja (con_caja=False) es la toma "limpia": la foto respira entre titulares."""
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

    if not con_caja:
        titular = ""

    # caja del titular
    ancho_caja = ANCHO - 2 * MARGEN_X
    if not titular:
        return _sello(im)
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

    return _sello(im)


def _sello(im):
    """Marca de agua de la marca, encima de todo."""
    if OVERLAY.exists():
        return pegar_png(im, OVERLAY, (0, 0))
    d2 = ImageDraw.Draw(im)
    d2.ellipse([MARGEN_X, 138, MARGEN_X + 22, 160], fill=ROJO)
    d2.text((MARGEN_X + 34, 128), SELLO, font=fuente(F_TITULAR, 46), fill=BLANCO)
    return im


def tarjeta_dato(fondo, dato):
    """La cifra o el hecho clave en grande, sobre la foto desenfocada y oscura.
    Va entre la interfaz de arriba y la banda de subtitulos."""
    from PIL import ImageEnhance
    im = fondo.copy().filter(ImageFilter.GaussianBlur(26))
    im = ImageEnhance.Brightness(im).enhance(0.38)
    d = ImageDraw.Draw(im)
    texto = re.sub(r"\s+", " ", str(dato or "")).strip().rstrip(".").upper()
    ancho_max = ANCHO - 2 * MARGEN_X - 20
    tam = 200
    while tam > 90:
        fnt = fuente(F_TITULAR, tam)
        lineas = envolver(texto, fnt, ancho_max, max_lineas=3)
        huerfana = len(lineas) > 1 and any(len(x) <= 3 for x in lineas)
        if lineas and all(fnt.getlength(x) <= ancho_max for x in lineas) \
                and " ".join(lineas) == texto and not huerfana:
            break
        tam -= 10
    alto_linea = int(tam * 1.05)
    alto_txt = len(lineas) * alto_linea
    y = int((TOPE_Y + 120 + Y_BANDA_SUBS - 60) / 2 - alto_txt / 2)
    d.rectangle([MARGEN_X, y - 54, MARGEN_X + 150, y - 38], fill=ROJO)   # acento
    roja = next((i for i, x in enumerate(lineas) if re.search(r"\d", x)),
                len(lineas) - 1 if len(lineas) > 1 else -1)
    for i, linea in enumerate(lineas):
        d.text((MARGEN_X, y), linea, font=fnt, fill=ROJO if i == roja else BLANCO)
        y += alto_linea
    return _sello(im)


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
            horas = max(0.0, (config.ahora().astimezone(timezone.utc) - dt).total_seconds() / 3600)
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
            # solo la foto libre que encontro fotos.py; nunca la del medio
            return (historias[idx].get("foto") or {}).get("url", "")
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
    guion_notas = guion.get("notas") or []
    planes = []                      # (segmento, [tomas con su png])
    for i, s in enumerate(segs):
        destino = slides_dir / f"{i:02d}-{s['id']}.png"
        dur = round(float(s["dur"]) + SILENCIO, 3)
        if s["id"] == "cierre":
            # la tarjeta de cierre va tal cual, sin etiqueta ni caja de titular
            if CIERRE.exists():
                im = Image.open(CIERRE).convert("RGB").resize((ANCHO, ALTO), Image.LANCZOS)
            else:
                im = diapositiva(fondo_diseno(), s["kicker"], textos.get("cierre", ""))
            im.save(destino, "PNG")
            rutas.append(destino)
            planes.append((s, [{"tipo": "principal", "t0": 0.0, "t1": dur,
                                "mov": "acerca", "png": destino}]))
            print(f"  diapositiva {destino.name} (cierre de marca)")
            continue
        kicker_fondo = segs[1]["kicker"] if s["id"] == "gancho" and len(segs) > 1 else s["kicker"]
        url = foto_de(s["id"])
        base = foto(url, slides_dir / f"{i:02d}-fuente.img", kicker_fondo)
        fuente_txt, es_mx, horas, medios = "", True, 99.0, 1
        idx = int(s["id"][4:]) - 1 if s["id"].startswith("nota") else 0
        url2, datos_nota = "", []
        if 0 <= idx < len(historias):
            h = historias[idx]
            info = por_link.get(h.get("link"), {})
            if s["id"].startswith("nota"):
                fuente_txt = info.get("medio") or h.get("medio") or medio_de(h.get("link"))
                url2 = (h.get("foto2") or {}).get("url", "")
            es_mx = (h.get("region") or info.get("region", "mx")) == "mx"
            horas = float(h.get("horas", info.get("horas", 99.0)))
            medios = int(h.get("medios", info.get("medios", 1)))
        if s["id"].startswith("nota") and 0 <= idx < len(guion_notas):
            datos_nota = [d for d in (guion_notas[idx].get("datos") or []) if str(d).strip()]
        kicker = s["kicker"]
        if s["id"] == "gancho" and len(segs) > 1:
            kicker = segs[1]["kicker"]
        im = diapositiva(base, kicker, textos.get(s["id"], ""), fuente_txt,
                         es_mx, horas, medios)
        im.save(destino, "PNG")
        rutas.append(destino)

        base2 = None
        if url2:
            ruta2 = slides_dir / f"{i:02d}-fuente2.img"
            if descargar(url2, ruta2):
                try:
                    base2 = encuadrar(Image.open(ruta2).convert("RGB"))
                except Exception:  # noqa: BLE001
                    base2 = None
        plan = tomas_mod.planear(dur, datos_nota, s.get("palabras") or [],
                                 hay_foto=bool(url), hay_foto2=base2 is not None,
                                 es_gancho=s["id"] == "gancho")
        for k, tm in enumerate(plan):
            if tm["tipo"] == "principal":
                tm["png"] = destino
                continue
            ruta_t = slides_dir / f"{i:02d}-{s['id']}-{k:02d}-{tm['tipo']}.png"
            if tm["tipo"] == "dato":
                tarjeta_dato(base2 or base, tm["dato"]).save(ruta_t, "PNG")
            else:
                fondo_t = base2 if tm["tipo"] == "foto2" else base
                diapositiva(fondo_t, kicker, "", "", es_mx, horas, medios,
                            con_caja=False).save(ruta_t, "PNG")
            tm["png"] = ruta_t
        planes.append((s, plan))
        resumen = " ".join(f"{t['tipo']}({t['t1'] - t['t0']:.1f})" for t in plan)
        print(f"  diapositiva {destino.name} · tomas: {resumen}")

    if args.solo_diapositivas:
        print(f"\ndiapositivas en {slides_dir}")
        return 0

    # video mudo: cada toma con su movimiento de camara, y todo concatenado
    trozos = []
    for i, (s, plan) in enumerate(planes):
        for k, tm in enumerate(plan):
            dur = round(tm["t1"] - tm["t0"], 3)
            trozo = carpeta / f"{i:02d}-{s['id']}-{k:02d}.mp4"
            frames = max(1, round(dur * FPS))
            vf = tomas_mod.zoompan(tm["mov"], frames, ANCHO, ALTO, FPS)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1",
                            "-framerate", str(FPS), "-t", str(dur),
                            "-i", str(tm["png"]), "-vf", vf, "-c:v", "libx264",
                            "-preset", "veryfast", "-crf", "22", "-r", str(FPS),
                            str(trozo)], check=True)
            trozos.append(trozo)
        print(f"  video {s['id']}: {len(plan)} tomas")
    dur_mudo = sum(round(t["t1"] - t["t0"], 3) for _, plan in planes for t in plan)

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

    filtros = []
    capa = "0:v"
    if idx_subs is not None:
        filtros.append(f"[0:v][{idx_subs}:v]overlay=0:{Y_BANDA_SUBS}:format=auto[vs]")
        capa = "vs"
    # barra de progreso roja arriba: avanza con el video
    filtros.append(f"color=c=0x{ROJO[0]:02X}{ROJO[1]:02X}{ROJO[2]:02X}:s={ANCHO}x{ALTO_BARRA}"
                   f":r={FPS}:d={dur_mudo:.3f}[barra]")
    filtros.append(f"[{capa}][barra]overlay=x='-w+w*t/{max(dur_mudo, 0.1):.3f}':y=0"
                   f":eof_action=pass[v]")
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
    orden += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]
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
