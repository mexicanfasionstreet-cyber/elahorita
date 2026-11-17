"""Busca la URL real del feed de cada medio probando rutas tipicas.

Solo biblioteca estandar. Uso: python herramientas/buscar-feeds.py [--workers 6]

Existe porque las URLs de RSS cambian sin avisar y muchas veces el dominio
responde 404 o devuelve HTML en la ruta vieja. Prueba las rutas habituales
(/arc/outboundfeeds/rss/, /feed/, /rss/, /rss.xml) y dice cual trae items.
"""
from __future__ import annotations

import concurrent.futures as futures
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

AQUI = Path(__file__).resolve().parent

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
TIMEOUT = 20

RUTAS = ["/arc/outboundfeeds/rss/", "/feed/", "/rss/", "/rss.xml"]

# sitios que fallaron en la primera pasada
SITIOS = {
    "El Universal": "https://www.eluniversal.com.mx",
    "Milenio": "https://www.milenio.com",
    "El Financiero": "https://www.elfinanciero.com.mx",
    "El Economista": "https://www.eleconomista.com.mx",
    "Animal Politico": "https://www.animalpolitico.com",
    "Proceso": "https://www.proceso.com.mx",
    "Aristegui Noticias": "https://aristeguinoticias.com",
    "Sin Embargo": "https://www.sinembargo.mx",
    "Excelsior": "https://www.excelsior.com.mx",
    "El Debate": "https://www.debate.com.mx",
    "El Informador": "https://www.informador.mx",
    "El Imparcial": "https://elimparcial.com",
    "Frontera.info": "https://www.frontera.info",
    "El Mexicano": "https://www.el-mexicano.com.mx",
    "Expansion": "https://expansion.mx",
    "Bloomberg Linea": "https://www.bloomberglinea.com",
    "Forbes Mexico": "https://www.forbes.com.mx",
    "CNN en Espanol": "https://cnnespanol.cnn.com",
    "N+": "https://www.nmas.com.mx",
    "Sopitas": "https://www.sopitas.com",
    "SDP Noticias": "https://www.sdpnoticias.com",
    "La Silla Rota": "https://lasillarota.com",
    "El Sol de Mexico": "https://www.elsoldemexico.com.mx",
    "La Opinion": "https://laopinion.com",
    "El Diario de Juarez": "https://diario.mx",
    "Emeequis": "https://www.emeequis.com",
}

# URLs concretas que no siguen las rutas tipicas
ESPECIALES = {
    "Presidencia": ["https://www.gob.mx/presidencia/es/rss",
                    "https://www.gob.mx/presidencia/es/articulos/rss",
                    "https://www.gob.mx/rss/presidencia"],
    "SSPC": ["https://www.gob.mx/sspc/es/rss",
             "https://www.gob.mx/sspc/es/articulos/rss"],
    "Proteccion Civil": ["https://www.gob.mx/proteccioncivil/es/rss",
                         "https://www.gob.mx/proteccioncivil/es/articulos/rss"],
    "CENAPRED": ["https://www.gob.mx/cenapred/es/rss",
                 "https://www.gob.mx/cenapred/es/articulos/rss"],
    "DW Espanol": ["https://rss.dw.com/xml/rss-es-all",
                   "https://rss.dw.com/rdf/rss-es-all",
                   "https://www.dw.com/es/rss"],
}

CANDIDATAS = [(n, [SITIOS[n] + r for r in RUTAS]) for n in SITIOS]
CANDIDATAS += list(ESPECIALES.items())


def probar(par):
    nombre, url = par
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            crudo = r.read(600000)
        cabeza = crudo[:3000].lower()
        if b"<rss" not in cabeza and b"<feed" not in cabeza and b"<rdf" not in cabeza:
            return {"name": nombre, "url": url, "ok": False, "items": 0, "nota": "no es feed"}
        raiz = ET.fromstring(crudo)
        items = [e for e in raiz.iter() if e.tag.split("}")[-1].lower() in ("item", "entry")]
        primero = ""
        for e in items[0].iter() if items else []:
            if e.tag.split("}")[-1].lower() == "title" and (e.text or "").strip():
                primero = " ".join(e.text.split())[:70]
                break
        return {"name": nombre, "url": url, "ok": bool(items), "items": len(items),
                "nota": primero}
    except urllib.error.HTTPError as e:
        return {"name": nombre, "url": url, "ok": False, "items": 0, "nota": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"name": nombre, "url": url, "ok": False, "items": 0,
                "nota": f"{type(e).__name__}"}


def main():
    trabajos = [(n, u) for n, urls in CANDIDATAS for u in urls]
    print(f"probando {len(trabajos)} URLs de {len(CANDIDATAS)} sitios...\n")
    with futures.ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(probar, trabajos))

    mejores = {}
    for r in res:
        if r["ok"] and (r["name"] not in mejores or r["items"] > mejores[r["name"]]["items"]):
            mejores[r["name"]] = r
    for nombre, _ in CANDIDATAS:
        m = mejores.get(nombre)
        if m:
            print(f"OK  {m['items']:>4}  {nombre:<20} {m['url']}")
        else:
            intentos = sorted({r["nota"] for r in res if r["name"] == nombre})
            print(f"XX   ---  {nombre:<20} {', '.join(intentos)[:60]}")

    print(f"\n{len(mejores)}/{len(CANDIDATAS)} sitios con feed encontrado")
    salida = AQUI / "_feeds-encontrados.json"
    salida.write_text(json.dumps(mejores, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"detalle en {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
