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

UA = "ElAhoritaBot/1.0 (https://github.com/mexicanfasionstreet-cyber/elahorita)"
ANCHO_MIN = 700                 # menos que esto se ve borroso a 1080x1920
ANCHO_BAJADA = 1280
LICENCIA_LIBRE = re.compile(r"^\s*(cc0|public domain|dominio p[uú]blico|pd\b|"
                            r"cc[ -]by(-sa)?([ -][\d.]+)?\b)", re.I)
EXTENSIONES = (".jpg", ".jpeg")


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


def buscar(termino, llamar=None):
    """Foto libre para un termino, o None. Nunca levanta excepcion."""
    termino = (termino or "").strip()
    if not termino:
        return None
    for lang in ("es", "en"):
        try:
            archivo = archivo_de_wikipedia(termino, lang, llamar)
            info = info_commons(archivo, llamar) if archivo else None
        except Exception as e:  # noqa: BLE001  (red, JSON raro: se sigue sin foto)
            print(f"  aviso: busqueda de foto fallo en {lang} ({type(e).__name__})")
            continue
        if info:
            info["termino"] = termino
            return info
    return None


def para_historias(historias, guion, llamar=None):
    """Le pone a cada historia su foto libre (o {} = fondo de diseño)."""
    notas = guion.get("notas") or []
    for i, h in enumerate(historias):
        termino = (notas[i].get("foto") if i < len(notas) else "") or ""
        if h.get("sensible"):
            h["foto"] = {}
            print(f"  foto nota {i + 1}: tema sensible, fondo de diseño")
            continue
        info = buscar(termino, llamar)
        h["foto"] = info or {}
        print(f"  foto nota {i + 1}: " + (f"{termino} -> {info['credito']}" if info
                                          else f"sin foto libre para '{termino}', fondo de diseño"))
    return historias


if __name__ == "__main__":
    print(json.dumps(buscar(" ".join(sys.argv[1:]) or "Jensen Huang"), ensure_ascii=False, indent=1))
