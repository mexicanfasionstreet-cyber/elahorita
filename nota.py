"""Nota pedida a mano: /nota <tema o enlace> desde Telegram.

Hace lo mismo que el flujo automatico pero sin ranking: investiga el tema, saca el
articulo, escribe el guion, monta voz, subtitulos y video, y lo manda al chat.

Uso:
    python nota.py "Sheinbaum anuncia el salario minimo 2027"
    python nota.py https://elpais.com/... --solo-guion
    python nota.py "tema" --sin-enviar
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import guion  # noqa: E402
import material  # noqa: E402
import telegram as telegram_mod  # noqa: E402

GOOGLE = ("https://news.google.com/rss/search?q={q}+when:3d"
          "&hl=es-419&gl=MX&ceid=MX:es-419")
SECCIONES = {"politica": "POLITICA", "seguridad": "SEGURIDAD", "economia": "ECONOMIA",
             "mundo": "MUNDO", "clima": "CLIMA", "salud": "SALUD", "ciencia": "CIENCIA",
             "deportes": "DEPORTES", "cultura": "CULTURA", "migracion": "MIGRACION",
             "justicia": "JUSTICIA", "industria": "ULTIMA HORA"}


def _titulo_de(html_titulo, alternativa=""):
    t = re.sub(r"\s+", " ", (html_titulo or "")).strip()
    return t or alternativa


def buscar_tema(tema):
    """Busca el tema en Google News y devuelve el articulo con mas cobertura."""
    from aggregate import entidades, fetch, parse_feed

    url = GOOGLE.format(q=urllib.parse.quote(tema))
    src = {"name": "Busqueda", "short": "Busca", "weight": 4.0, "lang": "es",
           "region": "mx", "kind": "news", "mirror": True, "aggregator": True}
    items = parse_feed(fetch(url), src)
    if not items:
        raise SystemExit(f"sin resultados para: {tema}")

    grupos = {}
    for it in items:
        clave = tuple(sorted(entidades(it["title"]))[:3]) or (it["title"][:30],)
        grupos.setdefault(clave, []).append(it)
    mejor = max(grupos.values(), key=len)
    print(f"  {len(items)} resultados · grupo mayor con {len(mejor)} notas")
    return mejor


def resolver_enlace(link, cache_path):
    """Google News -> articulo real (y su foto)."""
    import enlaces
    if not enlaces.es_google(link):
        return link, ""
    cache = enlaces.load_cache(cache_path)
    info = enlaces.resolve([link], cache, limit=5).get(link) or {}
    enlaces.save_cache(cache_path, cache)
    return info.get("url") or link, info.get("image") or ""


def construir(args):
    cache = RAIZ / "datos" / "enlaces-cache.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    tema = args.tema.strip()

    if tema.lower().startswith("http"):
        titulo, link, medios = "", tema, 1
    else:
        grupo = buscar_tema(tema)
        primero = grupo[0]
        titulo = primero["title"]
        link = primero["link"]
        medios = len(grupo)
        print(f"  historia: {titulo[:80]}")

    # algunos medios bloquean la lectura: se prueban los siguientes del grupo
    candidatos = [link] + [it["link"] for it in (grupo[1:5] if not tema.lower().startswith("http") else [])]
    art = {"texto": "", "descripcion": "", "palabras": 0}
    foto = ""
    for i, cand in enumerate(candidatos, 1):
        real, foto_c = resolver_enlace(cand, cache)
        if not tema.lower().startswith("http") and i <= len(grupo):
            titulo = (grupo[i - 1]["title"] if i - 1 < len(grupo) else titulo)
        prueba = material.articulo(real)
        print(f"  intento {i}: {prueba['palabras']} palabras · {real[:70]}")
        if prueba["texto"]:
            link, foto, art = real, foto_c or foto, prueba
            break
    if not art["texto"]:
        print("  aviso: ningun articulo se dejo leer; el guion saldra con lo justo")
    else:
        print(f"  material: {art['palabras']} palabras")

    if not foto:
        foto = art.get("imagen", "")       # enlaces directos: og:image del articulo
    if not titulo:
        titulo = art.get("titulo") or art["descripcion"][:110] or tema

    from aggregate import classify
    slug = (classify(titulo, art["texto"]) or ["industria"])[0]
    mat = [{
        "n": 1, "seccion": SECCIONES.get(slug, "ULTIMA HORA"), "titular": titulo,
        "entradilla": art["descripcion"][:400], "cuerpo_del_articulo": art["texto"][:2200],
        "la_publican": medios,
    }]

    try:
        guion_txt = guion.parsear(guion.llamar_llm(guion.SISTEMA, guion.prompt_usuario(mat)))
    except Exception as e:  # noqa: BLE001
        print(f"  aviso: sin IA ({type(e).__name__}: {e}); se usa la plantilla")
        guion_txt = guion.plantilla([{"title": titulo, "excerpt": art["texto"][:400],
                                      "seccion": slug}])
    if not args.sin_verificar:
        try:
            antes = json.loads(json.dumps(guion_txt, ensure_ascii=False))
            _, corregido = guion.verificar(guion_txt, mat)
            if corregido:
                for i, n in enumerate(corregido.get("notas", [])):
                    if not n.get("pantalla") and i < len(antes.get("notas", [])):
                        n["pantalla"] = antes["notas"][i].get("pantalla", "")
                if not corregido.get("gancho_pantalla"):
                    corregido["gancho_pantalla"] = antes.get("gancho_pantalla", "")
                guion_txt = corregido
        except Exception as e:  # noqa: BLE001
            print(f"  aviso: sin verificacion ({type(e).__name__})")

    if not (guion_txt.get("gancho_pantalla") or "").strip():
        notas = guion_txt.get("notas") or []
        guion_txt["gancho_pantalla"] = notas[0].get("pantalla", "") if notas else ""
    guion_txt, _ = guion.ajustar_longitud(guion_txt)

    n_pal = guion.palabras(guion_txt)
    nombre = f"{datetime.now():%Y-%m-%d}-nota"
    destino = RAIZ / "docs" / "guiones" / f"{nombre}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "origen": "nota_manual", "tema": tema, "palabras": n_pal,
        "segundos_estimados": round(n_pal / 2.7, 1),
        "historias": [{"titulo": titulo, "link": link, "seccion": slug,
                       "medios": medios, "score": 0, "imagen": bool(foto),
                       "imagen_url": foto, "region": "mx", "horas": 1.0}],
        "guion": guion_txt,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n--- GUION · {n_pal} palabras ~ {n_pal / 2.7:.0f} s ---")
    print(f"GANCHO: {guion_txt['gancho']}\n")
    for n in guion_txt["notas"]:
        print(f"[{n.get('kicker', '')}] {n['texto']}\n")
    print(f"CIERRE: {guion_txt['cierre']}")
    print(f"\nguion -> {destino}")
    return destino


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tema")
    ap.add_argument("--solo-guion", action="store_true")
    ap.add_argument("--sin-enviar", action="store_true")
    ap.add_argument("--sin-verificar", action="store_true")
    args = ap.parse_args()

    destino = construir(args)
    nombre = destino.stem
    if args.solo_guion:
        return 0

    import subprocess
    subprocess.run([sys.executable, str(RAIZ / "voz.py"), "--guion", str(destino)], check=True)
    subprocess.run([sys.executable, str(RAIZ / "capsula.py"), "--guion", str(destino)], check=True)
    video = RAIZ / "docs" / "videos" / f"{nombre}.mp4"
    print(f"\nvideo -> {video}")

    if not args.sin_enviar and video.exists():
        telegram_mod.mandar_video(video, f"El Ahorita · {args.tema[:120]}")
        print("enviado al chat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
