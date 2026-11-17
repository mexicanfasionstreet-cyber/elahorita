"""Genera la voz de la capsula: un audio por segmento y el total concatenado.

Hoy usa edge-tts (voces neuronales de Microsoft, gratis). El adaptador para
Voicebox esta previsto: si VOICEBOX_URL y VOICEBOX_PROFILE_ID estan puestos se
intenta primero y, si no responde, se cae a edge-tts avisando.

Uso:
    python voz.py                       # el guion mas reciente
    python voz.py --guion docs/guiones/2026-11-17-dia.json
    python voz.py --proveedor voicebox
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ.parent / ".deps"))  # edge-tts y compania, si estan aqui

import config  # noqa: E402

BUILD = RAIZ / "build"
SILENCIO = 0.28  # segundos de aire entre segmentos


def duracion(ruta):
    salida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(ruta)],
        capture_output=True, text=True, check=True)
    return float(salida.stdout.strip())


def segmentos_de(guion):
    """Convierte el guion en segmentos con su etiqueta en pantalla."""
    segs = [{"id": "gancho", "tipo": "gancho", "kicker": "EL AHORITA",
             "pantalla": guion.get("gancho_pantalla", ""), "texto": guion["gancho"]}]
    for i, n in enumerate(guion.get("notas", []), 1):
        segs.append({"id": f"nota{i}", "tipo": "nota",
                     "kicker": (n.get("kicker") or "").upper(),
                     "pantalla": n.get("pantalla", ""),
                     "texto": n["texto"]})
    segs.append({"id": "cierre", "tipo": "cierre", "kicker": "EL AHORITA",
                 "texto": guion.get("cierre", "")})
    return [s for s in segs if s["texto"].strip()]


async def _edge(texto, salida, voz, ritmo):
    """Genera el audio y devuelve el tiempo de cada palabra (para los subtitulos).

    edge-tts entrega eventos WordBoundary con offset y duracion en unidades de
    100 ns desde el inicio del audio de ese segmento.
    """
    import edge_tts
    com = edge_tts.Communicate(texto, voz, rate=ritmo, boundary="WordBoundary")
    palabras = []
    with open(salida, "wb") as f:
        async for trozo in com.stream():
            if trozo["type"] == "audio":
                f.write(trozo["data"])
            elif trozo["type"] == "WordBoundary":
                palabras.append({
                    "texto": trozo["text"],
                    "t0": round(trozo["offset"] / 1e7, 3),
                    "dur": round(trozo["duration"] / 1e7, 3),
                })
    return palabras


def con_edge_tts(texto, salida):
    return asyncio.run(_edge(texto, salida, config.VOZ, config.VOZ_RITMO))


def con_voicebox(texto, salida):
    """Pide la voz clonada al servidor Voicebox (API REST local/tailnet)."""
    import time

    import urllib.error
    import urllib.request

    if not (config.VOICEBOX_URL and config.VOICEBOX_PROFILE):
        raise RuntimeError("Voicebox sin configurar")
    cuerpo = json.dumps({
        "text": texto, "profile_id": config.VOICEBOX_PROFILE,
        "language": "es", "engine": "qwen3-tts",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{config.VOICEBOX_URL}/generate", data=cuerpo,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        gen = json.load(r)
    gid = gen.get("generation_id") or gen.get("id")
    if not gid:
        raise RuntimeError(f"Voicebox no devolvio id: {gen}")

    limite = time.time() + config.VOICEBOX_TIMEOUT
    while time.time() < limite:
        with urllib.request.urlopen(f"{config.VOICEBOX_URL}/generations/{gid}", timeout=30) as r:
            estado = json.load(r)
        if estado.get("status") in ("complete", "completed", "done"):
            break
        if estado.get("status") in ("failed", "error"):
            raise RuntimeError(f"Voicebox fallo: {estado}")
        time.sleep(1.5)
    else:
        raise RuntimeError("Voicebox no termino a tiempo")

    with urllib.request.urlopen(f"{config.VOICEBOX_URL}/generations/{gid}/audio", timeout=60) as r:
        datos = r.read()
    salida.write_bytes(datos)
    return salida


def generar_voz(guion, proveedor="edge"):
    """Devuelve la lista de segmentos con su audio y su duracion real."""
    carpetas = BUILD / guion["_nombre"]
    voces = carpetas / "voz"
    voces.mkdir(parents=True, exist_ok=True)

    segs = segmentos_de(guion)
    for i, s in enumerate(segs, 1):
        limpio = re.sub(r"\s+", " ", s["texto"]).strip()
        s["texto"] = limpio
        destino = voces / f"{i:02d}-{s['id']}.mp3"
        hecho = None
        if proveedor == "voicebox":
            try:
                hecho = con_voicebox(limpio, destino)
            except Exception as e:  # noqa: BLE001
                print(f"  Voicebox no responde ({e}); se usa la voz de respaldo")
        palabras = []
        if hecho is None:
            palabras = con_edge_tts(limpio, destino)
            s["voz"] = "edge-tts"
        else:
            hecho = hecho
            s["voz"] = "voicebox"
        s["audio"] = str(destino)
        s["dur"] = round(duracion(destino), 2)
        s["palabras"] = palabras
        print(f"  {s['id']:<8} {s['dur']:>6.2f} s  [{s['voz']}]  "
              f"{len(palabras)} palabras con tiempo  {limpio[:44]}…")

    # audio completo: segmentos con un respiro entre ellos
    total = carpetas / "voz-completa.mp3"
    sil = SILENCIO
    filtros = [f"[{i}:a]apad=pad_dur={sil}[a{i}]" for i in range(len(segs))]
    entradas = []
    for s in segs:
        entradas += ["-i", s["audio"]]
    grafo = ";".join(filtros) + ";" + "".join(f"[a{i}]" for i in range(len(segs))) \
        + f"concat=n={len(segs)}:v=0:a=1[out]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *entradas,
                    "-filter_complex", grafo, "-map", "[out]", str(total)],
                   check=True)
    return segs, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guion", default="")
    ap.add_argument("--proveedor", default="edge", choices=["edge", "voicebox"])
    args = ap.parse_args()

    if args.guion:
        ruta = Path(args.guion)
    else:
        cands = sorted((RAIZ / "docs" / "guiones").glob("*.json"))
        if not cands:
            raise SystemExit("no hay guiones en docs/guiones/")
        ruta = cands[-1]
    guion = json.loads(ruta.read_text(encoding="utf-8"))
    guion = guion.get("guion", guion)  # el archivo envuelve el guion con metadatos
    guion["_nombre"] = ruta.stem

    n_pal = guion.get("palabras") or sum(
        len(s.split()) for s in [guion.get("gancho", "")] +
        [n["texto"] for n in guion.get("notas", [])] + [guion.get("cierre", "")])
    print(f"guion {ruta.name} · {n_pal} palabras · proveedor {args.proveedor}\n")

    segs, total = generar_voz(guion, args.proveedor)
    dur = duracion(total)
    print(f"\ntotal voz: {dur:.2f} s ({len(segs)} segmentos)")
    if dur > 78:
        print("aviso: pasa de 78 s; conviene recortar el guion")

    # el audio concatenado lleva 0.28 s de aire despues de cada segmento, asi que
    # el inicio de cada segmento se acumula: eso da el tiempo absoluto por palabra
    cursor = 0.0
    for s in segs:
        s["inicio"] = round(cursor, 3)
        for p in s.get("palabras", []):
            p["abs"] = round(cursor + p["t0"], 3)
        cursor += float(s["dur"]) + SILENCIO

    manifiesto = BUILD / guion["_nombre"] / "voz.json"
    manifiesto.write_text(json.dumps(
        {"segmentos": segs, "total_seg": round(dur, 2), "voz": config.VOZ,
         "ritmo": config.VOZ_RITMO}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"audio -> {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
