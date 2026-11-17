"""Reescribe la agrupacion de historias de aggregate.py para noticias.

La version de moda agrupa por la PRIMERA palabra del titular y por tres tipos de
acontecimiento del negocio de la moda (fichajes, operacion, resultados). En
noticias eso no sirve: dos medios titulan la misma historia con sujetos y verbos
distintos. Aqui se agrupa por:

  - entidades compartidas (nombres propios, paises, instituciones)
  - mismo tipo de acontecimiento (sismo, detencion, eleccion, renuncia...)
  - ventana de 36 h

Regla: 2+ entidades compartidas basta; con 1 se exige tambien parecido de
titular, para no fusionar dos declaraciones distintas del mismo personaje.

Uso: python herramientas/patch-clustering.py
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
OBJETIVO = RAIZ / "aggregate.py"

ENTIDADES = '''# ------------------------------------------------------------------ entidades
# Nombres propios del titular original (con mayusculas). Se descartan los que
# solo lo son por abrir frase y los meses/dias, que no identifican nada.
NO_ENTIDAD = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "lo", "al", "del",
    "pero", "tras", "segun", "asi", "este", "esta", "estos", "estas", "esto",
    "nuevo", "nueva", "nuevos", "nuevas", "gran", "mayor", "mejor", "peor",
    "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "setiembre", "octubre", "noviembre", "diciembre",
    "the", "a", "an", "and", "but", "for", "with", "from", "after", "before",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "new", "top", "how", "why",
}

ENT_RX = re.compile(r"\\b([A-Z\\u00c0-\\u00dc][a-z\\u00e0-\\u00ff]{2,})\\b")
ACRONIMO_RX = re.compile(r"\\b([A-Z]{2,6})\\b")
ACRONIMO_FUERA = {"EEUU", "EE", "UU", "EUA", "HOY", "VIDEO", "FOTOS", "CNN", "BBC"}


def entidades(title):
    """Conjunto de entidades normalizadas que aparecen en el titular."""
    salida = set()
    for m in ENT_RX.finditer(title or ""):
        w = norm(m.group(1))
        if len(w) > 2 and w not in NO_ENTIDAD and w not in STOP:
            salida.add(w)
    for m in ACRONIMO_RX.finditer(title or ""):
        w = m.group(1)
        if w not in ACRONIMO_FUERA:
            salida.add(w.lower())
    return salida


# ------------------------------------------------------------------ acontecimientos
EVENTOS_NEWS = [
    ("sismo", r"(sismo|terremoto|temblor|epicentro|earthquake|quake)"),
    ("clima", r"(huracan|tormenta|cicion|inundacion|deslave|volcan|alerta|frente frio"
              r"|ola de calor|sequia|helada|hurricane|storm|flood)"),
    ("muerte", r"(muere|murio|fallece|fallecio|muerto|muerta|muertos|deceso|obituario"
               r"|asesinat|died|dies|death|killed)"),
    ("renuncia", r"(renuncia|renuncio|dimite|dimision|destitu|cese|despide|resign|steps down)"),
    ("nombramiento", r"(nombra|nombramiento|designa|appoint|ratifica|nuevo titular)"),
    ("detencion", r"(detenido|detenidos|detencion|captur|arrest|vinculado a proceso"
                  r"|consignad|extradit|aprehend)"),
    ("violencia", r"(balacera|ataque|tiroteo|masacre|enfrentamiento|homicidio|ejecutad"
                  r"|shooting|attack|massacre)"),
    ("eleccion", r"(eleccion|elecciones|electoral|votacion|comicios|candidat|election|vote)"),
    ("economia", r"(inflacion|pib|dolar|tipo de cambio|banxico|arancel|presupuesto|deuda"
                 r"|trimestre|resultados financieros|inflation|tariff|earnings)"),
    ("acuerdo", r"(acuerdo|convenio|tratado|firma de|cumbre|reunion bilateral|delegacion"
                r"|visita oficial|sign|summit|meeting)"),
    ("migracion", r"(migrante|migrantes|caravana|deporta|deportad|frontera|asilo|refugiad"
                   r"|migrant|border|deportation)"),
    ("salud", r"(vacuna|brote|epidemia|pandemia|hospital|desabasto|medicamento|virus|dengue"
              r"|vaccine|outbreak)"),
    ("justicia", r"(sentencia|condena|amparo|consigna|juez|tribunal|court|verdict|indict)"),
    ("declaracion", r"(dice|dijo|afirma|declara|advierte|asegura|rechaza|pide|exige|critica"
                    r"|anuncia|sostiene|says|warns|announces|urges)"),
    ("accidente", r"(accidente|choque|volcadura|derrumbe|explosion|incendio|crash|fire)"),
    ("deportes", r"(gol|partido|final|fichaje|torneo|championship|match|liga)"),
]
EVENTOS_RE = [(n, re.compile(r"(?<![a-z])(" + rx + r")(?![a-z])")) for n, rx in EVENTOS_NEWS]


def event_class(title):
    """Tipo de acontecimiento del titular, o None si no se reconoce."""
    nt = norm(title)
    for nombre, rx in EVENTOS_RE:
        if rx.search(nt):
            return nombre
    return None


def lead_entity(title):
    """Primera entidad del titular (se conserva por compatibilidad)."""
    ent = entidades(title)
    return sorted(ent)[0] if ent else None
'''

MERGE = '''def merge_items(items):
    """Agrupa la misma historia publicada por varios medios.

    Criterio: entidades compartidas + mismo tipo de acontecimiento, dentro de una
    ventana de 36 h. Dos entidades compartidas bastan; con una sola se exige
    ademas parecido de titular, para no unir dos declaraciones distintas del
    mismo personaje. Sin entidades reconocibles se cae a la similitud de titular.
    """
    # orden editorial: primero lo de mas peso y mas reciente -> sobrevive el mejor
    items.sort(key=lambda x: (-x["weight"], -x["published"].timestamp()))

    merged = []
    for it in items:
        ent = it.get("_ent") or set()
        ev = it.get("_ev")
        twin = None
        for cand in merged:
            if cand["source_name"] == it["source_name"]:
                continue  # dos titulares del mismo medio son una serie, no un duplicado
            gap = abs((cand["published"] - it["published"]).total_seconds())
            if gap > 36 * 3600:
                continue
            comun = ent & (cand.get("_ent") or set())
            mismo_ev = bool(ev) and ev == cand.get("_ev")
            if len(comun) >= 2 and (mismo_ev or not ev or not cand.get("_ev")):
                twin = cand
            elif len(comun) == 1 and mismo_ev and jaccard(it["_tok"], cand["_tok"]) >= 0.22:
                twin = cand
            elif not ent and not cand.get("_ent") and is_dup(it, cand):
                twin = cand
            if twin is not None:
                break
        if twin is None:
            merged.append(it)
            continue

        other = it
        if twin["mirror"] and not it["mirror"]:
            # la principal solo tenia el enlace de Google: gana la version directa
            other = _promote(twin, it)
        if not twin["excerpt"] and other["excerpt"] and other["lang"] == twin["lang"]:
            twin["excerpt"] = other["excerpt"]
        if not twin["image"] and other["image"]:
            twin["image"] = other["image"]
        also = twin.setdefault("also", [])
        if twin["source_name"] in also:
            also.remove(twin["source_name"])
        if other["source_name"] not in also and other["source_name"] != twin["source_name"]:
            also.append(other["source_name"])
        # el cluster hereda entidades: una tercera nota puede unirse por la variante
        twin["_ent"] = (twin.get("_ent") or set()) | ent
    return merged
'''


def main():
    texto = OBJETIVO.read_text(encoding="utf-8")
    shutil.copy2(OBJETIVO, OBJETIVO.with_suffix(".py.bak2"))

    # 1) entidades + acontecimientos
    patron = re.compile(r"def event_class\(title\):.*?\n    return None\n", re.S)
    if not patron.search(texto):
        raise SystemExit("no encontre event_class")
    texto = patron.sub(lambda m: ENTIDADES, texto, count=1)

    # 2) quitar lead_entity viejo (ya viene en el bloque nuevo)
    texto = re.sub(r"\n\ndef lead_entity\(title\):\n    for w in norm\(title\)\.split\(\):"
                   r"\n        if len\(w\) > 2 and w not in STOP and not w\.isdigit\(\):"
                   r"\n            return w\n    return None\n", "\n", texto, count=1)

    # 3) guardar entidades y acontecimiento por noticia
    viejo = '"_ev": (lead_entity(title), event_class(title)),'
    nuevo = '"_ent": entidades(title), "_ev": event_class(title),'
    if viejo not in texto:
        raise SystemExit("no encontre la asignacion de _ev en build()")
    texto = texto.replace(viejo, nuevo, 1)
    texto = texto.replace('it.pop("_ev", None)', 'it.pop("_ev", None)\n        it.pop("_ent", None)', 1)

    # 4) merge por entidades
    patron = re.compile(r"def merge_items\(items\):.*?\n    return merged\n", re.S)
    if not patron.search(texto):
        raise SystemExit("no encontre merge_items")
    texto = patron.sub(lambda m: MERGE, texto, count=1)

    OBJETIVO.write_text(texto, encoding="utf-8")
    print(f"ok: {OBJETIVO.name} con agrupacion por entidades")


if __name__ == "__main__":
    main()
