"""Fotos con licencia libre para el fondo del video.

Nunca se usa la foto del medio: casi siempre es de agencia (AP, Reuters, Getty,
EFE...) y una solicitud de retiro es un strike para el canal.

Por cada nota el guionista dice a quien o que mostrar ("Jensen Huang",
"Palacio Nacional", "Tijuana"). Aqui se busca ese articulo en Wikipedia
(español, luego ingles), se toma su foto principal y se confirma en Wikimedia
Commons que la licencia sea libre (dominio publico, CC0, CC BY o CC BY-SA).
Solo fotos (jpg): los logos y mapas suelen ser svg/png y una marca no es
licencia libre aunque el archivo lo diga.

Si no hay foto segura, o la nota es de un tema sensible, la nota va con el
fondo de diseño de la marca (capsula.fondo_diseno). El credito de cada foto va
en la descripcion de YouTube (publicar.textos).

    python fotos.py "Jensen Huang"      # prueba una busqueda
"""
from __future__ import annotations

import html
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

UA = "ElAhoritaBot/1.0 (https://github.com/mexicanfasionstreet-cyber/elahorita)"
ANCHO_MIN = 450                 # retratos recortados de Wikipedia: van nitidos al centro
                                # sobre su propio fondo desenfocado (capsula.foto)
ANCHO_BAJADA = 1280
LICENCIA_LIBRE = re.compile(r"^\s*(cc0|public domain|dominio p[uú]blico|pd\b|"
                            r"cc[ -]by(-sa)?([ -][\d.]+)?\b)", re.I)
EXTENSIONES = (".jpg", ".jpeg")
RECIENTES = Path(__file__).resolve().parent / "datos" / "fotos-usadas.json"
DIAS_SIN_REPETIR = 4            # una foto no vuelve a salir en este tiempo
MAX_CANDIDATAS = 12             # fotos del articulo que se revisan por busqueda
# imagenes del articulo que no son fotos de la persona o el lugar
NO_FOTO = re.compile(r"(logo|flag|bandera|map|mapa|escudo|coat|seal|firma|signature|icon|"
                     r"symbol|emblem|diagram|chart|commons-|wiki|screenshot|poster|cartel|"
                     r"stamp|sello|button|crop_?mark)", re.I)


def _get(url, params, timeout=20):
    q = urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z0-9]{3,}", t))


def _limpio(valor, n=90):
    """extmetadata trae HTML (enlaces al autor): se deja el texto."""
    t = html.unescape(re.sub(r"<[^>]+>", " ", str(valor or "")))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def archivo_de_wikipedia(termino, lang, llamar=None):
    llamar = llamar or _get
    """Nombre del archivo de la foto principal del articulo, o ''."""
    api = f"https://{lang}.wikipedia.org/w/api.php"
    base = {"action": "query", "prop": "pageimages", "piprop": "name",
            "pilicense": "free", "redirects": 1}
    datos = llamar(api, {**base, "titles": termino})
    paginas = [p for p in (datos.get("query") or {}).get("pages", []) if not p.get("missing")]
    if not paginas:
        # sin articulo con ese nombre exacto: la busqueda, pero solo si el
        # titulo que devuelve comparte palabras con lo pedido (que no sea otra persona)
        datos = llamar(api, {**base, "generator": "search", "gsrsearch": termino, "gsrlimit": 1})
        paginas = [p for p in (datos.get("query") or {}).get("pages", [])
                   if _norm(termino) & _norm(p.get("title", ""))]
    for p in paginas:
        if p.get("pageimage"):
            return p["pageimage"]
    return ""


def pagina_y_foto(termino, lang, llamar=None):
    """(titulo del articulo, foto principal) del termino, o ('', '')."""
    llamar = llamar or _get
    api = f"https://{lang}.wikipedia.org/w/api.php"
    base = {"action": "query", "prop": "pageimages", "piprop": "name",
            "pilicense": "free", "redirects": 1}
    datos = llamar(api, {**base, "titles": termino})
    paginas = [p for p in (datos.get("query") or {}).get("pages", []) if not p.get("missing")]
    if not paginas:
        datos = llamar(api, {**base, "generator": "search", "gsrsearch": termino, "gsrlimit": 1})
        paginas = [p for p in (datos.get("query") or {}).get("pages", [])
                   if _norm(termino) & _norm(p.get("title", ""))]
    for p in paginas:
        if p.get("pageimage"):
            return p.get("title", termino), p["pageimage"]
    return "", ""


def otras_fotos(titulo, lang, llamar=None):
    """Otras imagenes jpg del articulo (el resto de su galeria), sin logos ni mapas."""
    llamar = llamar or _get
    datos = llamar(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "prop": "images", "titles": titulo, "imlimit": 60, "redirects": 1})
    salida = []
    for pag in (datos.get("query") or {}).get("pages", []):
        for im in pag.get("images") or []:
            nombre = (im.get("title") or "").split(":", 1)[-1].replace(" ", "_")
            if nombre.lower().endswith(EXTENSIONES) and not NO_FOTO.search(nombre):
                salida.append(nombre)
    return salida


def info_commons(archivo, llamar=None):
    """URL a 1280 px, credito y licencia, solo si la foto es libre y sirve."""
    llamar = llamar or _get
    if not archivo.lower().endswith(EXTENSIONES):
        return None
    datos = llamar("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "titles": f"File:{archivo}", "prop": "imageinfo",
        "iiprop": "url|size|extmetadata", "iiurlwidth": ANCHO_BAJADA})
    paginas = (datos.get("query") or {}).get("pages", [])
    if not paginas or not paginas[0].get("imageinfo"):
        return None
    ii = paginas[0]["imageinfo"][0]
    meta = {k: (v or {}).get("value", "") for k, v in (ii.get("extmetadata") or {}).items()}
    licencia = _limpio(meta.get("LicenseShortName"), 40)
    if str(meta.get("NonFree", "")).lower() == "true" or not LICENCIA_LIBRE.match(licencia):
        return None
    if int(ii.get("width") or 0) < ANCHO_MIN:
        return None
    autor = _limpio(meta.get("Artist")) or "autor en Wikimedia Commons"
    return {"url": ii.get("thumburl") or ii.get("url"), "licencia": licencia, "autor": autor,
            "pagina": ii.get("descriptionurl", ""),
            "credito": f"{autor} ({licencia}), Wikimedia Commons"}


def buscar(termino, llamar=None, evitar=()):
    """Foto libre para un termino que no este en `evitar`, o None. Nunca levanta excepcion.

    Primero la foto principal del articulo; si ya salio hace poco, otras fotos del
    mismo articulo, para no repetir siempre la misma cara.
    """
    termino = (termino or "").strip()
    evitar = {_arch(a) for a in evitar}
    if not termino:
        return None
    for lang in ("es", "en"):
        try:
            titulo, principal = pagina_y_foto(termino, lang, llamar)
            if not principal:
                continue
            candidatas = [principal]
            if _arch(principal) in evitar and titulo:
                candidatas += [a for a in otras_fotos(titulo, lang, llamar) if a != principal]
            revisadas = 0
            for archivo in candidatas:
                if _arch(archivo) in evitar:
                    continue
                revisadas += 1
                if revisadas > MAX_CANDIDATAS:
                    break
                info = info_commons(archivo, llamar)
                if info:
                    info["termino"] = termino
                    info["archivo"] = archivo
                    return info
        except Exception as e:  # noqa: BLE001  (red, JSON raro: se sigue sin foto)
            print(f"  aviso: busqueda de foto fallo en {lang} ({type(e).__name__})")
            continue
    return None


def _arch(nombre):
    return (nombre or "").replace(" ", "_").lower()


def _leer_recientes():
    try:
        datos = json.loads(RECIENTES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    limite = datetime.now(timezone.utc) - timedelta(days=DIAS_SIN_REPETIR)
    salida = []
    for d in datos if isinstance(datos, list) else []:
        try:
            if datetime.fromisoformat(d["cuando"]) > limite:
                salida.append(d)
        except (KeyError, ValueError, TypeError):
            continue
    return salida


def _guardar_recientes(lista):
    try:
        RECIENTES.parent.mkdir(parents=True, exist_ok=True)
        RECIENTES.write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        print(f"  aviso: no se guardo el registro de fotos ({e})")


def para_historias(historias, guion, llamar=None):
    """Le pone a cada historia su foto libre (o {} = fondo de diseño)."""
    notas = guion.get("notas") or []
    recientes = _leer_recientes()
    evitar = {d["archivo"] for d in recientes if d.get("archivo")}
    usadas_ahora = []
    for i, h in enumerate(historias):
        nota = notas[i] if i < len(notas) else {}
        if h.get("sensible"):
            h["foto"] = h["foto2"] = {}
            print(f"  foto nota {i + 1}: tema sensible, fondo de diseño")
            continue
        for campo in ("foto", "foto2"):
            termino = (nota.get(campo) or "").strip()
            info = buscar(termino, llamar, evitar) if termino else None
            if info and campo == "foto2" and info["url"] == (h.get("foto") or {}).get("url"):
                info = None                     # la misma foto dos veces no suma
            if info and info.get("archivo"):
                evitar.add(_arch(info["archivo"]))   # ni dos veces en este mismo video
                usadas_ahora.append({"cuando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                     "archivo": _arch(info["archivo"]), "termino": termino})
            h[campo] = info or {}
            if termino:
                print(f"  {campo} nota {i + 1}: " + (f"{termino} -> {info['credito']}" if info
                      else f"sin foto libre nueva para '{termino}'"))
    if usadas_ahora:
        _guardar_recientes(recientes + usadas_ahora)
    return historias


if __name__ == "__main__":
    print(json.dumps(buscar(" ".join(sys.argv[1:]) or "Jensen Huang"), ensure_ascii=False, indent=1))
