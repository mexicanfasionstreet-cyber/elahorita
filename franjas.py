"""Que se publica en cada franja: ventana de noticias, seguimientos y casos especiales.

Cada franja publica sola un video de 1 o 2 notas con lo que paso en su ventana:

  05:00  madrugada  desde las 20:00 del dia anterior (la noche y la madrugada)
  12:00  manana     desde las 05:00 (lo relevante de la manana)
  15:00  tarde      desde las 12:00 (seguimiento y lo nuevo del mediodia)
  20:00  noche      desde las 15:00 (el cierre del dia)

Reglas:
  - Una historia ya publicada hoy solo vuelve si trae notas posteriores al video
    anterior (seguimiento); al guion se le dice que cuente solo lo nuevo.
  - Caso especial: si 2 o mas de las mejores tienen cobertura de alto impacto
    (muchos medios a la vez), no se publica solo: se pregunta por Telegram y, si
    no hay respuesta en ESPERA_MIN minutos, se publica lo mejor no sensible.
  - Tema sensible (suicidio, violencia sexual o menores victimas, violencia
    grafica; ver secciones.py): nunca sale solo. Se pregunta y, si no hay
    respuesta, sale la siguiente no sensible.
  - YouTube permite LIMITE_SUBIDAS al dia: las 4 franjas van primero y lo que
    sobra queda para /nota.

Uso:
    python franjas.py                 # que publicaria la franja que toca ahora
    python franjas.py --franja tarde  # una franja concreta, sin publicar nada
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402

# (hora, nombre, hora de inicio de la ventana; negativa = dia anterior)
FRANJAS = [(5, "madrugada", -4), (12, "manana", 5), (15, "tarde", 12), (20, "noche", 15)]
MARGEN_FRANJA = 2            # horas despues de la hora en que la franja aun puede salir
ESPERA_MIN = 30              # minutos para elegir en un caso especial
LIMITE_SUBIDAS = int(os.environ.get("LIMITE_SUBIDAS", "6") or 6)
# cobertura ponderada (suma del peso de los medios) desde la que una historia es
# "de alto impacto". Un dia normal la mas cubierta ronda 15-27; un suceso grande
# lo cubren casi todas las fuentes a la vez.
# un seguimiento solo sale si la nota previa tiene al menos estas horas: evita que
# el mismo tema salga en dos franjas seguidas con cambios menores
SEGUIMIENTO_HORAS = float(os.environ.get("SEGUIMIENTO_HORAS", "6") or 6)
# acontecimientos donde un mismo personaje/lugar + el mismo hecho es SIEMPRE la misma
# historia (aunque cada medio la titule distinto o en otro idioma) y no admite
# seguimiento: no hay segunda parte de un obituario
EVENTOS_UNICOS = {"muerte", "renuncia", "nombramiento"}
ALTO_IMPACTO = float(os.environ.get("ALTO_IMPACTO", "35") or 35)
SEGUNDA_NOTA = 1.15          # la 1a debe ganar por este factor para ir sola

PUBLICADAS = RAIZ / "datos" / "publicadas.json"
SUBIDAS = RAIZ / "datos" / "subidas.json"
EVENTOS = RAIZ / "datos" / "eventos.json"


# ------------------------------------------------------------------ tiempos
def _dt(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def franja_por_nombre(nombre):
    for hora, n, inicio in FRANJAS:
        if n == nombre:
            return hora, n, inicio
    raise ValueError(f"franja desconocida: {nombre}")


def franja_actual(ahora):
    """La franja cuya ventana de disparo incluye `ahora`, o None."""
    for hora, nombre, inicio in FRANJAS:
        if hora <= ahora.hour < hora + MARGEN_FRANJA:
            return hora, nombre, inicio
    return None


def inicio_ventana(franja, ahora):
    hora, _, inicio = franja
    base = ahora.replace(minute=0, second=0, microsecond=0)
    if inicio < 0:
        return (base - timedelta(days=1)).replace(hour=24 + inicio)
    return base.replace(hour=inicio)


def franjas_restantes(estado, ahora):
    """Franjas de hoy que aun no salen (cuentan contra el limite de subidas)."""
    hechas = estado.get("franjas", {})
    return sum(1 for hora, nombre, _ in FRANJAS
               if not hechas.get(f"{ahora:%Y-%m-%d}-{nombre}")
               and ahora.hour < hora + MARGEN_FRANJA)


# ------------------------------------------------------------------ registros
def _leer(ruta, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _escribir(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def registrar_publicada(historias, origen, video=""):
    """Anota lo publicado para no repetirlo (se guardan 3 dias)."""
    from aggregate import entidades
    ahora = config.ahora()
    lista = [p for p in _leer(PUBLICADAS, [])
             if (_dt(p.get("cuando")) or ahora) > ahora - timedelta(days=3)]
    for h in historias:
        lista.append({
            "cuando": ahora.isoformat(timespec="seconds"), "origen": origen,
            "titulo": h.get("titulo") or h.get("title", ""), "link": h.get("link", ""),
            "entidades": sorted(entidades(h.get("titulo") or h.get("title", ""))),
            "video": video,
        })
    _escribir(PUBLICADAS, lista)


def registrar_subida(video_id, titulo):
    ahora = config.ahora()
    datos = _leer(SUBIDAS, {})
    dia = datos.setdefault(f"{ahora:%Y-%m-%d}", [])
    dia.append({"hora": f"{ahora:%H:%M}", "id": video_id, "titulo": titulo[:100]})
    for viejo in sorted(datos)[:-7]:
        del datos[viejo]
    _escribir(SUBIDAS, datos)


def registrar_evento(tipo, texto):
    """Bitacora del dia para el resumen nocturno (fallos, voz de respaldo, etc.)."""
    try:
        ahora = config.ahora()
        datos = _leer(EVENTOS, {})
        datos.setdefault(f"{ahora:%Y-%m-%d}", []).append(
            {"hora": f"{ahora:%H:%M}", "tipo": tipo, "texto": str(texto)[:200]})
        for viejo in sorted(datos)[:-7]:
            del datos[viejo]
        _escribir(EVENTOS, datos)
    except Exception as e:  # noqa: BLE001  (la bitacora nunca tumba al robot)
        print(f"  aviso: no se anoto el evento ({type(e).__name__})")


def eventos_de(dia):
    return _leer(EVENTOS, {}).get(f"{dia:%Y-%m-%d}", [])


def publicadas_de(dia):
    return [p for p in _leer(PUBLICADAS, []) if str(p.get("cuando", "")).startswith(f"{dia:%Y-%m-%d}")]


def subidas_hoy(ahora=None):
    ahora = ahora or config.ahora()
    return len(_leer(SUBIDAS, {}).get(f"{ahora:%Y-%m-%d}", []))


def cupo_para_nota(estado, ahora=None):
    """Cuantas /nota caben hoy sin quitarle su lugar a las franjas."""
    ahora = ahora or config.ahora()
    return LIMITE_SUBIDAS - subidas_hoy(ahora) - franjas_restantes(estado, ahora)


# ------------------------------------------------------------------ seleccion
def _ya_publicada(fila, publicadas, desde):
    """La publicacion previa de esta misma historia (hoy), o None."""
    from aggregate import event_class
    ents = fila.get("_ents") or set()
    ev = event_class(fila.get("title", ""))
    for p in reversed(publicadas):
        cuando = _dt(p.get("cuando"))
        if not cuando or cuando < desde:
            continue
        if p.get("link") and p["link"] == fila.get("link"):
            return p
        comun = ents & set(p.get("entidades") or [])
        if len(comun) >= 2:
            return p
        # una sola entidad basta si es el mismo hecho puntual (p. ej. "muere X"):
        # BBC en espanol y NPR en ingles solo comparten el nombre del grupo
        if comun and ev in EVENTOS_UNICOS and event_class(p.get("titulo", "")) == ev:
            return p
    return None


def candidatas(items, franja, ahora, publicadas=None):
    """Historias de la ventana, sin repetir lo ya contado salvo que haya novedad."""
    from relevancia import diversificar, puntuar

    publicadas = _leer(PUBLICADAS, []) if publicadas is None else publicadas
    desde = inicio_ventana(franja, ahora)
    inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    filas = []
    for f in puntuar(items):
        ultima = _dt(f.get("updated"))
        if not ultima or ultima < desde:
            continue
        previa = _ya_publicada(f, publicadas, min(desde, inicio_dia))
        if previa:
            from aggregate import event_class
            ev = event_class(f["title"])
            if ev in EVENTOS_UNICOS and ev == event_class(previa.get("titulo", "")):
                continue                 # mismo hecho puntual: no hay seguimiento
            cuando_previa = _dt(previa["cuando"])
            if ultima <= cuando_previa:
                continue                 # ya se conto y no hay nada nuevo
            if ahora - cuando_previa < timedelta(hours=SEGUIMIENTO_HORAS):
                continue                 # contada hace poco: no repetir el tema
            f["seguimiento_de"] = previa["titulo"]
        # IA o palabras: basta con que una la marque
        if not f.get("sensible"):
            import secciones
            f["sensible"] = secciones.sensible(f["title"], f.get("excerpt", ""))
        filas.append(f)
    return diversificar(filas)


def es_especial(filas):
    """2 o mas historias de alto impacto compitiendo: decide Cesar."""
    return sum(f["peso_cobertura"] >= ALTO_IMPACTO for f in filas[:3]) >= 2


def elegir(filas):
    """1 nota si la primera gana con claridad; 2 si la segunda aguanta."""
    if len(filas) >= 2 and filas[0]["score"] < filas[1]["score"] * SEGUNDA_NOTA:
        return filas[:2]
    return filas[:1]


def resumen(f):
    return {"titulo": f["title"], "link": f["link"], "score": f["score"],
            "medios": f["medios"], "peso": f["peso_cobertura"],
            "seguimiento_de": f.get("seguimiento_de", ""), "tipo": "franja",
            "sensible": f.get("sensible", "")}


def no_sensibles(filas):
    """Lo que puede salir sin preguntar: 1 o 2 notas sin tema sensible."""
    return elegir([f for f in filas if not f.get("sensible")])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--franja", default="")
    args = ap.parse_args()
    ahora = config.ahora()
    franja = franja_por_nombre(args.franja) if args.franja else franja_actual(ahora)
    if not franja:
        franja = min(FRANJAS, key=lambda f: (f[0] - ahora.hour) % 24)
    datos = json.loads((RAIZ / "docs" / "data" / "latest.json").read_text(encoding="utf-8"))
    filas = candidatas(datos["items"], franja, ahora)
    print(f"franja {franja[1]} · ventana desde {inicio_ventana(franja, ahora):%d %H:%M} · "
          f"{len(filas)} historias")
    for f in filas[:6]:
        extra = f" · SEGUIMIENTO de: {f['seguimiento_de'][:50]}" if f.get("seguimiento_de") else ""
        print(f"  {f['score']:>5} peso {f['peso_cobertura']:>5} · {f['title'][:70]}{extra}")
    if es_especial(filas):
        print("\nCASO ESPECIAL: se preguntaria por Telegram")
    else:
        print(f"\npublicaria: {' + '.join(f['title'][:50] for f in elegir(filas)) or 'nada'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
