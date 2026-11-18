"""Seccion tematica y region (Mexico / Mundo) de cada noticia.

Dos preguntas distintas:

  seccion  de que trata: politica, seguridad, justicia, economia, mundo,
           migracion, salud, ciencia, deportes, cultura, clima; "industria" es
           "sin seccion" (se conserva el nombre por compatibilidad).
           Pesa en el ranking y sale en las listas de Telegram.
  region   donde pasa: "mx" o "mundo". Decide la etiqueta del video
           (AHORITA EN MEXICO / EN EL MUNDO). Antes salia del pais del medio,
           asi que una nota de Nvidia en La Jornada salia como "en Mexico".

Como decide la seccion: cada una tiene palabras FUERTES (casi siempre la
definen) y DEBILES (solo ayudan). El titular pesa mas que la entradilla. Si
nada llega al minimo, queda sin seccion. Las noticias de fuera de Mexico sobre
gobiernos, guerras o diplomacia van a "mundo"; las de deportes, economia, etc.
de fuera conservan su tema (la etiqueta del video ya dice EN EL MUNDO).

Medido contra 140 noticias reales clasificadas a mano (ver el PR): la seccion
acertaba 53 % y la region 92 %.

Uso: python secciones.py "titular" ["entradilla"]
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CACHE_IA = RAIZ / "datos" / "secciones-ia.json"

# ------------------------------------------------------------------ vocabulario
# Todo en minusculas y sin acentos (se compara contra el texto normalizado).
TEMAS = {
    "politica": {
        "fuertes": """sheinbaum|presidenta de mexico|gabinete|congreso de la union|camara de diputados|
            diputados|diputado|diputada|senado de la republica|senadores|senador|senadora|legislativo|
            legislatura|gobernador|gobernadora|alcalde|alcaldesa|presidente municipal|ayuntamiento|
            cabildo|morena|pri|prian|movimiento ciudadano|partido verde|oposicion|ine|iee|tepjf|
            tribunal electoral|eleccion|elecciones|electoral|candidato|candidata|candidatura|
            encuesta|encuestas|sondeo|sondeos|consulta popular|reforma electoral|reforma judicial|
            iniciativa de ley|decreto|segob|secretaria de gobernacion|cancilleria|embajador|embajadora|
            embajada|plan mexico|mananera|4t|4 t|cuarta transformacion|marchan|marchas|bloquean|
            protestan|manifestacion|manifestaciones|regidor|regidora|regidores|sobrerrepresentacion|
            coordinaciones estatales|plurinominales|pension bienestar|programas sociales|amlo|lopez obrador|monreal|ebrard|
            alito|adan augusto|taddei|paquete economico|presupuesto de egresos|bilateral|gobernar|
            election|elections|senate|congress|parliament|prime minister|campaign""",
        "debiles": """gobierno|gobierno federal|secretario|secretaria|ley|reforma|iniciativa|partido|
            protesta|protestas|marcha|bloqueo|bloqueos|manifestantes|productores|mesas de dialogo|
            renuncia|nombramiento|designa|funcionarios|politica|politico|presidente|presidenta|
            gobernar|president|minister|vote|policy""",
    },
    "seguridad": {
        "fuertes": """homicidio|homicidios|asesinato|asesinatos|asesinan|asesinado|asesinada|asesinados|
            matan|mataron|ejecutan|ejecutado|balacera|balazos|disparos|ataque armado|sicarios|sicario|
            masacre|narco|narcos|narcotrafico|narcotraficante|narcolaboratorio|narcolaboratorios|
            cartel|carteles|cjng|los mayos|chapitos|familia michoacana|fentanilo|metanfetamina|
            cocaina|marihuana|droga|drogas|capo|extorsion|secuestro|secuestran|desaparecido|desaparecida|
            desaparecidos|desaparicion|levanton|feminicidio|detienen|detenido|detenida|detenidos|
            arrestan|arresto|capturan|abatidos|enfrentamiento|tiroteo|atentado|robo|asalto|asaltan|
            violencia|inseguridad|guardia nacional|sedena|semar|policia|policias|atropellado|
            atropellada|volcadura|accidente vial|muertes viales|cadaver|fosa|fosas|rina|amenaza de bomba|
            amenazas de bomba|murder|killed|shooting|gunman|kidnapping|gang|smuggling|arrested|
            bomb threat|bomb threats|hoax|killer|stabbed|felix gallardo|caro quintero|el mayo zambada|el chapo|
            jefe de jefes|narcomenudeo|rescatan cuerpos|hallan cuerpos|localizan cuerpos|
            cabeza humana|restos humanos|descuartizado|criminales|delincuentes|ladron|ladrones|
            la mana""",
        "debiles": """militar|militares|soldados|ejercito|marina|operativo|operativos|captura|muere|muertos|
            cuerpos|incendio|explosion|choque|accidente|crash|seguridad|motociclista|motociclistas""",
    },
    "justicia": {
        "fuertes": """juez|jueza|jueces|tribunal|tribunales|sentencia|sentencian|sentenciado|condena|
            condenan|condenado|absuelto|amparo|juicio|proceso penal|vinculan a proceso|vinculado a proceso|
            imputado|imputada|carpeta de investigacion|corrupcion|corrupto|soborno|cohecho|peculado|
            lavado de dinero|uif|asf|fraude|trata de personas|extradicion|extraditado|
            se entrega a la justicia|apelacion|scjn|suprema corte|poder judicial|traicion a la patria|
            convicts|convicted|conviction|appeal|trial|verdict|court|indicted|fraud|lawsuit|sues|probe""",
        "debiles": """fiscal|fiscalia|denuncia|denuncian|denunciado|investigacion|investigan|
            investigating|audiencia|causa|juzgado|
            demanda|demandan|acusa|acusado|acusan|accused""",
    },
    "economia": {
        "fuertes": """economia|economica|economico|inflacion|pib|crecimiento economico|recesion|
            peso mexicano|el peso|tipo de cambio|dolar|banxico|reserva federal|fed|tasa de interes|
            tasas de interes|bolsa|bmv|wall street|dow jones|nasdaq|acciones|mercados|inversion|
            inversiones|inversionistas|empresa|empresas|empresarios|ipo|ventas|aranceles|arancel|
            exportaciones|importaciones|comercio exterior|t mec|tmec|remesas|empleo|empleos|
            desempleo|salario|salario minimo|aguinaldo|pobreza|buen fin|profeco|precios|gasolina|
            diesel|petroleo|pemex|cfe|impuestos|deuda|banco|bancos|bbva|banco mundial|fmi|ganancias|
            manufactura|derrama|stablecoins|bitcoin|cripto|criptomonedas|ceo|calificacion crediticia|
            calificadora|fitch|moodys|standard poors|peso se aprecia|peso se deprecia|peso retrocede|
            peso avanza|peso cierra|peso gana|peso pierde|peso cae|peso sube|precio del|precios del|
            crudo|brent|barril|gas lp|gas natural|consumo privado|inegi|bank|banks|financial|
            ingresos|pymes|creditos|credito|prestamos|hipotecas|vivienda|
            earnings|stocks|shares|economy|inflation|tariff|tariffs|trade deal|rate hikes|recession|
            pay|wages""",
        "debiles": """precio|mercado|negocio|negocios|comercio|industria|sector|consumo|ofertas|compras|
            nvidia|apple|google|amazon|microsoft|tesla|openai|anthropic|meta|financiero|financiera|
            trimestre|ratificacion""",
    },
    "mundo": {
        "fuertes": """guerra|otan|nato|onu|naciones unidas|union europea|sanciones|misiles|misil|
            bombardeo|invasion|tropas|alto el fuego|tregua|gaza|hamas|hezbollah|kremlin|crimea|
            zelenski|putin|corea del norte|kim jong|papa leon|vaticano|cumbre|apec|g20|g7|
            incursion|espacio aereo|aviones de combate|oligarcas|oligarchs|
            war|summit|troops|missile|ceasefire|sanctions|spying|espia|espionaje""",
        "debiles": """ataque|ataca|atacan|conflicto|diplomacia|canciller|papa|army|military""",
    },
    "migracion": {
        "fuertes": """migrante|migrantes|migracion|migratorio|migratoria|caravana|deportacion|
            deportaciones|deportados|deportado|ice|cbp|patrulla fronteriza|border patrol|asilo|
            refugiado|refugiados|garita|garitas|cruce fronterizo|cruzar a|para cruzar|tiempos de espera|
            sentri|ready lane|visa|visas|inm|para ir a el paso|para ir a san diego|
            migrant|migrants|deportation|asylum|refugee""",
        "debiles": """frontera|fronteriza|fronterizo|aduana|cruce|cruces|filas|filas de""",
    },
    "salud": {
        "fuertes": """salud|imss|issste|imss bienestar|hospital|hospitales|clinica|medicamento|
            medicamentos|desabasto|vacuna|vacunas|vacunacion|virus|brote|epidemia|pandemia|covid|
            influenza|dengue|sarampion|obesidad|diabetes|cancer|tumor|cirugia|cataratas|pacientes|
            enfermedad|enfermedades|salud mental|nutricion|fibra|alimentacion|oms|ops|cofepris|fda|
            muerte digna|eutanasia|health|vaccine|outbreak|disease""",
        "debiles": """medico|medica|medicos|doctor|embarazo|alimentos|crema|piel""",
    },
    "ciencia": {
        "fuertes": """ciencia|cientifico|cientificos|nasa|spacex|espacio exterior|espacial|satelite|cohete|
            voyager|sonda|telescopio|astronomos|marte|inteligencia artificial|ia|chatgpt|
            tecnologia|tecnologica|tecnologico|ciberseguridad|ciberataque|ciberataques|hackeo|hackeos|
            hackers|hacker|codigo malicioso|malware|datos personales|algoritmo|robot|robots|chip|chips|
            semiconductores|software|artificial intelligence|cyber|cyberattack|robotics""",
        "debiles": """estudio|investigacion|investigadores|universidad|unam|ipn|internet|digital|app|
            aplicacion|actualizacion|ingenieros|3d|luna|google|apple|openai|nvidia|anthropic|ai""",
    },
    "deportes": {
        "fuertes": """liga mx|seleccion mexicana|futbol|futbolista|gol|goles|jugador|jugadores|
            entrenador|director tecnico|torneo|liguilla|campeonato|campeon|mundial 2026|copa del mundo|
            fifa|champions|liga de campeones|nfl|nba|mlb|nhl|beisbol|baseball|basquetbol|baloncesto|
            tenis|boxeo|canelo|f1|formula 1|checo perez|olimpicos|olimpiadas|medalla|cruz azul|chivas|
            pumas|tigres|rayados|toluca|club america|salon de la fama|49ers|vikings|pelotazo|
            estadio azteca|automovilismo|baja 1000|rally|carrera de autos|nascar|indycar|
            coach|championship|playoffs|touchdown|world cup|olympics|scores|basketball""",
        "debiles": """estadio|partido|partidos|temporada|fichaje|renovar|renovacion|mundial|clausura|
            apertura|derrota|derrotas|victoria|triunfo|sancion|
            deportivo|deportiva""",
    },
    "cultura": {
        "fuertes": """cultura|arte|artistico|artista|artistas|museo|exposicion|pintura|pintor|pintora|
            obra de arte|frida kahlo|kahlo|diego rivera|subasta|subastas|cine|pelicula|peliculas|
            taquilla|recaudo|estreno|trailer|serie|series|netflix|streaming|actor|actriz|actores|
            cantante|musica|musico|concierto|conciertos|album|festival|teatro|libro|libros|escritor|
            escritora|novela|premios|oscar|grammy|nobel|turismo|turistico|turistica|pueblo magico|
            tradicion|tradiciones|tradicionales|gastronomia|chef|restaurante|moda|james bond|
            auditorio nacional|redoblaje|espectaculos|movie|film|singer|museum""",
        "debiles": """premio|banda|feria|homenaje|estilo|memes|viral|dies at|speech|
            i have a dream""",
    },
    "clima": {
        "fuertes": """clima|pronostico|temperaturas|bajas temperaturas|frente frio|frentes frios|
            onda gelida|ola de calor|lluvias|tormenta|tormenta tropical|huracan|ciclon|inundacion|
            inundaciones|deslave|granizo|sequia|nevada|helada|sismo|sismos|terremoto|temblor|magnitud|
            epicentro|volcan|popocatepetl|erupcion|tsunami|alerta amarilla|alerta naranja|alerta roja|
            alerta sismica|proteccion civil|damnificados|cop31|cop30|cop|cambio climatico|
            calentamiento global|combustibles fosiles|emisiones|medio ambiente|ambiental|contaminacion|
            contingencia ambiental|incendio forestal|adaptacion climatica|wildfire|earthquake|
            hurricane|flood|storm|volcano|climate""",
        "debiles": """lluvia|evacuacion|emergencia|frio""",
    },
}

# sin seccion aunque mencionen otras cosas: sorteos y similares
SIN_SECCION = re.compile(r"\b(resultados del sorteo|sorteo (tris|chispazo|melate|progol)|"
                         r"loteria nacional|horoscopo|correo institucional)\b")

PESO_FUERTE, PESO_DEBIL = 3.0, 1.0
PESO_ENTRADILLA = 0.3          # una palabra de la entradilla vale menos que del titular
MINIMO = 2.0                   # por debajo de esto, sin seccion

# ------------------------------------------------------------------ region
MARCAS_MX = """mexico|mexicano|mexicanos|mexicana|mexicanas|cdmx|edomex|estado de mexico|
    sheinbaum|amlo|lopez obrador|harfuch|monreal|ebrard|alito|noroña|norona|brugada|
    morena|pri|movimiento ciudadano|4t|cuarta transformacion|ine|tepjf|scjn|fgr|segob|sedena|semar|
    sader|sre|sep|imss|issste|pemex|cfe|banxico|inegi|profeco|conagua|cofepris|semarnat|
    palacio nacional|mananera|zocalo|peso mexicano|peso se aprecia|peso se deprecia|peso retrocede|
    peso avanza|peso cierra|peso gana|peso pierde|buen fin|aguinaldo|liga mx|
    seleccion mexicana|cruz azul|chivas|pumas|tigres|rayados|club america|estadio azteca|
    aguascalientes|baja california|campeche|chiapas|chihuahua|coahuila|colima|durango|guanajuato|
    guerrero|hidalgo|jalisco|michoacan|morelos|nayarit|nuevo leon|oaxaca|puebla|queretaro|
    quintana roo|san luis potosi|sinaloa|sonora|tabasco|tamaulipas|tlaxcala|veracruz|yucatan|
    zacatecas|tijuana|mexicali|ensenada|rosarito|tecate|juarez|ciudad juarez|hermosillo|culiacan|
    guasave|los mochis|mazatlan|tuxpan|tlaquepaque|zapopan|tonala|guadalajara|monterrey|saltillo|
    torreon|toluca|cuernavaca|acapulco|cancun|merida|tulum|villahermosa|xalapa|coatzacoalcos|
    tuxtla|tapachula|morelia|uruapan|pachuca|los cabos|cuetzalan|coacalco|ecatepec|naucalpan|
    iztapalapa|coyoacan|tepito|insurgentes|la mesilla|calexico|el paso|san ysidro|otay|garita|
    yaqui|tarahumara"""
MARCAS_FUERA = """estados unidos|eu|ee uu|eeuu|eua|washington|casa blanca|white house|trump|biden|
    vance|hegseth|pentagono|pentagon|reserva federal|fed|wall street|dow jones|nasdaq|california|
    texas|nueva york|new york|florida|arizona|chicago|china|beijing|pekin|xi jinping|rusia|russia|
    russian|moscu|putin|kremlin|ucrania|ukraine|kiev|zelenski|crimea|israel|israeli|israelies|gaza|
    hamas|iran|irani|irak|siria|libano|bahrein|barein|bahrain|arabia saudita|turquia|antalya|
    india|japon|corea|taiwan|filipinas|philippines|tailandia|thailand|indonesia|vietnam|australia|
    reino unido|uk|londres|london|francia|france|paris|alemania|germany|berlin|espana|madrid|
    italia|roma|vaticano|papa leon|portugal|canada|ottawa|cuba|venezuela|maduro|colombia|petro|
    brasil|brazil|brazilian|lula|argentina|milei|chile|peru|lima|bolivia|ecuador|paraguay|
    uruguay|guatemala|guatemalteco|honduras|el salvador|bukele|nicaragua|costa rica|panama|
    haiti|republica dominicana|puerto rico|europa|europeo|europea|europe|african|africa|sudan|
    sudanesas|nigeria|nigerian|ruanda|egipto|macedonia|grecia|greece|singapur|singapore|
    corea del norte|pp|psoe|vox|canarias|cataluna|nsw|abascal|onu|otan|nato|amazonia|amazon|
    apple|google|microsoft|nvidia|openai|anthropic|tesla"""

_MX_NO = re.compile(r"\b(nuevo mexico|new mexico)\b")


def _norm(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", t).strip() + " "


def _rx(lista):
    palabras = [p.strip() for p in lista.replace("\n", "|").split("|") if p.strip()]
    palabras = sorted({_norm(p).strip() for p in palabras}, key=len, reverse=True)
    return re.compile(r"(?<= )(?:" + "|".join(re.escape(p) for p in palabras) + r")(?= )")


_RX = {slug: (_rx(t["fuertes"]), _rx(t["debiles"])) for slug, t in TEMAS.items()}
_RX_MX, _RX_FUERA = _rx(MARCAS_MX), _rx(MARCAS_FUERA)


def _cuenta(rx, texto):
    # (?<= ) y (?= ) no consumen el espacio: dos palabras seguidas cuentan las dos
    return len(rx.findall(texto))


def puntajes(titulo, entradilla=""):
    """Puntaje de cada seccion, para depurar."""
    t, e = _norm(titulo), _norm(entradilla)
    salida = {}
    for slug, (fuerte, debil) in _RX.items():
        p = (PESO_FUERTE * min(_cuenta(fuerte, t), 2) + PESO_DEBIL * min(_cuenta(debil, t), 2)
             + PESO_ENTRADILLA * (PESO_FUERTE * min(_cuenta(fuerte, e), 3)
                                  + PESO_DEBIL * min(_cuenta(debil, e), 3)))
        if p:
            salida[slug] = round(p, 2)
    return salida


def region(titulo, entradilla="", region_fuente="mx"):
    """'mx' si la noticia pasa en Mexico o lo involucra; 'mundo' si no.

    Cuenta marcas de Mexico y de fuera; en el titular, una de Mexico vale 3 y una
    de fuera 2 ("Canada y EU, y ahora Mexico pierde..." es de Mexico). Empate con
    alguna marca de Mexico: mx ("Sheinbaum y Xi Jinping" es noticia de Mexico).
    Sin marcas de ningun lado, decide el pais del medio.
    """
    t = _MX_NO.sub(" ", _norm(titulo))
    e = _MX_NO.sub(" ", _norm(entradilla))
    mx = 3 * _cuenta(_RX_MX, t) + _cuenta(_RX_MX, e)
    fuera = 2 * _cuenta(_RX_FUERA, t) + _cuenta(_RX_FUERA, e)
    if mx and mx >= fuera:
        return "mx"
    if fuera:
        return "mundo"
    return "mx" if region_fuente == "mx" else "mundo"


def seccion(titulo, entradilla="", reg=None, region_fuente="mx"):
    """La seccion tematica. `reg` es la region ya calculada (si no, se calcula)."""
    if SIN_SECCION.search(_norm(titulo)):
        return "industria"
    reg = reg or region(titulo, entradilla, region_fuente)
    p = puntajes(titulo, entradilla)
    if reg == "mx" and p.get("mundo"):
        # Mexico con otro pais (Sheinbaum y Xi, el Papa promete venir) es politica
        p["politica"] = p.get("politica", 0) + p.pop("mundo")
    elif reg == "mundo" and p.get("politica"):
        # politica de otro pais = mundo (la de Mexico con otro pais es politica)
        p["mundo"] = p.get("mundo", 0) + p.pop("politica")
    if not p:
        return "mundo" if reg == "mundo" else "industria"
    orden = list(TEMAS)
    mejor = max(p, key=lambda s: (p[s], -orden.index(s)))
    if p[mejor] < MINIMO:
        return "mundo" if reg == "mundo" else "industria"
    return mejor


def clasificar(titulo, entradilla="", region_fuente="mx"):
    """(seccion, region) de una noticia."""
    reg = region(titulo, entradilla, region_fuente)
    return seccion(titulo, entradilla, reg), reg


# ------------------------------------------------------------------ temas sensibles
# Lo que el robot no publica solo: te pregunta antes (ver orquestador.py).
# Basta con que lo marque la IA o estas palabras: aqui es mejor preguntar de mas.
SENSIBLES = {
    "suicidio": _rx("""suicidio|suicidios|suicida|suicidas|se suicida|se suicido|suicidarse|
        se quito la vida|se quita la vida|quitarse la vida|autolesion|autolesiones|
        suicide|suicidal|self harm|took his own life|took her own life"""),
    "sexual_menores": _rx("""violacion|violaciones|violada|violado|violador|violadores|abuso sexual|
        abusos sexuales|agresion sexual|agredir sexualmente|agredio sexualmente|pederasta|pederastia|
        pedofilia|pedofilo|pornografia infantil|explotacion sexual|trata de personas|abuso infantil|
        maltrato infantil|infanticidio|rape|raped|sexual assault|sexually assaulted|child abuse|
        molested|molestation|grooming"""),
    "grafica": _rx("""cabeza humana|cabezas humanas|restos humanos|desmembrado|desmembrados|desmembrada|
        descuartizado|descuartizados|descuartizada|decapitado|decapitados|decapitada|decapitan|
        mutilado|mutilados|calcinados|cuerpos colgados|colgados de un puente|bolsas con restos|
        cuerpos embolsados|fosa clandestina|fosas clandestinas|masacre|masacres|tortura|torturado|
        torturados|video de la ejecucion|graban ejecucion|dismembered|beheaded|mutilated|massacre"""),
}
_MENOR = _rx("""menor|menores|menor de edad|nina|nino|ninas|ninos|bebe|bebes|adolescente|adolescentes|
    infante|infantes|estudiante de primaria|estudiante de secundaria|child|children|girl|boy|toddler""")
_DANO = _rx("""asesinado|asesinada|asesinan|asesinato|matan|mataron|muere|murio|muerto|muerta|golpeado|
    golpeada|golpean|abusado|abusada|maltratado|maltratada|secuestrado|secuestrada|desaparecido|
    desaparecida|baleado|baleada|apunalado|killed|murdered|beaten|abused""")
NOMBRES_SENSIBLES = {"suicidio": "suicidio o autolesiones", "sexual_menores": "violencia sexual o menores",
                     "grafica": "violencia grafica"}


# "violacion" tambien es de leyes y derechos: esos usos no cuentan
_VIOLACION_LEGAL = re.compile(r" violacion(es)? (a|de|al|del) (los |las |la |el )?"
                              r"(derechos|derecho|ley|leyes|constitucion|debido proceso|amparo|"
                              r"suspension|reglamento|contrato|norma|normas|veda|tratado|privacidad)")


def sensible(titulo, entradilla=""):
    """La categoria sensible de una noticia ("suicidio", "sexual_menores", "grafica") o ""."""
    texto = _VIOLACION_LEGAL.sub(" ", _norm(titulo) + _norm(entradilla))
    for nombre, rx in SENSIBLES.items():
        if rx.search(texto):
            return nombre
    # menores victimas de violencia, aunque no sea sexual
    t = _norm(titulo)
    if _MENOR.search(t) and _DANO.search(t):
        return "sexual_menores"
    return ""


# ------------------------------------------------------------------ revision con IA
SISTEMA_IA = """Eres editor de El Ahorita, un noticiero mexicano. Para cada noticia das su
seccion y su region. Secciones (usa exactamente estas palabras):
- politica: gobierno, partidos, elecciones y politica de Mexico, y relaciones de Mexico con otros paises
- mundo: politica, guerras, diplomacia y sucesos de otros paises que no encajan en otra seccion
- seguridad: crimen, violencia, narco, detenciones, accidentes
- justicia: jueces, tribunales, sentencias, corrupcion, demandas
- economia: economia, empresas, mercados, precios, empleo
- migracion: migrantes, deportaciones, frontera y cruces fronterizos
- salud
- ciencia: ciencia y tecnologia (incluye IA y ciberseguridad)
- deportes
- cultura: arte, espectaculos, cine, musica, turismo, tradiciones, religion
- clima: clima, desastres naturales, medio ambiente
- otros: si no encaja en ninguna
Region: "mx" si ocurre en Mexico o involucra directamente a Mexico o a mexicanos;
"mundo" si no. Una noticia de deportes o economia de otro pais es deportes/economia
con region "mundo".
Sensible ("k"): marca la noticia si trata de alguno de estos temas, aunque sea de pasada:
- "suicidio": suicidio, intentos de suicidio o autolesiones
- "sexual_menores": violencia sexual (violacion, abuso, trata) o menores de edad victimas de violencia
- "grafica": violencia grafica (restos humanos, desmembramientos, decapitados, masacres, tortura)
Si no trata de ninguno, "k" va vacio. Un homicidio sin esos elementos NO es sensible.
Devuelve SOLO JSON: {"r": [{"i": 0, "s": "seccion", "g": "mx", "k": ""}, ...]}"""

VALIDAS = set(TEMAS) | {"otros"}
CATEGORIAS_SENSIBLES = set(SENSIBLES)


def _clave(item):
    return item.get("id") or item.get("link") or item.get("title", "")[:80]


def _leer_cache():
    try:
        return json.loads(CACHE_IA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def con_ia(items, llamar=None):
    """Seccion y region con DeepSeek para una lista corta de noticias.

    Devuelve {clave: (seccion, region, sensible)} solo de las que el modelo respondio
    bien; sensible es "" o una categoria de SENSIBLES.
    Lo ya preguntado se toma de datos/secciones-ia.json. Si la IA falla, devuelve
    lo que haya en cache y el resto se queda con el clasificador por palabras.
    """
    cache = _leer_cache()
    salida = {k: tuple(cache[k]) for k in map(_clave, items)
              if k in cache and len(cache[k]) == 3}      # las de antes no traian "sensible"
    faltan = [it for it in items if _clave(it) not in salida]
    if faltan:
        if llamar is None:
            import guion
            llamar = guion.llamar_llm
        lineas = [f"{i}. {it.get('title', '')}" + (f" || {(it.get('excerpt') or '')[:200]}"
                                                     if it.get("excerpt") else "")
                  for i, it in enumerate(faltan)]
        try:
            texto = llamar(SISTEMA_IA, "\n".join(lineas))
            m = re.search(r"\{.*\}", texto or "", re.S)
            for r in json.loads(m.group(0)).get("r", []) if m else []:
                i, sec, reg = int(r.get("i", -1)), str(r.get("s", "")).lower(), str(r.get("g", "")).lower()
                k = str(r.get("k") or "").lower()
                k = k if k in CATEGORIAS_SENSIBLES else ""
                if 0 <= i < len(faltan) and sec in VALIDAS and reg in ("mx", "mundo"):
                    if sec == "politica" and reg == "mundo":
                        sec = "mundo"      # politica de otro pais: la misma regla que por palabras
                    clave = _clave(faltan[i])
                    salida[clave] = ("industria" if sec == "otros" else sec, reg, k)
                    cache[clave] = list(salida[clave])
        except Exception as e:  # noqa: BLE001
            print(f"  aviso: revision de secciones con IA fallo ({type(e).__name__}: {e})")
        for viejo in list(cache)[:-3000]:
            del cache[viejo]
        try:
            CACHE_IA.parent.mkdir(parents=True, exist_ok=True)
            CACHE_IA.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return salida


def refinar(items, n=25, llamar=None):
    """Corrige con IA la seccion y la region de las `n` mejores del ranking.

    Modifica los items en su lugar (tags, region y sensible) y devuelve cuantos cambiaron.
    Solo se revisan las que pueden publicarse: el resto no lo necesita.
    """
    from relevancia import puntuar
    top = {f["link"] for f in puntuar(items)[:n]}
    elegidas = [it for it in items if it.get("link") in top]
    respuestas = con_ia(elegidas, llamar)
    cambios = 0
    for it in elegidas:
        r = respuestas.get(_clave(it))
        if not r:
            continue
        sec, reg, k = r
        if (it.get("tags") or [""])[0] != sec or it.get("region") != reg:
            cambios += 1
        it["tags"], it["region"], it["seccion_por"] = [sec], reg, "ia"
        it["sensible"] = k or sensible(it.get("title", ""), it.get("excerpt", ""))
    return cambios


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit('uso: python secciones.py "titular" ["entradilla"]')
    tit, ent = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
    print(clasificar(tit, ent), puntajes(tit, ent))
