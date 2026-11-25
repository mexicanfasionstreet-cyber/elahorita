"""Genera la voz de la capsula: un audio por segmento y el total concatenado.

Proveedores, en orden (el primero que este configurado):
  1. ElevenLabs (ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID): voz principal; trae
     los tiempos por caracter, asi que los subtitulos no necesitan Whisper.
  2. Voicebox (VOICEBOX_URL + perfil): servidor propio por Tailscale.
  3. edge-tts: voz de respaldo gratis.
Si el principal falla, el video entero va con edge-tts y llega un aviso al chat.

Uso:
    python voz.py                       # el guion mas reciente
    python voz.py --guion docs/guiones/2026-11-17-dia.json
    python voz.py --proveedor elevenlabs
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


API_ELEVEN = "https://api.elevenlabs.io/v1/text-to-speech/{voz}/with-timestamps"


def _palabras_de_alineacion(al):
    """Caracteres con tiempo -> palabras {texto, t0, dur} (como edge-tts)."""
    chars = al.get("characters") or []
    ini = al.get("character_start_times_seconds") or []
    fin = al.get("character_end_times_seconds") or []
    palabras, actual = [], None
    for c, a, b in zip(chars, ini, fin):
        if c.isspace():
            if actual:
                palabras.append(actual)
                actual = None
            continue
        if actual is None:
            actual = {"texto": c, "t0": float(a), "t1": float(b)}
        else:
            actual["texto"] += c
            actual["t1"] = float(b)
    if actual:
        palabras.append(actual)
    return [{"texto": p["texto"], "t0": round(p["t0"], 3),
             "dur": round(max(0.05, p["t1"] - p["t0"]), 3)} for p in palabras]


def con_elevenlabs(texto, salida, llamar=None):
    """Genera el mp3 del segmento y devuelve sus palabras con tiempo.

    Reintenta una vez si ElevenLabs esta saturado (429/5xx). Los errores de
    cuenta (llave mala, sin creditos, voz que no existe) se dicen tal cual.
    """
    import base64
    import time
    import urllib.error
    import urllib.request

    if not (config.ELEVENLABS_KEY and config.ELEVENLABS_VOZ):
        raise RuntimeError("faltan ELEVENLABS_API_KEY o ELEVENLABS_VOICE_ID")
    cuerpo = {"text": texto, "model_id": config.ELEVENLABS_MODELO}
    if abs(config.ELEVENLABS_VELOCIDAD - 1.0) > 1e-6:
        cuerpo["voice_settings"] = {"speed": config.ELEVENLABS_VELOCIDAD}

    def _llamar_api(cuerpo):
        url = API_ELEVEN.format(voz=config.ELEVENLABS_VOZ) + "?output_format=mp3_44100_128"
        req = urllib.request.Request(url, data=json.dumps(cuerpo).encode("utf-8"), method="POST",
                                     headers={"xi-api-key": config.ELEVENLABS_KEY,
                                              "Content-Type": "application/json",
                                              "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=config.ELEVENLABS_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))

    llamar = llamar or _llamar_api
    for intento in (1, 2):
        try:
            datos = llamar(cuerpo)
            break
        except urllib.error.HTTPError as e:
            detalle = e.read()[:300].decode("utf-8", "replace")
            if intento == 1 and (e.code == 429 or e.code >= 500):
                time.sleep(4)
                continue
            raise RuntimeError(f"ElevenLabs {e.code}: {detalle}") from None
    audio = base64.b64decode(datos.get("audio_base64") or "")
    if len(audio) < 1000:
        raise RuntimeError("ElevenLabs devolvio un audio vacio")
    Path(salida).write_bytes(audio)
    return _palabras_de_alineacion(datos.get("alignment") or datos.get("normalized_alignment") or {})


def _vb_json(ruta, cuerpo=None, timeout=30):
    """Llamada a la API de Voicebox; los errores traen el detalle que da el servidor."""
    import urllib.error
    import urllib.request

    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(
        f"{config.VOICEBOX_URL}{ruta}", data=datos, method="POST" if datos else "GET",
        headers={"Content-Type": "application/json"} if datos else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detalle = e.read()[:300].decode("utf-8", "replace")
        raise RuntimeError(f"Voicebox {ruta} respondio {e.code}: {detalle}") from None


def con_voicebox(texto, salida):
    """Pide la voz clonada al servidor Voicebox (API REST local/tailnet).

    Rutas de la API actual de Voicebox (backend/routes en jamiepine/voicebox):
      POST /generate        -> {"id", "status": "generating", ...}
      GET  /history/{id}    -> status: generating | completed | failed
      GET  /audio/{id}      -> el archivo de audio (normalmente wav)
    El motor no se manda: Voicebox usa el del perfil. Si hace falta forzarlo,
    VOICEBOX_ENGINE acepta qwen, chatterbox, luxtts, etc. ("qwen3-tts" no existe).
    """
    import time
    import urllib.request

    if not (config.VOICEBOX_URL and config.VOICEBOX_PROFILE):
        raise RuntimeError("Voicebox sin configurar")
    pedido = {"text": texto, "profile_id": config.VOICEBOX_PROFILE, "language": "es"}
    if config.VOICEBOX_ENGINE:
        pedido["engine"] = config.VOICEBOX_ENGINE
    gen = _vb_json("/generate", pedido)
    gid = gen.get("id") or gen.get("generation_id")
    if not gid:
        raise RuntimeError(f"Voicebox no devolvio id: {str(gen)[:200]}")

    estado = gen
    limite = time.time() + config.VOICEBOX_TIMEOUT
    while estado.get("status") not in ("completed", "complete", "done"):
        if estado.get("status") in ("failed", "error"):
            raise RuntimeError(f"Voicebox fallo: {estado.get('error') or estado}")
        if time.time() > limite:
            raise RuntimeError(f"Voicebox no termino en {config.VOICEBOX_TIMEOUT} s")
        time.sleep(1.5)
        estado = _vb_json(f"/history/{gid}")

    with urllib.request.urlopen(f"{config.VOICEBOX_URL}/audio/{gid}", timeout=60) as r:
        datos = r.read()
        tipo = r.headers.get("Content-Type", "")
    # Voicebox entrega wav; el resto de la tuberia espera mp3
    crudo = salida.with_suffix(".mp3.src" if "mpeg" in tipo else ".wav")
    crudo.write_bytes(datos)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(crudo),
                    "-c:a", "libmp3lame", "-b:a", "192k", str(salida)], check=True)
    crudo.unlink(missing_ok=True)
    return salida


def _evento(tipo, texto):
    try:
        import franjas
        franjas.registrar_evento(tipo, texto)
    except Exception:  # noqa: BLE001
        pass


def _avisar(texto):
    """Manda un aviso al chat sin romper la tuberia si Telegram falla."""
    try:
        import telegram
        telegram.mandar(texto)
    except BaseException as e:  # noqa: BLE001  (_llamar usa SystemExit)
        print(f"  aviso no enviado ({type(e).__name__})")


def generar_voz(guion, proveedor="edge"):
    """Devuelve la lista de segmentos con su audio y su duracion real.

    Con Voicebox es todo o nada: si un segmento falla, el video entero se hace
    con la voz de respaldo, para no mezclar la voz principal con la de respaldo.
    """
    import html

    carpetas = BUILD / guion["_nombre"]
    voces = carpetas / "voz"
    voces.mkdir(parents=True, exist_ok=True)

    segs = segmentos_de(guion)
    for i, s in enumerate(segs, 1):
        s["texto"] = re.sub(r"\s+", " ", s["texto"]).strip()
        s["destino"] = voces / f"{i:02d}-{s['id']}.mp3"

    externa = False                     # True: la voz principal hizo todo el video
    if proveedor == "elevenlabs":
        try:
            for s in segs:
                s["palabras"] = con_elevenlabs(s["texto"], s["destino"])
                s["voz"] = "elevenlabs"
            externa = True
        except Exception as e:  # noqa: BLE001
            print(f"  ElevenLabs fallo ({e}); se usa la voz de respaldo")
            _evento("voz_respaldo", e)
            _avisar("<b>ElevenLabs no respondio</b>; este video va con la voz de respaldo.\n"
                    f"<pre>{html.escape(str(e)[:400])}</pre>")

    usar_voicebox = proveedor == "voicebox"
    if usar_voicebox:
        try:
            for s in segs:
                con_voicebox(s["texto"], s["destino"])
                s["voz"], s["palabras"] = "voicebox", []
        except Exception as e:  # noqa: BLE001
            print(f"  Voicebox no responde ({e}); se usa la voz de respaldo")
            _evento("voz_respaldo", e)
            _avisar("<b>Voicebox no respondio</b>; este video va con la voz de respaldo.\n"
                    f"<pre>{html.escape(str(e)[:400])}</pre>")
            usar_voicebox = False

    if usar_voicebox:
        # Voicebox no da tiempos por palabra: se sacan con Whisper para el karaoke.
        # Si falla, el video sale igual con la voz de Carla, solo sin subtitulos.
        fallo = None
        for s in segs:
            s["palabras"] = []
            try:
                import alinear
                s["palabras"] = alinear.palabras(s["destino"], s["texto"],
                                                 duracion(s["destino"]))
            except Exception as e:  # noqa: BLE001
                fallo = fallo or e
                print(f"  sin tiempos por palabra en {s['id']} ({type(e).__name__}: {e})")
        if fallo:
            _evento("subtitulos", fallo)
            _avisar("<b>Subtitulos incompletos</b>: no se pudieron sacar los tiempos "
                    f"de la voz de Carla.\n<pre>{html.escape(str(fallo)[:300])}</pre>")

    for s in segs:
        destino = s.pop("destino")
        limpio = s["texto"]
        if not (usar_voicebox or externa):
            s["palabras"] = con_edge_tts(limpio, destino)
            s["voz"] = "edge-tts"
        palabras = s["palabras"]
        s["audio"] = str(destino)
        s["dur"] = round(duracion(destino), 2)
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


def proveedor_auto():
    if config.ELEVENLABS_KEY and config.ELEVENLABS_VOZ:
        return "elevenlabs"
    if config.VOICEBOX_URL and config.VOICEBOX_PROFILE:
        return "voicebox"
    return "edge"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guion", default="")
    ap.add_argument("--proveedor", default="auto", choices=["auto", "edge", "voicebox", "elevenlabs"])
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
    if args.proveedor == "auto":
        args.proveedor = proveedor_auto()

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
