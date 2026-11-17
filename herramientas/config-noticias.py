"""Cambia la configuracion de dominio de aggregate.py: de moda a noticias.

Reemplaza tres bloques (CATS + CAT_BOOST, el ancla de nicho y el filtro de ruido)
y deja el resto del motor intacto. Hace copia de seguridad antes de escribir.

Uso: python herramientas/config-noticias.py
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
OBJETIVO = RAIZ / "aggregate.py"

CATS = '''CATS = [
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
            "sismologico", "volcan", "popocatepetl", "cenapred", "alerta", "evacuacion",
            "huracan", "tormenta", "cicion", "ciclón", "lluvia", "lluvias", "inundacion",
            "inundaciones", "deslave", "deslizamiento", "granizo", "sequia", "ola de calor",
            "frente frio", "helada", "proteccion civil", "damnificados", "emergencia",
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
            "hackeo", "datos personales", "starlink", "energia", "nuclear", "panel solar",
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
}'''

ANCLA = '''# terminos que anclan un titular a una noticia dura (para fuentes generalistas
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
)'''

RUIDO = '''# titulares que no son noticia (farandula, listiculos, servicio, sensacionalismo)
NOISE_RE = re.compile(
    r"(as[ií] reaccionaron|las redes reaccionan|reacciones de las redes|memes? de"
    r"|en fotos:|en im[aá]genes:|galer[ií]a:|minuto a minuto|en vivo:"
    r"|hor[oó]scopo|receta de|c[oó]mo preparar|qu[eé] significa tu"
    r"|look de|outfit|tendencias de moda|se besan|romance|boda de|tatuaje|tatuajes"
    r"|qu[eé] opina|opini[oó]n:|editorial:|columna:|carta al director"
    r"|pron[oó]stico del tiempo|clima en|d[oó]lar hoy|tipo de cambio hoy"
    r"|resultados de la jornada|alineaciones|el partido minuto"
    r"|seeking (an? )?(intern|interns|freelance|assistant)|is (now )?hiring|now hiring"
    r"|job (opening|opportunit)|bolsa de trabajo|vacante|sueldo de"
    r"|^\\d+ (cosas|formas|razones|tips|consejos|datos que)"
    r"|esto es lo que|lo que debes saber|te contamos|todo lo que)"
    , re.I
)'''


def main():
    texto = OBJETIVO.read_text(encoding="utf-8")
    original = texto

    respaldo = OBJETIVO.with_suffix(".py.bak")
    shutil.copy2(OBJETIVO, respaldo)

    # 1) CATS + CAT_BOOST
    patron = re.compile(r"CATS = \[.*?\n\nSTOP = \{", re.S)
    if not patron.search(texto):
        raise SystemExit("no encontre el bloque CATS")
    texto = patron.sub(lambda m: CATS + "\n\nSTOP = {", texto, count=1)

    # 2) ancla de nicho
    patron = re.compile(r"# t[eé]rminos que anclan.*?\n\)\n", re.S)
    if not patron.search(texto):
        raise SystemExit("no encontre el bloque FASHION_RE")
    texto = patron.sub(lambda m: ANCLA + "\n", texto, count=1)
    texto = texto.replace("FASHION_RE.search", "NEWS_RE.search")

    # 3) filtro de ruido
    patron = re.compile(r"# titulares que no son noticia.*?\n\)\n", re.S)
    if not patron.search(texto):
        raise SystemExit("no encontre el bloque NOISE_RE")
    texto = patron.sub(lambda m: RUIDO + "\n", texto, count=1)

    if texto == original:
        raise SystemExit("no cambie nada")
    OBJETIVO.write_text(texto, encoding="utf-8")
    print(f"ok: {OBJETIVO.name} reescrito (respaldo en {respaldo.name})")
    print(f"   secciones: {texto.count(chr(34) + 'slug' + chr(34))}")


if __name__ == "__main__":
    main()
