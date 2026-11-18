"""Nota pedida a mano: /nota <tema o enlace> desde Telegram.

Hace lo mismo que el flujo automatico pero sin ranking: investiga el tema, saca el
material, escribe el guion, monta voz, subtitulos y video, y lo manda al chat.

Como elige la historia (antes tomaba el grupo mas grande, aunque no tuviera que
ver con lo que pediste):
  1. busca el tema en Google News (ultimos 3 dias);
  2. puntua cada resultado por cuantas palabras clave de tu pedido contiene;
  3. agrupa los resultados que cuentan la misma historia;
  4. gana el grupo que mejor coincide (la cobertura solo desempata).
  Si ninguno coincide bien, no inventa: te manda las 3 opciones mas cercanas
  con botones para que elijas.

Material: lee hasta 3 articulos de la misma historia, no solo el primero.
Duracion: si el guion queda corto (menos de MIN_PALABRAS), arma el video y te lo
manda, pero NO lo sube a YouTube: te deja un boton "Subir asi".

Uso:
    python nota.py "Sheinbaum anuncia el salario minimo 2027"
    python nota.py https://elpais.com/... --solo-guion
    python nota.py "tema" --prueba        # video al chat, sin YouTube ni botones
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402
import guion  # noqa: E402
import material  # noqa: E402
import telegram as telegram_mod  # noqa: E402

GOOGLE = ("https://news.google.com/rss/search?q={q}+when:3d"
          "&hl=es-419&gl=MX&ceid=MX:es-419")
SECCIONES = {"politica": "POLITICA", "seguridad": "SEGURIDAD", "economia": "ECONOMIA",
             "mundo": "MUNDO", "clima": "CLIMA", "salud": "SALUD", "ciencia": "CIENCIA",
             "deportes": "DEPORTES", "cultura": "CULTURA", "migracion": "MIGRACION",
             "justicia": "JUSTICIA", "industria": "AHORITA"}

MIN_PALABRAS = 120            # ~45 s de voz: menos que esto no se sube solo
COINCIDENCIA_MIN = 0.5        # fraccion de palabras clave que debe tener la historia
MAX_ARTICULOS = 3             # articulos de la misma historia que se leen
MAX_INTENTOS = 6              # enlaces que se prueban para conseguirlos
CUERPO_POR_ARTICULO = 1400
CUERPO_TOTAL = 4000

# palabras que no dicen de que trata el pedido
VACIAS = set("""
el la los las un una unos unas lo al del de en y o u que por para con sin sobre
entre como mas pero sus su se es son fue han hay ser esta estan este esto ese esa
eso ya muy tambien hoy ayer dice dicen dijo menciona mencionan segun usando usan
nota noticia noticias tema video quiero haz hazme sobre acerca cual cuales donde
cuando quien quienes porque pues asi the and for with from
""".split())

# marcas de que la historia ocurre en Mexico (para la etiqueta MEXICO / MUNDO)
MARCAS_MX = re.compile(
    r"\b(mexico|mexican[oa]s?|cdmx|sheinbaum|morena|pemex|cfe|banxico|imss|sat|sep|"
    r"guardia nacional|fgr|scjn|tijuana|baja california|jalisco|guadalajara|monterrey|"
    r"nuevo leon|sinaloa|sonora|chihuahua|coahuila|tamaulipas|veracruz|oaxaca|chiapas|"
    r"guerrero|michoacan|puebla|queretaro|yucatan|quintana roo|cancun|edomex|estado de mexico|"
    r"zacatecas|durango|hidalgo|morelos|tabasco|campeche|colima|nayarit|aguascalientes|"
    r"guanajuato|san luis potosi|tlaxcala|baja california sur|los cabos)\b")


# ------------------------------------------------------------------ busqueda
def _norm(texto):
    from aggregate import norm
    return norm(texto or "")


def _raiz(palabra):
    """Raiz burda para empatar plurales y derivados: hackeos ~ hackeo ~ hackers."""
    return palabra[:5] if len(palabra) > 5 else palabra


def terminos(tema):
    """Palabras clave del pedido, ya normalizadas."""
    salida = []
    for p in _norm(tema).split():
        if (len(p) >= 3 or p == "ia") and p not in VACIAS and p not in salida:
            salida.append(p)
    return salida


def coincidencia(claves, texto):
    """Fraccion de palabras clave del pedido que aparecen en el texto."""
    if not claves:
        return 0.0
    raices = {_raiz(p) for p in _norm(texto).split()}
    return sum(_raiz(c) in raices for c in claves) / len(claves)


def _misma_historia(a, b):
    """Dos titulares de la misma historia: comparten personajes o casi las mismas palabras."""
    from aggregate import entidades, jaccard, tokens
    comunes = len(entidades(a["title"]) & entidades(b["title"]))
    raices = jaccard({_raiz(t) for t in tokens(a["title"])},
                     {_raiz(t) for t in tokens(b["title"])})
    return comunes >= 2 or raices >= 0.35 or (comunes == 1 and raices >= 0.25)


def agrupar(items, claves):
    """Agrupa por historia y ordena: primero lo que coincide con el pedido."""
    for it in items:
        it["_coincide"] = coincidencia(claves, it["title"] + " " + (it.get("body") or ""))
    grupos = []
    for it in sorted(items, key=lambda x: -x["_coincide"]):
        for g in grupos:
            if _misma_historia(g[0], it):
                g.append(it)
                break
        else:
            grupos.append([it])

    def puntaje(g):
        # la coincidencia manda; la cobertura (cuantos medios) solo desempata
        return max(x["_coincide"] for x in g) * (1 + 0.1 * math.log2(len(g)))
    grupos.sort(key=puntaje, reverse=True)
    return grupos


def buscar_tema(tema):
    """Busca en Google News y devuelve los grupos de historias, el mejor primero."""
    from aggregate import fetch, parse_feed, strip_pub_suffix

    url = GOOGLE.format(q=urllib.parse.quote(tema))
    try:
        items = parse_feed(fetch(url), {"name": "Busqueda"})
    except Exception as e:  # noqa: BLE001
        print(f"  la busqueda fallo ({type(e).__name__}: {e})")
        return []
    for it in items:
        it["title"] = strip_pub_suffix(it["title"])
    if not items:
        return []
    grupos = agrupar(items, terminos(tema))
    print(f"  {len(items)} resultados · {len(grupos)} historias · "
          f"claves: {', '.join(terminos(tema))}")
    for g in grupos[:3]:
        print(f"   {max(x['_coincide'] for x in g):.0%} · {len(g)} medio(s) · {g[0]['title'][:80]}")
    return grupos


# ------------------------------------------------------------------ material
def resolver_enlace(link, cache_path):
    """Google News -> articulo real (y su foto)."""
    import enlaces
    if not enlaces.es_google(link):
        return link, ""
    cache = enlaces.load_cache(cache_path)
    info = enlaces.resolve([link], cache, limit=5).get(link) or {}
    enlaces.save_cache(cache_path, cache)
    return info.get("url") or link, info.get("image") or ""


def _medio(url):
    host = urllib.parse.urlparse(url or "").netloc.lower().replace("www.", "")
    return host.split(".")[0] if host else "medio"


def reunir_material(enlaces_grupo, cache):
    """Lee hasta MAX_ARTICULOS articulos legibles de la misma historia."""
    leidos, foto = [], ""
    for i, cand in enumerate(enlaces_grupo[:MAX_INTENTOS], 1):
        real, foto_c = resolver_enlace(cand, cache)
        art = material.articulo(real)
        print(f"  intento {i}: {art['palabras']} palabras · {real[:70]}")
        foto = foto or foto_c or art.get("imagen", "")
        if art["texto"]:
            art["url_real"] = real
            leidos.append(art)
            if len(leidos) >= MAX_ARTICULOS:
                break
    return leidos, foto


def cuerpo_combinado(leidos):
    partes = [f"[Fuente {i}: {_medio(a['url_real'])}] {a['texto'][:CUERPO_POR_ARTICULO]}"
              for i, a in enumerate(leidos, 1)]
    return "\n\n".join(partes)[:CUERPO_TOTAL]


def horas_desde(fecha):
    try:
        dt = datetime.fromisoformat(str(fecha).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 99.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round(max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600), 1)


def es_de_mexico(texto):
    return bool(MARCAS_MX.search(_norm(texto)))


# ------------------------------------------------------------------ telegram
def _avisar(texto, botones=None):
    try:
        telegram_mod.mandar(texto, botones)
    except BaseException as e:  # noqa: BLE001  (_llamar usa SystemExit)
        print(f"  aviso no enviado ({type(e).__name__})")


def ofrecer_opciones(tema, grupos, prueba=False):
    """Ninguna historia coincide bien: se ofrecen las 3 mas cercanas, sin gastar nada."""
    opciones = []
    for g in grupos[:3]:
        mejor = max(g, key=lambda x: x["_coincide"])
        opciones.append({"titulo": mejor["title"], "link": mejor["link"], "tipo": "nota",
                         "coincide": round(mejor["_coincide"], 2), "medios": len(g)})
    lineas = [f"<b>/nota {html.escape(tema[:80])}</b>",
              "No encontre una historia que coincida bien. Lo mas cercano:\n"]
    for i, o in enumerate(opciones, 1):
        lineas.append(f"<b>{i}.</b> {html.escape(o['titulo'][:140])}\n"
                      f"   coincide {o['coincide']:.0%} · {o['medios']} medio(s)")
    if prueba or not opciones:
        lineas.append("\n(modo prueba: sin botones)" if prueba else "")
        _avisar("\n".join(lineas))
        return
    lote = telegram_mod.guardar_lote(opciones)
    botones = [[(f"Hacer la {i}", f"pub:{lote}:n{i}")] for i in range(1, len(opciones) + 1)]
    botones.append([("Ninguna", f"pub:{lote}:nada")])
    lineas.append("\nO manda /nota con otras palabras o con el enlace.")
    _avisar("\n".join(lineas), botones)


# ------------------------------------------------------------------ guion
def escribir_guion(mat, sin_verificar=False, titulo="", texto=""):
    try:
        g = guion.parsear(guion.llamar_llm(guion.SISTEMA, guion.prompt_usuario(mat)))
    except Exception as e:  # noqa: BLE001
        print(f"  aviso: sin IA ({type(e).__name__}: {e}); se usa la plantilla")
        g = guion.plantilla([{"title": titulo, "excerpt": texto[:400],
                              "seccion": mat[0]["seccion"].lower()}])
    if not sin_verificar:
        try:
            antes = json.loads(json.dumps(g, ensure_ascii=False))
            _, corregido = guion.verificar(g, mat)
            if corregido:
                for i, n in enumerate(corregido.get("notas", [])):
                    if not n.get("pantalla") and i < len(antes.get("notas", [])):
                        n["pantalla"] = antes["notas"][i].get("pantalla", "")
                if not corregido.get("gancho_pantalla"):
                    corregido["gancho_pantalla"] = antes.get("gancho_pantalla", "")
                g = corregido
        except Exception as e:  # noqa: BLE001
            print(f"  aviso: sin verificacion ({type(e).__name__})")
    if not (g.get("gancho_pantalla") or "").strip():
        notas = g.get("notas") or []
        g["gancho_pantalla"] = notas[0].get("pantalla", "") if notas else ""
    g, _ = guion.ajustar_longitud(g)
    return g


def construir(args):
    """Investiga y escribe el guion. Devuelve la ruta del guion, o None si no hay nota."""
    cache = RAIZ / "datos" / "enlaces-cache.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    tema = args.tema.strip()
    es_enlace = tema.lower().startswith("http")

    if es_enlace:
        enlaces_grupo, titulo, medios, publicado = [tema], "", 1, None
    else:
        grupos = buscar_tema(tema)
        if not grupos:
            _avisar(f"<b>/nota</b>: sin resultados de los ultimos 3 dias para "
                    f"<i>{html.escape(tema[:100])}</i>. Prueba con otras palabras o manda el enlace.")
            return None
        grupo = grupos[0]
        mejor = max(grupo, key=lambda x: x["_coincide"])
        if mejor["_coincide"] < COINCIDENCIA_MIN:
            print(f"  coincidencia baja ({mejor['_coincide']:.0%}): se ofrecen opciones")
            ofrecer_opciones(tema, grupos, prueba=args.prueba)
            return None
        # primero el que mejor coincide, luego el resto de la misma historia
        orden = [mejor] + [x for x in grupo if x is not mejor]
        enlaces_grupo = [x["link"] for x in orden]
        titulo, medios, publicado = mejor["title"], len(grupo), mejor.get("published")
        print(f"  historia: {titulo[:80]} ({mejor['_coincide']:.0%}, {medios} medios)")

    leidos, foto = reunir_material(enlaces_grupo, cache)
    if leidos:
        print(f"  material: {len(leidos)} articulo(s), "
              f"{sum(a['palabras'] for a in leidos)} palabras")
    else:
        print("  aviso: ningun articulo se dejo leer; el guion saldra con lo justo")
    principal = leidos[0] if leidos else {"descripcion": "", "texto": "", "titulo": ""}
    link = principal.get("url_real") or enlaces_grupo[0]
    if not titulo:
        titulo = principal.get("titulo") or principal["descripcion"][:110] or tema
    cuerpo = cuerpo_combinado(leidos)

    from aggregate import classify
    slug = (classify(titulo, cuerpo) or ["industria"])[0]
    region = "mx" if es_de_mexico(titulo + " " + cuerpo[:1500]) else "mundo"
    mat = [{
        "n": 1, "seccion": SECCIONES.get(slug, "AHORITA"), "titular": titulo,
        "entradilla": principal["descripcion"][:400], "cuerpo_del_articulo": cuerpo,
        "la_publican": medios,
    }]
    guion_txt = escribir_guion(mat, args.sin_verificar, titulo, cuerpo)

    n_pal = guion.palabras(guion_txt)
    destino_dir = RAIZ / ("build" if args.prueba else "docs/guiones")
    nombre = f"{config.ahora():%Y-%m-%d-%H%M}-nota"
    destino = destino_dir / f"{nombre}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "origen": "nota_manual", "tema": tema, "palabras": n_pal,
        "segundos_estimados": round(n_pal / config.PALABRAS_POR_SEGUNDO, 1),
        "articulos_leidos": [a["url_real"] for a in leidos],
        "historias": [{"titulo": titulo, "link": link, "seccion": slug,
                       "medios": medios, "score": 0, "imagen": bool(foto),
                       "imagen_url": foto, "region": region,
                       "horas": horas_desde(publicado) if publicado else 99.0}],
        "guion": guion_txt,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n--- GUION · {n_pal} palabras ~ {n_pal / config.PALABRAS_POR_SEGUNDO:.0f} s · "
          f"{SECCIONES.get(slug)} · {region} ---")
    print(f"GANCHO: {guion_txt['gancho']}\n")
    for n in guion_txt["notas"]:
        print(f"[{n.get('kicker', '')}] {n['texto']}\n")
    print(f"CIERRE: {guion_txt['cierre']}")
    print(f"\nguion -> {destino}")
    return destino


# ------------------------------------------------------------------ video
def subir_a_youtube(video, guion_path):
    """Sube el video de una nota manual. Devuelve el enlace o cadena vacia."""
    import os

    if not (config.YT_CLIENT_ID and config.YT_REFRESH):
        return ""
    privacidad = os.environ.get("YT_PRIVACIDAD", "private") or "private"
    print(f"  subiendo a YouTube ({privacidad})")
    hecho = subprocess.run(
        [sys.executable, str(RAIZ / "publicar.py"), "--video", str(video),
         "--guion", str(guion_path), "--privacidad", privacidad],
        cwd=RAIZ, capture_output=True, text=True, errors="replace")
    salida = hecho.stdout or ""
    print(salida[-600:])
    if hecho.returncode != 0:
        print((hecho.stderr or "")[-400:])
        return ""
    for linea in salida.splitlines():
        if "youtube.com/shorts/" in linea:
            return linea.split()[-1]
    return ""


def montar(destino):
    """Voz y video a partir de un guion ya escrito. Devuelve la ruta del mp4."""
    subprocess.run([sys.executable, str(RAIZ / "voz.py"), "--guion", str(destino)], check=True)
    subprocess.run([sys.executable, str(RAIZ / "capsula.py"), "--guion", str(destino)], check=True)
    video = RAIZ / "docs" / "videos" / f"{destino.stem}.mp4"
    print(f"\nvideo -> {video}")
    return video


def publicar_y_avisar(destino, video, tema, forzar=False, prueba=False):
    """Sube a YouTube y manda el video al chat. Si salio corto, no sube: pregunta."""
    datos = json.loads(destino.read_text(encoding="utf-8"))
    n_pal = datos.get("palabras", 0)
    seg = round(n_pal / config.PALABRAS_POR_SEGUNDO)
    pie = f"El Ahorita · {tema[:120]}"
    if prueba:
        telegram_mod.mandar_video(video, pie + f"\n(prueba: {n_pal} palabras, ~{seg} s; no se sube)")
        return
    if n_pal < MIN_PALABRAS and not forzar:
        telegram_mod.mandar_video(
            video, pie + f"\nSalio corto: {n_pal} palabras (~{seg} s). No lo subi a YouTube.")
        _avisar(f"Esa nota quedo de ~{seg} s: los medios no dieron mas material. "
                "¿La subo asi?", [[("Subir asi", f"subir:{destino.stem}")]])
        print(f"  corta ({n_pal} palabras): no se sube; se pregunta en el chat")
        return
    enlace = subir_a_youtube(video, destino)
    if enlace:
        pie += f"\n{enlace}"
    telegram_mod.mandar_video(video, pie)
    print("enviado al chat" + (f" · {enlace}" if enlace else " · SIN subir"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tema", nargs="?", default="")
    ap.add_argument("--solo-guion", action="store_true")
    ap.add_argument("--sin-enviar", action="store_true")
    ap.add_argument("--sin-verificar", action="store_true")
    ap.add_argument("--prueba", action="store_true",
                    help="video al chat sin subirlo a YouTube y sin botones")
    ap.add_argument("--subir", default="",
                    help="rearma y sube una nota corta ya escrita (nombre del guion)")
    args = ap.parse_args()

    if args.subir:
        destino = RAIZ / "docs" / "guiones" / f"{args.subir}.json"
        if not re.fullmatch(r"[\w-]+", args.subir) or not destino.exists():
            raise SystemExit(f"no existe el guion {args.subir}")
        video = montar(destino)
        tema = json.loads(destino.read_text(encoding="utf-8")).get("tema", args.subir)
        publicar_y_avisar(destino, video, tema, forzar=True)
        return 0

    if not args.tema:
        ap.error("falta el tema o el enlace")
    destino = construir(args)
    if destino is None or args.solo_guion:
        return 0
    video = montar(destino)
    if not args.sin_enviar and video.exists():
        publicar_y_avisar(destino, video, args.tema, prueba=args.prueba)
    return 0


if __name__ == "__main__":
    sys.exit(main())
