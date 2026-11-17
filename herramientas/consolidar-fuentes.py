"""Consolida sources.json a partir de las pruebas de fuentes.

Cruza los catalogos de candidatas con su resultado de prueba y se queda solo con
las URLs que respondieron. Primero los espejos (los que traen mas notas), luego
las directas; si un medio ya entro por su `short`, se salta.

Uso: python herramientas/consolidar-fuentes.py
"""
from __future__ import annotations

import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent

PARES = [
    ("espejo", AQUI / "fuentes-espejo.json", AQUI / "_resultado-espejos.json"),
    ("directa", AQUI / "fuentes-candidatas.json", AQUI / "_resultado-fuentes.json"),
]

# medios que no se quieren aunque respondan (ruido, sensacionalismo o duplicado)
FUERA = {"Sopitas", "Sopitas (espejo)", "Mexico (busqueda)", "Ultimo momento MX"}


def main():
    salida, vistos = [], set()
    for origen, catalogo, resultado in PARES:
        cands = json.loads(catalogo.read_text(encoding="utf-8"))["candidatas"]
        ok = {r["url"] for r in json.loads(resultado.read_text(encoding="utf-8")) if r["ok"]}
        for c in cands:
            corto = c.get("short", "")
            if c["url"] not in ok or corto in vistos or c["name"] in FUERA:
                continue
            vistos.add(corto)
            item = {
                "name": c["name"].replace(" (espejo)", ""),
                "short": corto,
                "url": c["url"],
                "weight": c.get("weight", 3.0),
                "lang": c.get("lang", "es"),
                "region": c.get("region", "mx"),
                "kind": c.get("kind", "news"),
            }
            if origen == "espejo":
                item["mirror"] = True
                item["aggregator"] = bool(c.get("aggregator"))
            else:
                item["generic"] = False
            salida.append(item)

    salida.sort(key=lambda x: (-x["weight"], x["name"]))
    doc = {
        "_comment": ("El Ahorita. Noticias de Mexico y el mundo. "
                     "Generado el 2026-11-17 por herramientas/consolidar-fuentes.py; "
                     "validar con herramientas/probar-fuentes.py antes de tocar."),
        "sources": salida,
    }
    destino = RAIZ / "sources.json"
    destino.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    directas = [s for s in salida if not s.get("mirror")]
    espejos = [s for s in salida if s.get("mirror")]
    print(f"{len(salida)} fuentes -> {destino}")
    print(f"  directas {len(directas)}  ·  espejos {len(espejos)}")
    print(f"  mx {sum(1 for s in salida if s['region'] == 'mx')}"
          f"  ·  oficiales {sum(1 for s in salida if s['kind'] == 'official')}")


if __name__ == "__main__":
    main()
