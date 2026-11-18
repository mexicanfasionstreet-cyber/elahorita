"""Mide el clasificador de secciones contra noticias reales clasificadas a mano.

herramientas/secciones-oro.json trae 250 noticias del radar (noviembre 2026) con
la seccion y la region correctas; donde dos secciones son igual de validas, se
aceptan las dos. Tres muestras:

  ajuste      140 con las que se ajustaron las palabras clave
  validacion   60 que se usaron para corregir huecos generales
  ciega        50 apartadas: la medida mas honesta (antes de ajustar: 74 %)

Uso:
    python herramientas/evaluar-secciones.py          # clasificador por palabras
    python herramientas/evaluar-secciones.py --ia     # ademas, la revision con DeepSeek
    python herramientas/evaluar-secciones.py --errores
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import secciones  # noqa: E402

ORO = Path(__file__).resolve().parent / "secciones-oro.json"


def acierta(n, sec, reg):
    return (n["temas"] == "*" or sec in n["temas"]), reg in n["regiones"]


def reporte(nombre, noticias, resultados, errores=False):
    por = defaultdict(lambda: [0, 0, 0])
    for n, (sec, reg) in zip(noticias, resultados):
        t, r = acierta(n, sec, reg)
        m = por[n["muestra"]]
        m[0] += 1
        m[1] += t
        m[2] += r
        if errores and not (t and r):
            print(f"   [{n['muestra'][:5]}] {sec:<9} {'' if t else 'tema≠' + '/'.join(n['temas']):<24} "
                  f"{reg:<5} {'' if r else 'REGION':<6} {n['title'][:70]}")
    for muestra, (total, t, r) in por.items():
        print(f"{nombre:<9} {muestra:<10} seccion {t:>3}/{total} = {t / total:4.0%}   "
              f"region {r:>3}/{total} = {r / total:4.0%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ia", action="store_true")
    ap.add_argument("--errores", action="store_true")
    args = ap.parse_args()
    noticias = json.loads(ORO.read_text(encoding="utf-8"))

    palabras = [secciones.clasificar(n["title"], n["excerpt"], n["region_fuente"]) for n in noticias]
    reporte("palabras", noticias, palabras, args.errores)

    if args.ia:
        # cache aparte: se mide a la IA de verdad, no lo que ya respondio antes
        secciones.CACHE_IA = Path(tempfile.mkdtemp()) / "cache.json"
        items = [{"id": f"oro{i}", "title": n["title"], "excerpt": n["excerpt"]}
                 for i, n in enumerate(noticias)]
        respuestas = {}
        for i in range(0, len(items), 25):
            respuestas.update(secciones.con_ia(items[i:i + 25]))
        ia = [respuestas.get(f"oro{i}", palabras[i])[:2] for i in range(len(noticias))]
        sin = sum(1 for i in range(len(noticias)) if f"oro{i}" not in respuestas)
        print(f"\nIA respondio {len(noticias) - sin} de {len(noticias)} (el resto cuenta con palabras)")
        reporte("ia", noticias, ia, args.errores)
        print("\nsensibles (IA | palabras):")
        for i, n in enumerate(noticias):
            k_ia = respuestas.get(f"oro{i}", ("", "", ""))[2]
            k_pal = secciones.sensible(n["title"], n["excerpt"])
            if k_ia or k_pal:
                print(f"   {k_ia or '-':<15} {k_pal or '-':<15} {n['title'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
