"""Puntua la relevancia de cada historia del dia.

Cuatro senales, todas calculables con lo que el motor ya produce:

  cobertura  cuantos medios la publican y cuanto pesa cada uno (la mas importante:
             lo que varios medios consideran noticia, es noticia)
  recencia   cuanto hace que salio (decae con semivida de 12 h)
  pico       si un personaje o institucion aparece de golpe en muchos titulares
             del dia, algo esta pasando con el
  seccion    peso editorial del tema (seguridad y clima arriba, cultura abajo)

Uso:
    python relevancia.py            # top 10 del dia
    python relevancia.py --top 20
    python relevancia.py --json ranking.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from aggregate import CAT_BOOST, entidades, norm

RAIZ = Path(__file__).resolve().parent
RANKING = RAIZ / "docs" / "data" / "latest.json"

# peso de cada senal (suman 1.0)
PESOS = {"cobertura": 0.40, "recencia": 0.20, "pico": 0.20, "seccion": 0.10}
# margen para el "otro" 0.10: se reparte como bonus de imagen, que hace la capsula posible
PESO_IMAGEN = 0.10

SEMIVIDA_H = 12.0
COBERTURA_TOPE = 26.0   # suma de pesos de medios que ya se considera cobertura total
PICO_TOPE = 10.0        # apariciones de una entidad para considerarlo "pico"


def _horas(pub):
    try:
        dt = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return 48.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)


def _pesos_por_medio(items):
    """Peso editorial de cada medio, a partir de lo que ya trae cada noticia."""
    pesos = {}
    for it in items:
        pesos.setdefault(it["source_name"], float(it.get("weight", 3.0)))
    return pesos


def _spikes(items):
    """Cuenta en cuantos titulares aparece cada entidad (pico de atencion)."""
    cuenta = Counter()
    en_item = []
    for it in items:
        ent = entidades(it["title"])
        en_item.append(ent)
        for e in ent:
            cuenta[e] += 1
    return cuenta, en_item


def puntuar(items, ahora=None):
    pesos = _pesos_por_medio(items)
    spikes, ents_por_item = _spikes(items)
    filas = []
    for it, ent in zip(items, ents_por_item):
        medios = [it["source_name"]] + list(it.get("also") or [])
        peso_cob = sum(pesos.get(m, 3.0) for m in medios)
        cobertura = min(peso_cob / COBERTURA_TOPE, 1.0)

        horas = _horas(it.get("published"))
        recencia = 0.5 ** (horas / SEMIVIDA_H)

        pico = 0.0
        pico_ent = ""
        for e in ent:
            v = min(spikes[e] / PICO_TOPE, 1.0)
            if v > pico:
                pico, pico_ent = v, e

        slugs = it.get("tags") or ["industria"]
        seccion = CAT_BOOST.get(slugs[0], 0.5)
        imagen = 1.0 if (it.get("image") or "").startswith("http") else 0.0

        score = 100 * (
            PESOS["cobertura"] * cobertura
            + PESOS["recencia"] * recencia
            + PESOS["pico"] * pico
            + PESOS["seccion"] * seccion
            + PESO_IMAGEN * imagen
        )
        filas.append({
            "score": round(score, 1),
            "title": it["title"],
            "link": it.get("link", ""),
            "seccion": slugs[0],
            "medios": len(medios),
            "peso_cobertura": round(peso_cob, 1),
            "horas": round(horas, 1),
            "updated": it.get("updated") or it.get("published"),
            "pico_entidad": pico_ent,
            "pico": round(pico, 2),
            "imagen": bool(imagen),
            "imagen_url": it.get("image", ""),
            "_ents": ent,
            "desglose": {
                "cobertura": round(cobertura, 3), "recencia": round(recencia, 3),
                "pico": round(pico, 3), "seccion": round(seccion, 3), "imagen": imagen,
            },
        })
    filas.sort(key=lambda x: -x["score"])
    return filas


def diversificar(filas, n=None):
    """Elige historias sin repetir personaje ni institucion.

    Un clip lleva una o dos notas: si las dos mejores hablan de la misma persona,
    el canal parece monotematico y desperdicia la segunda. Se recorre el ranking y
    se toma la primera historia que no comparta ninguna entidad con las ya elegidas.
    """
    elegidas, usadas = [], []
    for f in filas:
        ent = f.get("_ents") or set()
        if any(ent & u for u in usadas):
            continue
        elegidas.append(f)
        usadas.append(ent)
        if n and len(elegidas) >= n:
            break
    return elegidas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--json", default="")
    ap.add_argument("--diversidad", action="store_true",
                    help="no repetir personaje ni institucion entre historias")
    ap.add_argument("--archivo", default=str(RANKING))
    args = ap.parse_args()

    datos = json.loads(Path(args.archivo).read_text(encoding="utf-8"))
    items = datos["items"] if isinstance(datos, dict) and "items" in datos else datos
    filas = puntuar(items)
    vista = diversificar(filas) if args.diversidad else filas

    modo = " · sin repetir personajes" if args.diversidad else ""
    print(f"{len(items)} noticias · {len(filas)} historias{modo}\n")
    for i, f in enumerate(vista[:args.top], 1):
        print(f"{i:>2}. {f['score']:>5}  [{f['seccion']}] {f['medios']} medio(s) "
              f"· peso {f['peso_cobertura']} · hace {f['horas']} h"
              + (f" · pico: {f['pico_entidad']}" if f['pico_entidad'] else "")
              + (" · con foto" if f["imagen"] else ""))
        print(f"    {f['title'][:104]}")

    if args.json:
        limpias = [{k: v for k, v in f.items() if k != "_ents"} for f in filas]
        Path(args.json).write_text(json.dumps(limpias, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nranking completo en {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
