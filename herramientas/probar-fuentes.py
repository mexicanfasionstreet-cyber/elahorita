"""Prueba el catalogo de fuentes: RSS valido, cuantas notas trae y si traen imagen.

Solo biblioteca estandar. Uso:
    python herramientas/probar-fuentes.py [--json salida.json] [--workers 8]

Para cada fuente informa: estado HTTP, tipo de feed (RSS/Atom), numero de items,
antiguedad del mas reciente, si el primer item trae imagen y un titular de muestra.
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CATALOGO = AQUI / "fuentes-candidatas.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
TIMEOUT = 25
IMG_RX = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)
TAG_RX = re.compile(r"<[^>]+>")
WS_RX = re.compile(r"\s+")


def tag(e):
    return e.tag.split("}")[-1].lower()


def texto(e, nombres):
    """Primer hijo cuyo tag este en `nombres`."""
    for hijo in e:
        if tag(hijo) in nombres and (hijo.text or "").strip():
            return hijo.text.strip()
    return ""


def limpio(s, n=90):
    s = WS_RX.sub(" ", TAG_RX.sub(" ", s or "")).strip()
    return s[:n]


def decodificar(crudo, cabecera):
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


def tiene_imagen(item, descripcion):
    for hijo in item.iter():
        t = tag(hijo)
        if t in ("content", "thumbnail", "enclosure", "image"):
            for k, v in hijo.attrib.items():
                if k.lower().endswith("url") and v:
                    if t == "enclosure" and hijo.attrib.get("type", "").startswith("video"):
                        continue
                    return True
        if t == "link" and hijo.attrib.get("rel") == "enclosure":
            return True
    return bool(IMG_RX.search(descripcion or ""))


def probar(src):
    r = {"name": src["name"], "short": src.get("short", ""), "url": src["url"],
         "region": src.get("region", ""), "lang": src.get("lang", ""),
         "ok": False, "http": None, "items": 0, "imagen": False,
         "titular": "", "fecha": "", "error": ""}
    try:
        req = urllib.request.Request(src["url"], headers={
            "User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            crudo = resp.read()
            r["http"] = resp.status
            cab = resp.headers.get("Content-Type", "")
        cuerpo = decodificar(crudo, cab)
        if "<rss" not in cuerpo[:3000].lower() and "<feed" not in cuerpo[:3000].lower() \
                and "<rdf" not in cuerpo[:3000].lower():
            r["error"] = "no es XML de feed"
            return r
        raiz = ET.fromstring(crudo if crudo.lstrip().startswith(b"<") else cuerpo.encode("utf-8"))
        todos = [e for e in raiz.iter() if tag(e) in ("item", "entry")]
        r["items"] = len(todos)
        if todos:
            primero = todos[0]
            r["titular"] = limpio(texto(primero, {"title"}))
            desc = texto(primero, {"description", "summary", "content"})
            r["imagen"] = tiene_imagen(primero, desc)
            fecha = texto(primero, {"pubdate", "published", "updated", "date"})
            r["fecha"] = fecha[:25]
        r["ok"] = r["items"] > 0
    except urllib.error.HTTPError as e:
        r["http"] = e.code
        r["error"] = f"HTTP {e.code}"
    except urllib.error.URLError as e:
        r["error"] = f"red: {e.reason}"[:60]
    except ET.ParseError as e:
        r["error"] = f"XML roto: {e}"[:60]
    except Exception as e:  # noqa: BLE001
        r["error"] = f"{type(e).__name__}: {e}"[:60]
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(AQUI / "_resultado-fuentes.json"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--catalogo", default=str(CATALOGO))
    args = ap.parse_args()

    fuentes = json.loads(Path(args.catalogo).read_text(encoding="utf-8"))["candidatas"]
    print(f"probando {len(fuentes)} fuentes...\n")
    with futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        res = list(ex.map(probar, fuentes))

    res.sort(key=lambda x: (not x["ok"], -x["items"]))
    print(f"{'':2} {'items':>5} {'img':>3}  {'region':<6} {'fuente':<26} titular")
    print("-" * 132)
    for r in res:
        marca = "OK" if r["ok"] else "XX"
        img = "si" if r["imagen"] else "-"
        cab = (r["titular"] or r["error"])[:64]
        print(f"{marca:2} {r['items']:>5} {img:>3}  {r['region']:<6} {r['name'][:26]:<26} {cab}")

    ok = [r for r in res if r["ok"]]
    con_img = [r for r in ok if r["imagen"]]
    print("-" * 132)
    print(f"\nresponden {len(ok)}/{len(res)}  ·  con imagen {len(con_img)}  ·  "
          f"items totales {sum(r['items'] for r in ok)}")
    Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"detalle en {args.json}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
