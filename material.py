"""Saca el texto de un articulo para que el guion tenga material de verdad.

Sin dependencias: quita scripts, menus y avisos de cookies, y se queda con los
parrafos del cuerpo del articulo. Si no encuentra nada usable, devuelve lo que
haya (descripcion, titular) y el guion sabra que tiene poco.

Uso: python material.py <url>
"""
from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aggregate import clean_text  # noqa: E402


def decodificar(crudo, cabecera=""):
    """Decodifica con el charset de la cabecera, del <meta> o un respaldo."""
    charset = None
    m = re.search(r"charset=([\w-]+)", cabecera or "", re.I)
    if m:
        charset = m.group(1)
    if not charset:
        m = re.search(rb"""charset=["']?([\w-]+)""", crudo[:2048], re.I)
        if m:
            charset = m.group(1).decode("ascii", "ignore")
    for c in (charset, "utf-8", "cp1252"):
        if not c:
            continue
        try:
            return crudo.decode(c)
        except (LookupError, UnicodeDecodeError):
            continue
    return crudo.decode("utf-8", "replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
TIMEOUT = 25
MAX_CHARS = 3000

BASURA = re.compile(
    r"(cookie|newsletter|suscr[ií]bete|suscribirse|inicia sesi[oó]n|reg[ií]strate"
    r"|publicidad|comparte (esta|en)|s[ií]guenos|descarga la app|t[eé]rminos y condiciones"
    r"|aviso de privacidad|todos los derechos|copyright|©)", re.I)
SALTAR = re.compile(r"<(script|style|noscript|nav|header|footer|aside|form|iframe|figure|svg)\b.*?</\1>",
                    re.I | re.S)
COMENTARIOS = re.compile(r"<!--.*?-->", re.S)
PARRAFO = re.compile(r"<p\b[^>]*>(.*?)</p>", re.I | re.S)
ARTICLE = re.compile(r"<article\b[^>]*>(.*?)</article>", re.I | re.S)
META = re.compile(r"""<meta[^>]+(?:name|property)=["'](og:description|description)["'][^>]+content=["']([^"']+)["']""",
                  re.I)


def _limpiar_html(html):
    html = COMENTARIOS.sub(" ", html)
    return SALTAR.sub(" ", html)


def parrafos(html, minimo=70):
    """Parrafos con cuerpo suficiente, sin avisos ni menus."""
    # si hay <article>, se usa el mas largo: es donde vive la nota
    trozos = ARTICLE.findall(html)
    cuerpo = max(trozos, key=len) if trozos else html
    salida = []
    for bruto in PARRAFO.findall(cuerpo):
        txt = clean_text(bruto)
        if len(txt) < minimo:
            continue
        if BASURA.search(txt):
            continue
        if txt.count(" ") < 8:      # listas y botones
            continue
        salida.append(txt)
    return salida


def articulo(url, timeout=TIMEOUT):
    """Devuelve {'texto', 'descripcion', 'palabras', 'url'} del articulo."""
    vacio = {"texto": "", "descripcion": "", "palabras": 0, "url": url}
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "es-MX,es;q=0.9,en;q=0.7"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            crudo = r.read(900_000)
            cab = r.headers.get("Content-Type", "")
            final = r.geturl()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return vacio

    html = decodificar(crudo, cab)
    desc = ""
    m = META.search(html)
    if m:
        desc = clean_text(m.group(2))

    html = _limpiar_html(html)
    pars = parrafos(html)
    texto = " ".join(pars)
    if len(texto) > MAX_CHARS:
        texto = texto[:MAX_CHARS].rsplit(" ", 1)[0] + "…"

    return {"texto": texto, "descripcion": desc,
            "palabras": len(texto.split()), "url": final}


def main():
    if len(sys.argv) < 2:
        raise SystemExit("uso: python material.py <url>")
    d = articulo(sys.argv[1])
    print(f"{d['palabras']} palabras · {d['url']}\n")
    print(d["descripcion"])
    print()
    print(d["texto"][:1500])


if __name__ == "__main__":
    main()
