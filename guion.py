"""Escribe el guion de una capsula de 60-75 s con 1 o 2 notas.

Flujo:
  1. puntua el dia con relevancia.py y se queda con la mejor historia
     (o con dos si la segunda aguanta el corte)
  2. DeepSeek redacta gancho, desarrollo y cierre en español de Mexico
  3. se valida que no invente: solo puede usar el material que se le da

Uso:
    python guion.py                    # guion de hoy
    python guion.py --notas 1          # forzar una sola nota
    python guion.py --franja noche
    python guion.py --sin-ia           # plantilla, sin llamar al modelo
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import config
from material import articulo
from relevancia import diversificar, puntuar

RAIZ = Path(__file__).resolve().parent
RANKING = RAIZ / "docs" / "data" / "latest.json"
SALIDA = RAIZ / "docs" / "guiones"

# cuantos segundos de voz caben: 60-75 s a 2.7 palabras/s
PALABRAS_OBJETIVO = (165, 195)

SISTEMA = """Eres el guionista de El Ahorita, un canal de noticias mexicanas en YouTube Shorts.
Escribes para que lo lea una voz sintetica en 60-75 segundos.

Reglas que no puedes romper:
- Español de Mexico, hablado, frases cortas. Nada de "en el marco de" ni "cabe destacar".
- Usa SOLO los datos del material que recibes. No inventes cifras, nombres, fechas ni citas.
  Si un dato no esta, simplemente no lo menciones.
- No editorialices ni opines. No digas "es importante" sin explicar por que.
- Nada de sensacionalismo, mayusculas gritadas ni "no vas a creer".
- NUNCA menciones cuantos medios publican la noticia ni como llego a ti: al espectador
  no le sirve y suena a robot. Esa informacion es solo para que tu sepas que es relevante.
- Cada nota tiene que responder: que paso, con que contexto, y que sigue o por que importa.
  Desarrolla cada nota en 4 o 5 frases: no la dejes en el titular.
- No repitas el titular literal: explicitalo como se lo contarias a alguien en la fila.
- La extension total DEBE quedar entre 180 y 200 palabras, PERO nunca rellenes con datos
  que no esten en el material. Si con lo que hay no llegas, escribe menos: una nota corta
  es mejor que una nota con un dato inventado.
- Prohibido inventar antecedentes, cargos, fechas, cifras o consecuencias. Ejemplo de
  error grave: decir que "Sheinbaum asume el cargo" cuando lleva años gobernando. Si no
  aparece en el material, no lo escribas. Si falta contexto, di que no se conocen detalles.

Devuelves SOLO un JSON valido, sin texto alrededor, con esta forma:
{"gancho": "...", "gancho_pantalla": "...", "notas": [{"kicker": "SECCION", "pantalla": "...", "texto": "..."}], "cierre": "..."}
El gancho es una sola frase que da ganas de escuchar (sin prometer nada falso).
"gancho_pantalla" es el rotulo del gancho: entre 3 y 7 palabras en mayusculas de
concepto (ejemplo: "NVIDIA Y CHINA HOY"), sin punto final.
"pantalla" es el titular que se lee en el video: entre 4 y 9 palabras, en español,
sin punto final, con el hecho concreto (quien + que paso). No repite el gancho.
En "texto" va lo que dice la voz, completo y desarrollado: no es lo mismo que "pantalla".
El cierre es una frase corta de despedida con la marca."""


def _recorte(texto, n=700):
    texto = re.sub(r"\s+", " ", texto or "").strip()
    return texto[:n]


def historias_del_dia(n=2):
    datos = json.loads(RANKING.read_text(encoding="utf-8"))
    items = datos["items"] if isinstance(datos, dict) and "items" in datos else datos
    filas = diversificar(puntuar(items))
    return filas[:n]


def historia_por_link(link):
    """La historia elegida a mano en Telegram, por su enlace."""
    datos = json.loads(RANKING.read_text(encoding="utf-8"))
    items = datos["items"] if isinstance(datos, dict) and "items" in datos else datos
    for f in puntuar(items):
        if f["link"] == link:
            return f
    return None


def elegir_notas(filas, forzadas=None):
    """Una nota si la primera gana por goleada; dos si la segunda aguanta."""
    if forzadas:
        return filas[:forzadas]
    if len(filas) < 2:
        return filas[:1]
    if filas[0]["score"] >= filas[1]["score"] * 1.15:
        return filas[:1]
    return filas[:2]


def asegurar_imagen(f):
    """Si el enlace es de Google News o no hay foto, la consigue.

    El motor resuelve 40 enlaces por corrida; la historia elegida puede haber
    quedado fuera, y entonces la diapositiva salia sin foto.
    """
    import enlaces
    import material as mat

    cache_path = RAIZ / "datos" / "enlaces-cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    link = f.get("link", "")

    if enlaces.es_google(link):
        cache = enlaces.load_cache(cache_path)
        info = enlaces.resolve([link], cache, limit=1).get(link) or {}
        enlaces.save_cache(cache_path, cache)
        if info.get("url"):
            f["link"] = info["url"]
            f["imagen_url"] = info.get("image", "") or f.get("imagen_url", "")

    if not f.get("imagen_url") and f.get("link"):
        art = mat.articulo(f["link"])
        f["imagen_url"] = art.get("imagen", "")
        if not art.get("imagen"):
            print(f"  aviso: sin foto para {f['link'][:60]}")
    return f


def material(notas, con_articulo=True):
    """Material para el modelo: el articulo completo, no solo el titular."""
    partes = []
    for i, f in enumerate(notas, 1):
        cuerpo, desc = "", ""
        if con_articulo and f.get("link"):
            d = articulo(f["link"])
            cuerpo, desc = d["texto"], d["descripcion"]
            print(f"  material nota {i}: {d['palabras']} palabras de {f['link'][:60]}")
        partes.append({
            "n": i,
            "seccion": f["seccion"].upper(),
            "titular": f["title"],
            "entradilla": _recorte(desc or f.get("excerpt") or "", 400),
            "cuerpo_del_articulo": cuerpo[:2200],
            "la_publican": f["medios"],
        })
    return partes


def prompt_usuario(mat):
    lineas = [
        f"Material del dia ({len(mat)} nota(s)). Redacta el guion.",
        f"Extension total: entre {PALABRAS_OBJETIVO[0]} y {PALABRAS_OBJETIVO[1]} palabras.",
        "Todo lo que afirmes tiene que salir de este material.",
        "",
    ]
    for m in mat:
        lineas.append(f"=== NOTA {m['n']} · seccion {m['seccion']} ===")
        lineas.append(f"titular: {m['titular']}")
        if m["entradilla"]:
            lineas.append(f"entradilla: {m['entradilla']}")
        if m["cuerpo_del_articulo"]:
            lineas.append(f"cuerpo: {m['cuerpo_del_articulo']}")
        lineas.append("")
    return "\n".join(lineas)


def llamar_llm(sistema, usuario, timeout=120):
    if not config.LLAVE:
        raise RuntimeError("sin DEEPSEEK_API_KEY")
    cuerpo = json.dumps({
        "model": config.MODELO,
        "messages": [{"role": "system", "content": sistema},
                     {"role": "user", "content": usuario}],
        "temperature": 0.4,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{config.BASE_URL}/chat/completions", data=cuerpo,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {config.LLAVE}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        datos = json.load(r)
    return datos["choices"][0]["message"]["content"]


def parsear(texto):
    texto = (texto or "").strip()
    texto = re.sub(r"^```(?:json)?|```$", "", texto, flags=re.M).strip()
    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        raise ValueError("la respuesta no trae JSON")
    datos = json.loads(m.group(0))
    if not datos.get("gancho") or not datos.get("notas"):
        raise ValueError("al JSON le falta gancho o notas")
    return datos


SISTEMA_VERIFICADOR = """Eres editor de datos de una agencia de noticias. Recibes un MATERIAL y un GUION.
Encuentra toda frase del guion que AFIRME un hecho verificable que no este en el material:
cargos, fechas, cifras, antecedentes, causas, consecuencias o atribuciones.

No toques el estilo ni las palabras de relleno narrativo. Solo los datos.

Devuelves SOLO JSON:
{"problemas": ["frase :: motivo"], "guion_corregido": {"gancho": "...", "notas": [{"kicker": "...", "texto": "..."}], "cierre": "..."}}
En guion_corregido elimina o reformula cada problema usando solo lo que esta en el material.
Si no hay problemas, devuelve la lista vacia y el guion identico."""


def verificar(guion, mat, timeout=120):
    """Segunda pasada: caza afirmaciones que no estan en el material."""
    usuario = ("MATERIAL:\n" + json.dumps(mat, ensure_ascii=False, indent=1)
               + "\n\nGUION:\n" + json.dumps(guion, ensure_ascii=False, indent=1))
    return parsear_verificacion(llamar_llm(SISTEMA_VERIFICADOR, usuario, timeout=timeout))


def parsear_verificacion(texto):
    texto = re.sub(r"^```(?:json)?|```$", "", (texto or "").strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        raise ValueError("la verificacion no trae JSON")
    datos = json.loads(m.group(0))
    return datos.get("problemas") or [], datos.get("guion_corregido")


def _frases(texto):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", texto or "") if s.strip()]


def ajustar_longitud(guion, objetivo=185, tolerancia=8):
    """Recorta frases completas (nunca a media idea) hasta caber en el objetivo.

    El modelo tiende a escribir de mas cuando el material es rico; para un short de
    60-75 s el techo manda. Se quitan primero las ultimas frases de la nota mas larga.
    """
    if palabras(guion) <= objetivo + tolerancia:
        return guion, False
    g = json.loads(json.dumps(guion, ensure_ascii=False))
    tocado = False
    while palabras(g) > objetivo + tolerancia:
        orden = sorted(range(len(g["notas"])),
                       key=lambda i: -len(g["notas"][i]["texto"].split()))
        quitada = False
        for i in orden:
            fr = _frases(g["notas"][i]["texto"])
            if len(fr) > 3:
                g["notas"][i]["texto"] = " ".join(fr[:-1])
                quitada = tocado = True
                break
        if not quitada:
            break
    return g, tocado


def plantilla(notas):
    """Guion de respaldo, sin IA: correcto pero plano."""
    out = {"gancho": notas[0]["title"], "notas": [], "cierre": "Esto es El Ahorita."}
    for f in notas:
        texto = _recorte(f.get("excerpt") or "", 320) or f["title"]
        out["notas"].append({"kicker": f["seccion"].upper(), "texto": texto})
    return out


def palabras(guion):
    trozos = [guion.get("gancho", ""), guion.get("cierre", "")]
    trozos += [n.get("texto", "") for n in guion.get("notas", [])]
    return sum(len(t.split()) for t in trozos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--notas", type=int, default=0, help="1 o 2; 0 = automatico")
    ap.add_argument("--franja", default="")
    ap.add_argument("--link", default="", help="publicar una historia concreta")
    ap.add_argument("--sin-ia", action="store_true")
    ap.add_argument("--sin-articulo", action="store_true",
                    help="no descargar el articulo completo (mas rapido)")
    ap.add_argument("--sin-verificar", action="store_true",
                    help="no hacer la segunda pasada que caza datos inventados")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if args.link:
        elegida = historia_por_link(args.link)
        if not elegida:
            raise SystemExit("no encontre esa historia en la edicion de hoy")
        notas = [elegida]
    else:
        filas = historias_del_dia(3)
        if not filas:
            raise SystemExit("no hay historias en el dia")
        notas = elegir_notas(filas, args.notas or None)
    notas = [asegurar_imagen(f) for f in notas]
    mat = material(notas, con_articulo=not args.sin_articulo)

    guion, origen, problemas = None, "ia", []
    if args.sin_ia:
        guion, origen = plantilla(notas), "plantilla"
    else:
        try:
            guion = parsear(llamar_llm(SISTEMA, prompt_usuario(mat)))
        except (RuntimeError, ValueError, urllib.error.URLError, json.JSONDecodeError) as e:
            print(f"aviso: no se pudo usar la IA ({e}); se usa la plantilla")
            guion, origen = plantilla(notas), "plantilla"

    if origen == "ia" and not args.sin_verificar:
        try:
            antes = json.loads(json.dumps(guion, ensure_ascii=False))
            problemas, corregido = verificar(guion, mat)
            if corregido:
                # el verificador reescribe el texto: se conserva el titular de
                # pantalla original, que no es un dato sino un rotulo
                for i, n in enumerate(corregido.get("notas", [])):
                    if not n.get("pantalla") and i < len(antes.get("notas", [])):
                        n["pantalla"] = antes["notas"][i].get("pantalla", "")
                if not corregido.get("gancho_pantalla"):
                    corregido["gancho_pantalla"] = antes.get("gancho_pantalla", "")
                guion = corregido
        except (RuntimeError, ValueError, urllib.error.URLError,
                json.JSONDecodeError) as e:
            print(f"aviso: no se pudo verificar ({e})")

    # rotulo del gancho: si el modelo no lo mando, se usa el de la primera nota
    if not (guion.get("gancho_pantalla") or "").strip():
        notas_g = guion.get("notas") or []
        guion["gancho_pantalla"] = (notas_g[0].get("pantalla", "") if notas_g else "")
    guion, recortado = ajustar_longitud(guion)
    if recortado:
        print("aviso: guion recortado para caber en 60-75 s\n")
    n_pal = palabras(guion)
    est = n_pal / config.PALABRAS_POR_SEGUNDO

    print(f"--- GUION ({origen}) · {len(notas)} nota(s) · {n_pal} palabras "
          f"~ {est:.0f} s ---\n")
    print(f"GANCHO: {guion['gancho']}\n")
    for n in guion["notas"]:
        print(f"[{n.get('kicker', '')}] {n['texto']}\n")
    print(f"CIERRE: {guion['cierre']}\n")
    for f in notas:
        print(f"  fuente: {f['title'][:70]} ({f['medios']} medios)")

    salida = Path(args.json) if args.json else (
        SALIDA / f"{datetime.now():%Y-%m-%d}-{args.franja or 'dia'}.json")
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps({
        "origen": origen, "palabras": n_pal, "segundos_estimados": round(est, 1),
        "historias": [{"titulo": f["title"], "link": f["link"], "seccion": f["seccion"],
                       "medios": f["medios"], "score": f["score"],
                       "imagen": bool(f.get("imagen_url")),
                       "imagen_url": f.get("imagen_url", "")} for f in notas],
        "guion": guion,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nguion -> {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
