#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""moda-radar — radar diario de noticias de la industria de la moda.

Qué hace:
  1. Descarga los RSS/Atom de las fuentes de sources.json (en paralelo).
  2. Limpia, normaliza y descarta noticias fuera de la ventana de días.
  3. Elimina duplicados entre medios (misma noticia en BoF y WWD = una sola).
  4. Clasifica cada noticia en secciones (negocio, retail, pasarela, sostenibilidad...).
  5. Genera el panel HTML (docs/index.html), los datos JSON (docs/data/) y el digest Markdown (digests/).

Solo usa la biblioteca estándar de Python 3.9+. Sin claves API. Sin coste.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import gzip
import hashlib
import html
import json
import os
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import enlaces
import ui

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
MAX_PER_FEED = 40
TIMEOUT = 30

CATS = [
    {
        "slug": "politica",
        "label": "Politica",
        "kw": [
            "presidente", "presidenta", "sheinbaum", "congreso", "senado", "diputados",
            "senadores", "legislativo", "gobernador", "gobernadora", "gabinete", "secretario",
            "secretaria", "decreto", "reforma", "iniciativa", "ley", "scjn", "suprema corte",
            "tribunal electoral", "ine", "eleccion", "elecciones", "candidato", "candidata",
            "morena", "pan", "pri", "mc", "oposicion", "opositor", "partido", "campana",
            "mitin", "protesta", "marcha", "paro", "renuncia", "destitucion", "juicio politico",
            "presupuesto", "hacienda", "shcp", "banxico", "fiscalia general", "fgr",
            "election", "president", "congress", "senate", "parliament", "minister", "vote",
        ],
    },
    {
        "slug": "seguridad",
        "label": "Seguridad",
        "kw": [
            "homicidio", "asesinato", "asesinado", "balacera", "ataque armado", "ejecutado",
            "cadaver", "cuerpo", "masacre", "narco", "narcotrafico", "cartel", "cjng", "sinaloa",
            "fentanilo", "droga", "droga", "extorsion", "secuestro", "desaparecido",
            "desaparecidos", "desaparicion", "levanton", "detenido", "detenidos", "captura",
            "capturado", "vinculado a proceso", "prision", "penal", "reclusorio", "motin",
            "guardia nacional", "policia", "policias", "militar", "ejercito", "marina",
            "operativo", "enfrentamiento", "tiroteo", "explosion", "atentado", "robo",
            "violencia", "inseguridad", "fiscalia", "ministerio publico", "sentencia",
            "murder", "killed", "shooting", "cartel", "kidnapping", "gang", "assault",
        ],
    },
    {
        "slug": "clima",
        "label": "Clima y alertas",
        "kw": [
            "sismo", "terremoto", "temblor", "replica", "epicentro", "magnitud", "ssn",
            "sismologico", "volcan", "popocatepetl", "cenapred", "alerta amarilla", "alerta naranja", "alerta roja",
            "alerta sismica", "bajas temperaturas", "evacuacion",
            "huracan", "tormenta", "cicion", "ciclón", "lluvia", "lluvias", "inundacion",
            "inundaciones", "deslave", "deslizamiento", "granizo", "sequia", "ola de calor",
            "frente frio", "helada", "proteccion civil", "damnificados", "emergencia climatica",
            "contingencia ambiental",
            "earthquake", "hurricane", "flood", "storm", "wildfire", "volcano", "tsunami",
        ],
    },
    {
        "slug": "economia",
        "label": "Economia",
        "kw": [
            "inflacion", "pib", "dolar", "tipo de cambio", "peso mexicano", "banxico", "tasa",
            "desempleo", "empleo", "empleos", "salario", "salario minimo", "presupuesto",
            "deuda", "deficit", "exportacion", "exportaciones", "importacion", "arancel",
            "aranceles", "remesas", "bolsa", "bmv", "inversion", "inversionistas", "nearshoring",
            "pemex", "cfe", "petroleo", "gasolina", "precio", "precios", "inflacion",
            "recesion", "crecimiento", "pobreza", "economia", "mercado", "empresa",
            "inflation", "economy", "tariff", "recession", "stock market", "oil", "trade",
        ],
    },
    {
        "slug": "mundo",
        "label": "Mundo",
        "kw": [
            "estados unidos", "trump", "casa blanca", "congreso de eeuu", "pentagono",
            "china", "xi jinping", "rusia", "putin", "ucrania", "zelenski", "israel", "gaza",
            "hamas", "hezbollah", "iran", "medio oriente", "otan", "union europea",
            "onu", "apec", "g20", "cumbre", "venezuela", "maduro", "cuba", "colombia",
            "petro", "brasil", "lula", "argentina", "milei", "chile", "peru", "guatemala",
            "honduras", "el salvador", "bukele", "nicaragua", "corea del norte", "japon",
            "india", "reino unido", "francia", "alemania", "espana", "guerra", "conflicto",
            "trump", "white house", "china", "russia", "ukraine", "israel", "gaza", "war",
            "nato", "european union", "united nations", "summit",
        ],
    },
    {
        "slug": "migracion",
        "label": "Migracion",
        "kw": [
            "migrante", "migrantes", "caravana", "deportacion", "deportados", "ice",
            "cbp", "patrulla fronteriza", "border patrol", "frontera", "fronteriza", "aduana",
            "cruce", "cruces", "visa", "asilo", "refugiado", "refugiados", "tijuana",
            "mexicali", "juarez", "matamoros", "reynosa", "nogales", "sonora", "baja california",
            "migrant", "migrants", "deportation", "border", "asylum", "refugee",
        ],
    },
    {
        "slug": "justicia",
        "label": "Justicia",
        "kw": [
            "sentencia", "condena", "condenado", "absuelto", "juez", "jueza", "amparo",
            "corrupcion", "corrupto", "soborno", "cohecho", "peculado", "desvio",
            "uif", "lavado de dinero", "auditoria", "asf", "ine", "fiscal", "denuncia",
            "denuncias", "investigacion", "imputado", "proceso penal", "tribunal",
            "impunidad", "transparencia", "contrato", "licitacion", "fraude",
            "corruption", "trial", "verdict", "court", "indicted", "fraud",
        ],
    },
    {
        "slug": "salud",
        "label": "Salud",
        "kw": [
            "salud", "imss", "issste", "hospital", "hospitales", "medicamento",
            "medicamentos", "desabasto", "vacuna", "vacunacion", "virus", "brote",
            "epidemia", "pandemia", "covid", "influenza", "dengue", "sarampion", "obesidad",
            "diabetes", "cancer", "embarazo", "aborto", "salud publica", "oms", "opa",
            "secretaria de salud", "doctor", "pacientes", "cirugia",
            "health", "vaccine", "outbreak", "disease", "hospital", "cancer",
        ],
    },
    {
        "slug": "ciencia",
        "label": "Ciencia y tecnologia",
        "kw": [
            "nasa", "spacex", "satelite", "cohete", "mision espacial", "luna", "marte",
            "inteligencia artificial", "ia", "robot", "robots", "chip", "semiconductores",
            "estudio", "investigacion cientifica", "cientificos", "descubrimiento",
            "universidad", "unam", "ipn", "tecnologia", "internet", "ciberseguridad",
            "hackeo", "hackeos", "hacker", "hackers", "ciberataque", "ciberataques", "datos personales", "starlink", "energia", "nuclear", "panel solar",
            "nasa", "artificial intelligence", "ai", "chip", "research", "study", "cyber",
        ],
    },
    {
        "slug": "deportes",
        "label": "Deportes",
        "kw": [
            "seleccion mexicana", "tri", "mundial", "copa del mundo", "liga mx", "clausura",
            "apertura", "final", "campeon", "campeones", "titulo", "cruz azul", "america",
            "chivas", "pumas", "tigres", "rayados", "toluca", "boxeo", "canelo", "pelea",
            "olimpiadas", "olimpicos", "medalla", "f1", "formula 1", "checo perez", "nfl",
            "super bowl", "mlb", "nba", "champions", "real madrid", "barcelona", "messi",
            "fichaje", "transferencia", "arbitro", "estadio", "entrenador", "lesion",
            "world cup", "olympics", "championship", "coach",
        ],
    },
    {
        "slug": "cultura",
        "label": "Cultura",
        "kw": [
            "fallecio", "fallece", "murio", "muere", "muerte de", "deceso", "obituario",
            "cantante", "actor", "actriz", "artista", "musico", "banda", "concierto",
            "pelicula", "serie", "netflix", "libro", "escritor", "premio", "nobel",
            "festival", "museo", "exposicion", "teatro", "novela", "documental",
            "gastronomia", "restaurante", "chef", "turismo", "viajeros", "tradicion",
            "dia de muertos", "virgen de guadalupe", "peregrinacion", "feria",
            "died", "dies", "death", "singer", "actor", "movie", "award", "festival",
        ],
    },
    {
        # el motor usa este slug como cajon de sastre cuando nada puntua
        "slug": "industria",
        "label": "Portada",
        "kw": [],
    },
]

# peso editorial de cada seccion al elegir la portada
CAT_BOOST = {
    "seguridad": 1.2, "clima": 1.2, "politica": 1.15, "economia": 1.0, "mundo": 0.95,
    "justicia": 0.9, "migracion": 0.85, "salud": 0.8, "ciencia": 0.6,
    "industria": 0.5, "deportes": 0.45, "cultura": 0.3,
}

STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by", "from", "as",
    "is", "are", "was", "were", "be", "been", "its", "it", "this", "that", "new", "how", "why", "what",
    "el", "la", "los", "las", "un", "una", "de", "del", "en", "y", "o", "que", "por", "para", "con",
    "al", "lo", "su", "sus", "se", "es", "son", "como", "mas", "pero", "il", "lo", "gli", "di", "da",
    "che", "per", "con", "una", "uno",
    "s", "will", "could", "can", "says", "said",
}

# terminos que anclan un titular a una noticia dura (para fuentes generalistas
# marcadas con generic: true, tipo Sopitas o un diario de estilo de vida)
NEWS_RE = re.compile(
    r"(?<![a-z])(presidente|presidenta|gobierno|congreso|senado|diputados|secretario"
    r"|secretaria|fiscalia|juez|sentencia|policia|militar|guardia nacional|detenido"
    r"|homicidio|asesinato|masacre|cartel|secuestro|extorsion|sismo|terremoto|temblor"
    r"|huracan|inundacion|volcan|alerta|evacuacion|inflacion|dolar|pib|banxico|arancel"
    r"|presupuesto|deuda|exportacion|migrante|migrantes|deportacion|frontera|eleccion"
    r"|reforma|ley|decreto|corrupcion|fraude|salud|vacuna|hospital|desabasto|guerra"
    r"|ataque|explosion|incendio|accidente|muerto|muertos|heridos|fallecio|renuncia"
    r"|president|congress|senate|election|minister|court|police|military|killed|shooting"
    r"|earthquake|hurricane|flood|inflation|tariff|border|migrant|war|attack|died"
    r"|sheinbaum|morena|pemex|cfe|imss|banxico)(?![a-z])"
)

# Google News añade " - El Medio" al final del titular
PUB_SUFFIX_RE = re.compile(r"\s+[-–—]\s+[^-–—]{2,42}$")


def strip_pub_suffix(title):
    return PUB_SUFFIX_RE.sub("", title).strip() or title

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
IMG_RE = re.compile(r"""<img[^>]+?src=["']([^"']+)["']""", re.I)

# titulares que no son noticia (farandula, listiculos, servicio, sensacionalismo)
NOISE_RE = re.compile(
    r"(as[ií] reaccionaron|las redes reaccionan|reacciones de las redes|memes?"
    r"|videoan[aá]lisis|en video:"
    r"|en fotos:|en im[aá]genes:|galer[ií]a:|minuto a minuto|en vivo:"
    r"|hor[oó]scopo|receta de|c[oó]mo preparar|qu[eé] significa tu"
    r"|look de|outfit|tendencias de moda|se besan|romance|boda de|tatuaje|tatuajes"
    r"|qu[eé] opina|opini[oó]n:|editorial:|columna:|carta al director"
    r"|pron[oó]stico del tiempo|clima en|d[oó]lar hoy|tipo de cambio hoy"
    r"|resultados de la jornada|alineaciones|el partido minuto"
    r"|seeking (an? )?(intern|interns|freelance|assistant)|is (now )?hiring|now hiring"
    r"|job (opening|opportunit)|bolsa de trabajo|vacante|sueldo de"
    r"|^\d+ (cosas|formas|razones|tips|consejos|datos que)"
    r"|esto es lo que|lo que debes saber|te contamos|todo lo que)"
    , re.I
)


# --------------------------------------------------------------------------- utilidades

def norm(s):
    """minúsculas, sin acentos, espacios simples."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    return WS_RE.sub(" ", s.lower()).strip()


def clean_text(s):
    if not s:
        return ""
    s = html.unescape(s)  # primero decodifica: algunos feeds escapan el HTML (&lt;img&gt;)
    s = TAG_RE.sub(" ", s)
    s = re.sub(r"https?://\S+", " ", s)  # fuera URLs sueltas dentro del texto
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    s = WS_RE.sub(" ", s).strip()
    return s


def _lead_rx(text):
    """Patrón que reconoce `text` al inicio de otra cadena, tolerando puntuación,
    comillas tipográficas y espacios distintos entre palabras."""
    words = re.findall(r"\w+", text or "")
    if not words:
        return None
    return re.compile(r"^\W*" + r"\W+".join(re.escape(w) for w in words) + r"(?!\w)\W*", re.I)


def strip_lead(excerpt, prefixes):
    """Quita del inicio del extracto lo que repite el medio o el titular.

    Drapers, por ejemplo, publica "Drapers <titular> <entradilla>": sin esto el
    extracto del panel y de la cápsula empieza leyendo el nombre del medio.
    """
    text = excerpt or ""
    # el más largo primero: si el titular empieza por el nombre del medio
    # ("Drapers reveals…"), quitar solo "Drapers" se comería una palabra de más
    rxs = [rx for rx in (_lead_rx(p) for p in sorted(set(prefixes), key=len, reverse=True)) if rx]
    changed = True
    while changed and text:
        changed = False
        for rx in rxs:
            m = rx.match(text)
            if m and m.end() < len(text):
                text = text[m.end():]
                changed = True
                break
    return text.strip()


def truncate(s, limit=230):
    s = clean_text(s)
    if len(s) <= limit:
        return s
    cut = s[:limit]
    if " " in cut[limit - 30:]:
        cut = cut[: cut.rfind(" ")]
    else:
        cut = cut[: limit - 1]
    return cut.rstrip(" ,;:-–—") + "…"


def local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_date(raw):
    if not raw:
        return None
    raw = raw.strip()
    # RFC 822 ("Wed, 05 Nov 2026 10:00:00 +0000")
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(raw)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        pass
    # ISO 8601
    txt = raw.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.fromisoformat(txt) if fmt is None else datetime.strptime(txt, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _fetch_once(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding", "").lower() == "gzip":
            raw = gzip.decompress(raw)
        return raw


def fetch(url, retries=2):
    last = None
    for attempt in range(retries):
        try:
            return _fetch_once(url)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last


# --------------------------------------------------------------------------- parseo de feeds

def parse_feed(raw, source):
    root = ET.fromstring(raw)
    if local(root.tag) == "feed":
        entries = [el for el in root if local(el.tag) == "entry"]
        return [atom_item(el) for el in entries]

    channel = None
    for el in root:
        if local(el.tag) == "channel":
            channel = el
            break
    container = channel if channel is not None else root
    items = [el for el in container if local(el.tag) == "item"]
    return [rss_item(el) for el in items]


def _children(el):
    out = {}
    for ch in el:
        name = local(ch.tag).lower()
        if name in out:
            continue
        out[name] = ch
    return out


def _text(el):
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _first_img(markup):
    if not markup:
        return ""
    m = IMG_RE.search(markup)
    if not m:
        return ""
    src = html.unescape(m.group(1)).strip()
    if src.startswith("data:") or src.startswith("//"):
        return "https://" + src[2:] if src.startswith("//") else ""
    return src


def _media_image(el):
    for ch in el.iter():
        name = local(ch.tag).lower()
        if name in ("content", "thumbnail", "group"):
            for key in ("url", "href"):
                v = ch.attrib.get(key, "")
                if v and re.search(r"\.(jpe?g|png|webp|avif)(\?|$)", v, re.I):
                    return html.unescape(v)
    return ""


def _link_from(el):
    for ch in el:
        if local(ch.tag).lower() == "link":
            href = ch.attrib.get("href")
            if href:
                rel = ch.attrib.get("rel", "alternate")
                if rel == "alternate":
                    return href.strip()
            txt = (ch.text or "").strip()
            if txt.startswith("http"):
                return txt
    return ""


def rss_item(el):
    kids = _children(el)
    title = clean_text(_text(kids.get("title")))
    link = _link_from(el) or _text(kids.get("guid"))
    raw_body = _text(kids.get("encoded")) or _text(kids.get("description")) or _text(kids.get("summary"))
    image = (
        _media_image(el)
        or _first_img(_text(kids.get("encoded")))
        or _first_img(_text(kids.get("description")))
    )
    date = (
        parse_date(_text(kids.get("pubdate")))
        or parse_date(_text(kids.get("date")))
        or parse_date(_text(kids.get("published")))
        or parse_date(_text(kids.get("updated")))
    )
    return {
        "title": title,
        "link": (link or "").strip(),
        "body": raw_body,
        "image": image,
        "published": date,
        "via": clean_text(_text(kids.get("source"))),
    }


def atom_item(el):
    kids = {}
    for ch in el:
        name = local(ch.tag).lower()
        kids.setdefault(name, ch)
    title = clean_text(_text(kids.get("title")))
    link = _link_from(el)
    body = _text(kids.get("content")) or _text(kids.get("summary"))
    image = _media_image(el) or _first_img(body)
    date = parse_date(_text(kids.get("published"))) or parse_date(_text(kids.get("updated")))
    return {
        "title": title,
        "link": (link or "").strip(),
        "body": body,
        "image": image,
        "published": date,
    }


# --------------------------------------------------------------------------- clasificación

def _prep_kw():
    for c in CATS:
        if not c["kw"]:
            c["re"] = None
            continue
        alts = []
        for k in sorted(c["kw"], key=len, reverse=True):
            k = norm(k)
            if not k:
                continue
            alts.append(re.escape(k).replace(r"\ ", r"\s+"))
        c["re"] = re.compile(r"(?<![a-z0-9])(?:" + "|".join(alts) + r")(?![a-z0-9])", re.I)


_prep_kw()


# secciones que una revista de consumo puede aportar. Las locales (México y LatAm)
# también cuentan pasarela, diseño y calzado: ahí es donde cubren a los diseñadores
# y las semanas de la moda de la región, que no aparecen en la prensa internacional.
STRICT_OK = {"negocio", "retail", "sostenibilidad", "personas"}
STRICT_OK_LOCAL = STRICT_OK | {"pasarela", "diseno"}  # calzado no: ahí son guías de compra


def classify(title, body, strict=False, allowed=STRICT_OK):
    """Devuelve la sección principal, ordenada por puntuación.

    strict=True (revistas de consumo): solo el titular decide, porque el cuerpo
    de un artículo de lifestyle menciona 'store', 'collection' o 'beauty' y
    ensucia la clasificación.
    """
    nt = " " + norm(title) + " "
    nb = " " + norm(truncate(body, 450)) + " "
    scored = []
    for idx, c in enumerate(CATS):
        if not c["re"]:
            continue
        hits_t = len(c["re"].findall(nt))
        hits_b = 0 if strict else len(c["re"].findall(nb))
        if not hits_t and not hits_b:
            continue
        score = min(hits_t * 3.0, 6.0) + min(hits_b * 0.4, 1.8) - idx * 0.01
        scored.append((score, c["slug"]))
    scored.sort(reverse=True)
    if not scored:
        return ["industria"]
    # revistas de consumo: solo si el titular apunta a un tema de industria
    if strict and scored[0][1] not in allowed:
        return ["industria"]
    return [slug for _, slug in scored[:3]]


# algunas ediciones locales (Vogue México) republican notas de Vogue Italia en italiano
IT_WORDS = {"di", "il", "della", "delle", "degli", "dei", "più", "gli", "nel", "nella", "sono", "dello"}


def wrong_lang(title, lang):
    if lang != "es":
        return False
    words = set(re.findall(r"\w+", title.lower()))
    return len(words & IT_WORDS) >= 2


def tokens(title):
    return {w for w in norm(title).split() if len(w) > 2 and w not in STOP and not w.isdigit()}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b)


def is_dup(a, b):
    t1, t2 = a["_tok"], b["_tok"]
    if not t1 or not t2:
        return False
    short, long_ = (t1, t2) if len(t1) <= len(t2) else (t2, t1)
    # un titular contenido en otro con 3+ palabras significativas = misma noticia
    if len(short) >= 3 and short.issubset(long_):
        return True
    return jaccard(t1, t2) >= 0.5


def canonical(link):
    link = (link or "").strip().lower()
    link = re.sub(r"^https?://", "", link)
    link = re.sub(r"^www\.", "", link)
    link = link.split("#")[0]
    link = re.sub(r"\?.*$", "", link)
    return link.rstrip("/")


TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source", "smid", "partner", "cmpid"}


def clean_link(link):
    """Quita parámetros de seguimiento (utm_*, fbclid...) para que el enlace quede limpio."""
    try:
        parts = urllib.parse.urlsplit(link)
        if not parts.query:
            return link
        keep = [
            (k, v)
            for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in TRACKING
        ]
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(keep), "")
        )
    except Exception:
        return link


# tipo de acontecimiento: sirve para reconocer la misma noticia contada por varios medios
EVENTS = [
    ("resultados", re.compile(
        r"(?<![a-z])(sales|revenue|revenues|earnings|profit|quarter|quarterly|q[1-4]|outlook|forecast"
        r"|results|guidance|margin|turnover|ingresos|ventas|resultados|fatturato|utile|bilancio)(?![a-z])")),
    ("fichajes", re.compile(
        r"(?<![a-z])(names|named|appoints|appointed|exits|departs|steps down|resigns|hires|joins"
        r"|director creativo|nombra|nombramiento|dimite|nomina|dimissioni|direttore creativo)(?![a-z])")),
    ("operacion", re.compile(
        r"(?<![a-z])(acquires|acquisition|merger|stake|takeover|investment|funding|ipo|buyout"
        r"|adquiere|compra|fusion|inversion)(?![a-z])")),
]


# ------------------------------------------------------------------ entidades
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

ENT_RX = re.compile(r"\b([A-Z\u00c0-\u00dc][a-z\u00e0-\u00ff]{2,})\b")
ACRONIMO_RX = re.compile(r"\b([A-Z]{2,6})\b")
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
    # violencia va antes que muerte: "tiroteo deja seis muertos" es un ataque, no
    # un obituario, y asi todos los medios caen en la misma clase
    ("violencia", r"(balacera|ataque|tiroteo|masacre|enfrentamiento|homicidio|ejecutad"
                  r"|asesinat|shooting|attack|massacre|killed)"),
    ("muerte", r"(muere|murio|fallece|fallecio|muerto|muerta|muertos|deceso|obituario"
               r"|died|dies|death)"),
    ("renuncia", r"(renuncia|renuncio|dimite|dimision|destitu|cese|despide|resign|steps down)"),
    ("nombramiento", r"(nombra|nombramiento|designa|appoint|ratifica|nuevo titular)"),
    ("detencion", r"(detenido|detenidos|detencion|captur|arrest|vinculado a proceso"
                  r"|consignad|extradit|aprehend)"),
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



# --------------------------------------------------------------------------- pipeline

def resolve_google_links(items, cache_path, limit=40):
    """Cambia los enlaces de Google News por el artículo real, con su foto y entradilla."""
    google = [it for it in items if enlaces.es_google(it["link"])]
    if not google:
        return 0
    # primero las búsquedas por tema (Tijuana, Pasarelas MX), luego por peso editorial
    google.sort(key=lambda it: (not it.get("aggregator"), -it["weight"]))
    cache = enlaces.load_cache(cache_path)
    infos = enlaces.resolve([it["link"] for it in google], cache, limit=limit)
    enlaces.save_cache(cache_path, cache)
    hechos = 0
    for it in google:
        info = infos.get(it["link"]) or {}
        if not info.get("url"):
            continue
        it["link"] = clean_link(info["url"])
        hechos += 1
        if not it["image"] and info.get("image", "").startswith("http"):
            it["image"] = info["image"]
        desc = strip_lead(clean_text(info.get("desc", "")), [it["source_name"], it.get("via", ""), it["title"]])
        if len(desc) >= 40 and (not it["excerpt"] or it["excerpt"].startswith("Publicado por")):
            it["excerpt"] = truncate(desc)
    return hechos


def build(sources, days, cache_path=None):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    results, failures = [], []

    def work(src):
        errors = []
        urls = [src["url"]] + ([src["fallback"]] if src.get("fallback") else [])
        for idx, url in enumerate(urls):
            try:
                parsed = parse_feed(fetch(url), src)
                if parsed:
                    return src, parsed, None, idx > 0 or bool(src.get("mirror"))
                errors.append("feed vacio")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
        return src, [], " | ".join(errors), False

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for src, parsed, err, mirrored in ex.map(work, sources):
            if err and not parsed:
                failures.append((src["name"], err))
                continue
            results.append((src, parsed, mirrored))

    items, seen_links = [], set()
    for src, parsed, mirrored in results:
        kind = src.get("kind", "trade")
        kept = 0
        for it in parsed:
            title = strip_pub_suffix(it["title"]) if mirrored else it["title"]
            link = it["link"]
            if not title or not link.startswith("http"):
                continue
            if NOISE_RE.search(title) or wrong_lang(title, src.get("lang")):
                continue
            if mirrored and len(title) < 20:
                continue  # Google News a veces devuelve solo el nombre de una marca
            if src.get("generic") and not NEWS_RE.search(norm(title)):
                continue
            pub = it["published"] or now
            if pub < cutoff or pub > now + timedelta(days=1):
                continue
            can = canonical(link)
            if not can or can in seen_links:
                continue
            # una noticia = una sección (la de mayor puntuación)
            allowed = STRICT_OK_LOCAL if src.get("local") else STRICT_OK
            tags = classify(title, it["body"], strict=(kind == "consumer"), allowed=allowed)[:1]
            # las revistas de consumo solo entran si la noticia es de industria
            if tags[0] == "industria" and kind == "consumer":
                continue
            seen_links.add(can)
            body = strip_lead(clean_text(it["body"]), [src["name"], src["short"], title])
            excerpt = truncate(body)
            if mirrored and norm(excerpt).startswith(norm(title)[:40]):
                excerpt = ""  # el espejo solo devuelve "Titular - Medio"
            if len(excerpt) < 40:
                excerpt = ""
            if not excerpt and mirrored and src.get("aggregator") and it.get("via"):
                # agregador (Google News por tema): al menos se sabe qué medio la publicó
                excerpt = f"Publicado por {it['via']}."
            image = it["image"] or ""
            if image and not image.startswith("http"):
                image = urllib.parse.urljoin(link, image)  # rutas relativas de algunos feeds
            items.append(
                {
                    "title": title,
                    "link": clean_link(link),
                    "excerpt": excerpt,
                    "image": image,
                    "published": pub,
                    "source": src["short"],
                    "source_name": src["name"],
                    "kind": kind,
                    "mirror": mirrored,
                    "weight": float(src["weight"]),
                    "lang": src["lang"],
                    "region": src["region"],
                    "tags": tags,
                    "via": it.get("via", "") if mirrored else "",
                    "aggregator": bool(src.get("aggregator")),
                    "_tok": tokens(title),
                    "_ent": entidades(title), "_ev": event_class(title),
                }
            )
            kept += 1
            if kept >= MAX_PER_FEED:
                break

    merged = merge_items(items)
    if cache_path:
        n = resolve_google_links(merged, cache_path)
        print(f"enlaces de Google News resueltos: {n}")

    for it in merged:
        it.pop("_tok", None)
        it.pop("_ev", None)
        it.pop("_ent", None)
        it.pop("aggregator", None)
        it["also"] = it.get("also", [])
        it["published"] = it["published"].isoformat().replace("+00:00", "Z")
        # id estable: hash del enlace (hash() de Python cambia en cada proceso y
        # rompería la deduplicación del archivo histórico)
        it["id"] = hashlib.sha1(it["link"].encode("utf-8")).hexdigest()[:12]
        it["score"] = round(
            it["weight"] * 1.2
            + _recency_bonus(it["published"])
            + CAT_BOOST.get(it["tags"][0], 0.0)
            + 0.75 * len(it["also"])  # cuantos más medios lo cubren, más importante es
            + (0.35 if it["image"] else 0)
            + (0.15 if 30 <= len(it["title"]) <= 115 else 0)
            + (0.2 if it["excerpt"] else 0),
            3,
        )

    merged.sort(key=lambda x: (x["published"], x["score"]), reverse=True)
    return merged, failures


# campos que definen "de qué medio es" una noticia; se intercambian en bloque
OWN_FIELDS = (
    "title", "link", "excerpt", "image", "published", "source", "source_name",
    "kind", "mirror", "weight", "lang", "region", "tags", "via", "aggregator",
)


def _promote(twin, it):
    """`it` trae enlace directo y `twin` (la principal) vino por el espejo de Google.

    La versión directa pasa a ser la principal: su enlace es el real y estable
    (los de news.google.com son redirecciones opacas que pueden caducar) y trae
    entradilla e imagen propias. El medio del espejo queda en "también en".
    """
    old = {k: twin[k] for k in OWN_FIELDS}
    for k in OWN_FIELDS:
        twin[k] = it[k]
    return old


def merge_items(items):
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
            jac = jaccard(it["_tok"], cand["_tok"])
            # el parecido del titular manda: compartir dos entidades no basta,
            # porque "Sheinbaum" + "Trump" salen en diez historias distintas del
            # mismo dia. Con el titular parecido, basta una entidad y el evento.
            if comun and jac >= 0.25 and (mismo_ev or len(comun) >= 2):
                twin = cand
            elif not ent and not cand.get("_ent") and is_dup(it, cand):
                twin = cand
            if twin is not None:
                break
        if twin is None:
            merged.append(it)
            continue

        other = it
        if os.environ.get("MERGE_DEBUG"):
            print(f"UNE  [{it['source']}] {it['title'][:72]}")
            print(f"  A  [{twin['source']}] {twin['title'][:72]}")
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
        # la historia conserva solo las entidades que comparten TODAS sus notas.
        # Si se unionaran, el cluster se volveria un iman y absorberia cualquier
        # nota que compartiera una sola entidad y el mismo tipo de acontecimiento.
        interseccion = (twin.get("_ent") or set()) & ent
        if interseccion:
            twin["_ent"] = interseccion
    return merged


def _recency_bonus(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return 0.0
    hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    if hours <= 6:
        return 2.0
    if hours <= 18:
        return 1.4
    if hours <= 36:
        return 0.9
    if hours <= 72:
        return 0.4
    return 0.0


TZ_MX = "America/Mexico_City"


def fecha_mx(iso_utc):
    """Fecha de la edición en Ciudad de México (la cápsula de la noche no salta de día)."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(
            ZoneInfo(TZ_MX)).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return (iso_utc or "")[:10]


def video_for(out_dir, date_str, sufijo=""):
    """Cápsula más reciente del día ("" general, "-latam"): noche, mediodía, mañana o día."""
    base = out_dir / "videos"
    for franja in ("-noche", "-mediodia", "-manana", ""):
        nombre = f"{date_str}{franja}{sufijo}.mp4"
        if (base / nombre).exists():
            return f"videos/{nombre}"
    return None


def textos_for(out_dir, date_str, sufijo=""):
    """El archivo de textos de esa misma cápsula."""
    base = out_dir / "videos"
    for franja in ("-noche", "-mediodia", "-manana", ""):
        nombre = f"{date_str}{franja}{sufijo}-textos.txt"
        if (base / nombre).exists():
            return f"videos/{nombre}"
    return None


def pick_hero(items):
    ranked = sorted(items, key=lambda x: x["score"], reverse=True)
    if not ranked:
        return []
    # la noticia principal debe tener imagen: la tarjeta grande se apoya en ella
    lead = next((it for it in ranked if it["image"]), ranked[0])
    hero, used = [lead], {lead["tags"][0]}
    for it in ranked:
        if len(hero) == 3:
            break
        if it in hero or it["tags"][0] in used:
            continue
        hero.append(it)
        used.add(it["tags"][0])
    for it in ranked:
        if len(hero) == 3:
            break
        if it not in hero:
            hero.append(it)
    return hero[:3]


# --------------------------------------------------------------------------- salidas

ARCHIVE_COLS = [
    "id", "published", "title", "source", "section", "lang",
    "link", "excerpt", "image", "also", "mirror", "weight",
]


def update_archive(items, root):
    """Acumula el corpus histórico: un JSON por línea y un CSV para Excel/pandas."""
    d = root / "datos"
    d.mkdir(exist_ok=True)
    jl = d / "noticias.jsonl"

    seen = set()
    seen_same = set()  # mismo medio + mismo titular + mismo día (directo vs espejo)

    def clave(r):
        return "|".join([
            r.get("source", ""),
            norm(r.get("title", ""))[:70],
            str(r.get("published", ""))[:10],
        ])

    if jl.exists():
        for line in jl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            seen.add(row["id"])
            seen_same.add(clave(row))

    nuevos = 0
    with jl.open("a", encoding="utf-8") as f:
        for it in sorted(items, key=lambda x: x["published"]):
            row = {
                "id": it["id"],
                "published": it["published"],
                "title": it["title"],
                "source": it["source"],
                "section": it["tags"][0],
                "lang": it["lang"],
                "link": it["link"],
                "excerpt": it["excerpt"],
                "image": it["image"],
                "also": "; ".join(it["also"]),
                "mirror": it["mirror"],
                "weight": it["weight"],
            }
            if row["id"] in seen or clave(row) in seen_same:
                continue
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            seen.add(row["id"])
            seen_same.add(clave(row))
            nuevos += 1

    rows = [json.loads(l) for l in jl.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows.sort(key=lambda r: r.get("published", ""), reverse=True)
    with (d / "noticias.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ARCHIVE_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return nuevos, len(rows)


def write_digest(items, meta, path):
    lines = []
    d = datetime.fromisoformat(meta["generated"].replace("Z", "+00:00"))
    fecha = d.strftime("%d/%m/%Y")
    lines.append(f"# Moda Radar · {fecha}")
    lines.append("")
    lines.append(
        f"**{len(items)} noticias · {meta['sources_ok']} fuentes · ventana de {meta['days']} días**"
    )
    if meta["sources_failed"]:
        lines.append("")
        lines.append(f"_Fuentes que fallaron esta edición: {', '.join(meta['sources_failed'])}_")
    lines.append("")

    if meta["hero"]:
        lines.append("## Lo esencial")
        lines.append("")
        for it in meta["hero"]:
            lines.append(f"### [{it['title']}]({it['link']})")
            lines.append(f"_{it['source']}{' · también en ' + ', '.join(it['also']) if it['also'] else ''}_")
            if it["excerpt"]:
                lines.append("")
                lines.append(it["excerpt"])
            lines.append("")

    for cat in CATS:
        group = [it for it in items if cat["slug"] in it["tags"]]
        if not group:
            continue
        lines.append(f"## {cat['label']} ({len(group)})")
        lines.append("")
        for it in group[:20]:
            hora = datetime.fromisoformat(it["published"].replace("Z", "+00:00")).strftime("%H:%M")
            extra = f" · también en {', '.join(it['also'])}" if it["also"] else ""
            lines.append(f"- **[{it['title']}]({it['link']})** — {it['source']}{extra} · {hora} UTC")
        if len(group) > 20:
            lines.append(f"- _…y {len(group) - 20} más en el panel_")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Fuentes")
    lines.append("")
    per = {}
    for it in items:
        per[it["source"]] = per.get(it["source"], 0) + 1
    for name, n in sorted(per.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {name}: {n}")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Radar diario de noticias de moda.")
    ap.add_argument("--days", type=int, default=4, help="ventana de días (defecto 4)")
    ap.add_argument("--out", default="docs", help="carpeta de salida del panel (defecto docs)")
    ap.add_argument("--digests", default="digests", help="carpeta de digests Markdown")
    ap.add_argument("--sources", default="sources.json", help="catálogo de fuentes")
    ap.add_argument("--check", action="store_true", help="solo validar las fuentes y salir")
    ap.add_argument("--render-only", action="store_true", help="regenerar el panel desde latest.json")
    ap.add_argument("--limit", type=int, default=0, help="limitar nº de fuentes (pruebas)")
    ap.add_argument("--muestra", type=int, default=0, help="con --check: titulares de ejemplo por fuente")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    from pathlib import Path

    root = Path(__file__).resolve().parent
    cfg = json.loads((root / args.sources).read_text(encoding="utf-8"))
    sources = cfg["sources"]
    if args.limit:
        sources = sources[: args.limit]

    if args.check:
        ok = bad = 0
        for src in sources:
            urls = [("", src["url"])] + ([("espejo ", src["fallback"])] if src.get("fallback") else [])
            for etiqueta, url in urls:
                try:
                    parsed = parse_feed(fetch(url), src)
                    if not parsed:
                        raise ValueError("feed vacio")
                    n = len(parsed)
                    dates = [p["published"] for p in parsed if p["published"]]
                    newest = max(dates).strftime("%Y-%m-%d %H:%M") if dates else "sin fecha"
                    con_img = sum(1 for p in parsed if p["image"])
                    print(f"  OK  {n:>3} items  {src['name']:<30} {newest}  img {con_img}/{n}  {etiqueta}{url}")
                    recientes = sorted(
                        parsed, key=lambda p: p["published"] or datetime.min.replace(tzinfo=timezone.utc),
                        reverse=True,
                    )
                    for p in recientes[: args.muestra]:
                        print(f"        · {p['title'][:110]}")
                    ok += 1
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"  ERR              {src['name']:<30} {type(exc).__name__}: {str(exc)[:80]}  {etiqueta}{url}")
            else:
                bad += 1
        print(f"\n{ok} fuentes OK · {bad} con error")
        return 0 if ok else 1

    if args.render_only:
        payload = json.loads((root / args.out / "data" / "latest.json").read_text(encoding="utf-8"))
        items = payload["items"]
        gen = payload.get("generated", "")
        meta = {
            "generated": gen,
            "generated_date": gen[:10],
            "generated_human": datetime.fromisoformat(gen.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M UTC"),
            "days": payload.get("days", args.days),
            "sources_ok": payload.get("sources_ok", 0),
            "sources_failed": payload.get("sources_failed", []),
            "hero": pick_hero(items),
            "category_order": CATS,
            "video": video_for(root / args.out, fecha_mx(gen)),
            "video_latam": video_for(root / args.out, fecha_mx(gen), "-latam"),
            "textos": textos_for(root / args.out, fecha_mx(gen)),
        }
        (root / args.out / "index.html").write_text(ui.render(items, meta), encoding="utf-8")
        print(f"panel regenerado ({'con' if meta['video'] else 'sin'} capsula)")
        return 0

    print(f"moda-radar · {len(sources)} fuentes · ventana {args.days} días")
    items, failures = build(sources, args.days, cache_path=root / "datos" / "enlaces-cache.json")
    for name, err in failures:
        print(f"  ! {name}: {err}")

    now = datetime.now(timezone.utc)
    out = root / args.out
    hero = pick_hero(items)
    meta = {
        "generated": now.isoformat().replace("+00:00", "Z"),
        "generated_date": now.strftime("%Y-%m-%d"),
        "generated_human": now.strftime("%d/%m/%Y %H:%M UTC"),
        "days": args.days,
        "sources_ok": len(sources) - len(failures),
        "sources_failed": [n for n, _ in failures],
        "hero": hero,
        "category_order": CATS,
        "video": video_for(out, fecha_mx(now.isoformat())),
        "video_latam": video_for(out, fecha_mx(now.isoformat()), "-latam"),
        "textos": textos_for(out, fecha_mx(now.isoformat())),
    }

    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(ui.render(items, meta), encoding="utf-8")

    payload = {
        "generated": meta["generated"],
        "days": args.days,
        "count": len(items),
        "sources_ok": meta["sources_ok"],
        "sources_failed": meta["sources_failed"],
        "items": items,
    }
    blob = json.dumps(payload, ensure_ascii=False, indent=1)
    (out / "data" / "latest.json").write_text(blob, encoding="utf-8")
    (out / "data" / f"news-{now.strftime('%Y-%m-%d')}.json").write_text(blob, encoding="utf-8")

    write_digest(items, meta, root / args.digests / f"{now.strftime('%Y-%m-%d')}.md")

    nuevos, acumuladas = update_archive(items, root)

    print(f"\n{len(items)} noticias · {meta['sources_ok']}/{len(sources)} fuentes · {len(failures)} errores")
    print(f"panel   -> {out / 'index.html'}")
    print(f"digest  -> {root / args.digests / (now.strftime('%Y-%m-%d') + '.md')}")
    print(f"archivo -> {root / 'datos' / 'noticias.jsonl'} (+{nuevos} nuevas, {acumuladas} en total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
