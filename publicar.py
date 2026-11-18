"""Sube un Short a YouTube.

Solo YouTube: corto, sin dependencias. Usa el refresh token del proyecto de Google
Cloud (flujo de dispositivo) y la YouTube Data API v3.

Uso:
    python publicar.py --video docs/videos/2026-11-17-nota.mp4
    python publicar.py --video X.mp4 --guion docs/guiones/X.json --privacidad public
    python publicar.py --video X.mp4 --solo-titulo        # ver que se subiria

Coste de cuota: 1.600 unidades por subida; el proyecto trae 10.000 al dia, o sea
6 videos diarios como maximo.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402

API_SUBIR = "https://www.googleapis.com/upload/youtube/v3/videos"
API_TOKEN = "https://oauth2.googleapis.com/token"
HASHTAGS = "#ElAhorita #Noticias #Mexico #Shorts"
LINEA_DE_LA_VIDA = ("Si tú o alguien que conoces está pasando por un momento difícil, llama gratis "
                    "a la Línea de la Vida: 800 911 2000 (24 horas, confidencial).")


def _post_form(url, datos):
    cuerpo = urllib.parse.urlencode(datos).encode()
    req = urllib.request.Request(url, data=cuerpo, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def token_de_acceso():
    """Cambia el refresh token por un access token de corta vida."""
    if not (config.YT_CLIENT_ID and config.YT_CLIENT_SECRET and config.YT_REFRESH):
        raise SystemExit("faltan YT_CLIENT_ID, YT_CLIENT_SECRET o YT_REFRESH_TOKEN en .env")
    datos = _post_form(API_TOKEN, {
        "client_id": config.YT_CLIENT_ID,
        "client_secret": config.YT_CLIENT_SECRET,
        "refresh_token": config.YT_REFRESH,
        "grant_type": "refresh_token",
    })
    return datos["access_token"]


def canal(acceso=None):
    """Dice a que canal pertenece el token: evita subir al canal equivocado."""
    acceso = acceso or token_de_acceso()
    url = ("https://www.googleapis.com/youtube/v3/channels"
           "?part=snippet&mine=true")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {acceso}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            datos = json.load(r)
    except urllib.error.HTTPError as e:
        detalle = e.read()[:300].decode("utf-8", "replace")
        raise SystemExit(f"YouTube rechazo la consulta ({e.code}): {detalle}")
    items = datos.get("items") or []
    if not items:
        return None
    it = items[0]
    return {"id": it["id"], "nombre": it["snippet"]["title"]}


def limpiar_titulo(texto, largo=95):
    """Titulo listo para YouTube: sin punto final ni comillas, sin gritar, cortado en palabra."""
    t = re.sub(r"\s+", " ", texto or "").strip().strip('"\'“”«»').strip()
    t = t.rstrip(".").strip()
    letras = [c for c in t if c.isalpha()]
    if len(letras) > 3 and sum(c.isupper() for c in letras) / len(letras) > 0.8:
        # TODO EN MAYUSCULAS (un rotulo de pantalla): se baja a escritura normal
        t = t.lower()
    if t:
        t = t[0].upper() + t[1:]
    if len(t) > largo:
        corte = t[:largo - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
        t = corte + "…"
    return t


def textos(video, guion_path=None):
    """Titulo y descripcion a partir del guion, si existe."""
    titulo, descripcion = video.stem.replace("-", " ").title(), ""
    enlaces = []
    if guion_path and Path(guion_path).exists():
        datos = json.loads(Path(guion_path).read_text(encoding="utf-8"))
        g = datos.get("guion", datos)
        gancho = (g.get("gancho") or "").strip()
        notas = g.get("notas") or []
        # el titulo que escribio el guionista; si no hay, el titular de la primera
        # nota (quien + que paso); el rotulo del gancho solo como ultimo recurso
        titulo = next((t for t in (g.get("titulo"),
                                   notas[0].get("pantalla") if notas else "",
                                   g.get("gancho_pantalla"), gancho)
                       if (t or "").strip()), titulo)
        partes = [gancho] if gancho else []
        for h in datos.get("historias", []):
            if h.get("link"):
                enlaces.append(h["link"])
        if enlaces:
            partes.append("Fuentes: " + " · ".join(enlaces[:3]))
        creditos = []
        for h in datos.get("historias", []):
            c = (h.get("foto") or {}).get("credito")
            if c and c not in creditos:
                creditos.append(c)
        if creditos:
            partes.append("Fotos: " + " · ".join(creditos))
        if os.environ.get("MUSICA_CREDITO"):
            partes.append("Música: " + os.environ["MUSICA_CREDITO"].strip())
        if any(h.get("sensible") == "suicidio" for h in datos.get("historias", [])):
            partes.append(LINEA_DE_LA_VIDA)
        partes.append(HASHTAGS)
        descripcion = "\n\n".join(p for p in partes if p)
    else:
        descripcion = HASHTAGS

    titulo = limpiar_titulo(titulo)          # YouTube corta a 100
    if "#shorts" not in descripcion.lower() and "#shorts" not in titulo.lower():
        titulo = (titulo + " #Shorts")[:100]
    return titulo, descripcion[:4900]


def subir(video, titulo, descripcion, privacidad="public", categoria="25"):
    """Sube el archivo por carga reanudable y devuelve el id del video."""
    video = Path(video)
    if not video.exists():
        raise SystemExit(f"no existe {video}")
    acceso = token_de_acceso()

    metadatos = {
        "snippet": {
            "title": titulo,
            "description": descripcion,
            "categoryId": categoria,          # 25 = News & Politics
            "defaultLanguage": "es",
            "defaultAudioLanguage": "es",
        },
        "status": {
            "privacyStatus": privacidad,
            "selfDeclaredMadeForKids": False,
            # voz clonada / sintetica: YouTube pide declarar el contenido alterado
            # o sintetico realista (status.containsSyntheticMedia, desde oct 2024)
            "containsSyntheticMedia": True,
        },
    }
    cuerpo = json.dumps(metadatos).encode("utf-8")
    url = API_SUBIR + "?uploadType=resumable&part=snippet,status"
    req = urllib.request.Request(url, data=cuerpo, method="POST", headers={
        "Authorization": f"Bearer {acceso}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(video.stat().st_size),
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            destino = r.headers.get("Location")
    except urllib.error.HTTPError as e:
        detalle = e.read()[:400].decode("utf-8", "replace")
        raise SystemExit(f"YouTube rechazo los metadatos ({e.code}): {detalle}")
    if not destino:
        raise SystemExit("YouTube no devolvio la URL de subida")

    datos = video.read_bytes()
    req = urllib.request.Request(destino, data=datos, method="PUT", headers={
        "Content-Type": "video/mp4",
        "Content-Length": str(len(datos)),
    })
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            respuesta = json.load(r)
    except urllib.error.HTTPError as e:
        detalle = e.read()[:400].decode("utf-8", "replace")
        raise SystemExit(f"fallo la subida ({e.code}): {detalle}")
    snip = respuesta.get("snippet") or {}
    if snip.get("channelTitle"):
        print(f"  canal: {snip['channelTitle']}  ·  id {snip.get('channelId', '')}")
    return respuesta.get("id", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--guion", default="")
    ap.add_argument("--privacidad", default="public",
                    choices=["public", "unlisted", "private"])
    ap.add_argument("--solo-titulo", action="store_true")
    ap.add_argument("--canal", action="store_true", help="solo decir a que canal apunta el token")
    args = ap.parse_args()

    if args.canal:
        print("nota: leer el canal necesita el permiso youtube.readonly.")
        print("con el token actual la verificacion sale al subir un video en privado.\n")
        info = canal()
        if not info:
            print("el token no tiene ningun canal asociado")
            return 1
        print(f"canal: {info['nombre']}  ·  id {info['id']}")
        return 0

    titulo, descripcion = textos(Path(args.video), args.guion)
    if args.solo_titulo:
        print(f"titulo: {titulo}")
        print(f"largo: {len(titulo)} caracteres")
        print(f"\ndescripcion:\n{descripcion[:600]}")
        return 0

    print(f"subiendo {args.video}\n  titulo: {titulo}")
    vid = subir(args.video, titulo, descripcion, args.privacidad)
    try:
        import franjas
        franjas.registrar_subida(vid, titulo)   # cuenta contra el limite diario
    except Exception as e:  # noqa: BLE001
        print(f"  aviso: no se anoto la subida ({type(e).__name__})")
    print(f"\nlisto: https://youtube.com/shorts/{vid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
