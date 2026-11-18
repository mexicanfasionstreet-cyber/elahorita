"""Mesa de edicion por Telegram: avisa de las candidatas y recibe tu decision.

El bot solo atiende a tu chat: cualquier otro se ignora. El token y tu chat_id
viven en `.env` (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) y nunca se suben al repo.

Uso:
    python telegram.py --quien        # lee tu chat_id (mandale antes un "hola" al bot)
    python telegram.py --prueba       # manda un mensaje de prueba con botones
    python telegram.py --candidatas   # manda las 3 mejores historias del dia
    python telegram.py --recoger      # lee tus respuestas pendientes
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402

ESTADO = RAIZ / "datos" / "telegram.json"
API = "https://api.telegram.org/bot{token}/{metodo}"
LOTES_GUARDADOS = 8    # listas de candidatas que siguen valiendo (2 dias de franjas)


def esc(texto):
    """Escapa texto ajeno (titulares, errores) para el modo HTML de Telegram."""
    return html.escape(str(texto or ""), quote=False)


# ------------------------------------------------------------------ base
def _llamar(metodo, **params):
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("falta TELEGRAM_BOT_TOKEN en .env")
    datos = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(API.format(token=config.TELEGRAM_TOKEN, metodo=metodo),
                                 data=datos, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            respuesta = json.load(r)
    except urllib.error.HTTPError as e:
        detalle = e.read()[:300].decode("utf-8", "replace")
        raise SystemExit(f"Telegram respondio {e.code}: {detalle}")
    if not respuesta.get("ok"):
        raise SystemExit(f"Telegram: {respuesta}")
    return respuesta.get("result")


def _estado():
    if ESTADO.exists():
        try:
            return json.loads(ESTADO.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"lotes": {}, "offset": 0, "elegidas": []}


def _guardar(datos):
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ envio
def mandar(texto, botones=None):
    """Manda un mensaje; `botones` es [[(etiqueta, dato), ...], ...].

    Si Telegram no puede leer el HTML (un "&" o "<" sin escapar que se colo), se
    reintenta en texto plano: un aviso feo es mejor que un aviso perdido.
    """
    params = {"chat_id": config.TELEGRAM_CHAT, "text": texto,
              "parse_mode": "HTML", "disable_web_page_preview": "true"}
    if botones:
        params["reply_markup"] = json.dumps({"inline_keyboard": [
            [{"text": t, "callback_data": d} for t, d in fila] for fila in botones]})
    try:
        return _llamar("sendMessage", **params)
    except SystemExit as e:
        if "parse entities" not in str(e):
            raise
        params.pop("parse_mode")
        params["text"] = html.unescape(re.sub(r"</?[a-zA-Z][^>]*>", "", texto))
        return _llamar("sendMessage", **params)


def es_mi_chat(chat_id):
    """Solo se obedece al chat de TELEGRAM_CHAT_ID. Sin chat configurado, a nadie."""
    return bool(config.TELEGRAM_CHAT) and str(chat_id) == str(config.TELEGRAM_CHAT)


def _subir(metodo, campo, ruta, mime, texto=""):
    """Sube un archivo al chat (limite de Telegram para bots: 50 MB)."""
    import uuid
    ruta = Path(ruta)
    if not ruta.exists():
        raise SystemExit(f"no existe {ruta}")
    frontera = "----elahorita" + uuid.uuid4().hex
    trozos = []

    def parte(nombre, valor):
        trozos.append((f"--{frontera}\r\nContent-Disposition: form-data; "
                       f"name=\"{nombre}\"\r\n\r\n{valor}\r\n").encode("utf-8"))

    parte("chat_id", config.TELEGRAM_CHAT)
    if texto:
        parte("caption", texto[:900])
    if campo == "video":
        parte("supports_streaming", "true")
    trozos.append((f"--{frontera}\r\nContent-Disposition: form-data; name=\"{campo}\"; "
                   f"filename=\"{ruta.name}\"\r\nContent-Type: {mime}\r\n\r\n").encode("utf-8"))
    trozos.append(ruta.read_bytes())
    trozos.append(f"\r\n--{frontera}--\r\n".encode("utf-8"))
    req = urllib.request.Request(
        API.format(token=config.TELEGRAM_TOKEN, metodo=metodo), data=b"".join(trozos),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={frontera}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        respuesta = json.load(r)
    if not respuesta.get("ok"):
        raise SystemExit(f"Telegram: {respuesta}")
    return respuesta["result"]


def mandar_video(ruta, texto=""):
    """Sube el mp4 al chat."""
    return _subir("sendVideo", "video", ruta, "video/mp4", texto)


def mandar_audio(ruta, texto=""):
    """Sube un mp3 al chat (para escuchar la voz sin armar el video)."""
    return _subir("sendAudio", "audio", ruta, "audio/mpeg", texto)


def quien(datos=None):
    """Saca el chat_id del ultimo mensaje recibido (mandale un 'hola' al bot)."""
    recibidos = _llamar("getUpdates", timeout=0, limit=20)
    chats = {}
    for r in recibidos:
        msg = r.get("message") or r.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            chats[chat["id"]] = chat.get("first_name") or chat.get("username") or "?"
    if not chats:
        print("no hay mensajes. Abre el bot en Telegram y mandale un 'hola'.")
        return None
    for cid, nombre in chats.items():
        print(f"chat_id {cid} · {nombre}")
    ultimo = list(chats.items())[-1][0]
    print(f"\nusa este en .env:\nTELEGRAM_CHAT_ID={ultimo}")
    return str(ultimo)


# ------------------------------------------------------------------ candidatas
def candidatas(n=3):
    """Las mejores historias del dia, en orden y sin repetir personaje."""
    from relevancia import diversificar, puntuar

    datos = json.loads((RAIZ / "docs" / "data" / "latest.json").read_text(encoding="utf-8"))
    items = datos["items"] if isinstance(datos, dict) and "items" in datos else datos
    return diversificar(puntuar(items))[:n]


def guardar_lote(historias):
    """Guarda una lista de opciones con su propio identificador y lo devuelve.

    Las claves son n1, n2, ... en el orden recibido. Una historia con
    "tipo": "nota" o "notavideo" se arma con nota.py (busqueda de /nota o
    /notavideo); sin tipo, con el
    ranking del dia.
    """
    estado = _estado()
    estado.pop("pendientes", None)          # formato viejo, sin lote
    lotes = estado.setdefault("lotes", {})
    base = f"{config.ahora():%m%d%H%M}"
    lote, extra = base, 0
    while lote in lotes:                    # dos listas en el mismo minuto
        extra += 1
        lote = f"{base}{chr(96 + extra)}"
    lotes[lote] = {f"n{i}": h for i, h in enumerate(historias, 1)}
    for viejo in sorted(lotes)[:-LOTES_GUARDADOS]:
        del lotes[viejo]
    _guardar(estado)
    return lote


def mandar_candidatas(n=3):
    """Manda la lista con botones. Cada lista lleva su propio identificador (lote).

    Antes todas usaban "pub:n1/n2/n3": al llegar una lista nueva, los botones de
    la anterior apuntaban a las historias nuevas y se publicaba otra nota.
    """
    ahora = config.ahora()
    historias = {}
    filas, texto = [], [f"<b>El Ahorita</b> · {ahora:%H:%M}\n"]
    for i, f in enumerate(candidatas(n), 1):
        clave = f"n{i}"
        historias[clave] = {
            "titulo": f["title"], "link": f["link"], "seccion": f["seccion"],
            "score": f["score"], "medios": f["medios"], "imagen": f["imagen"],
        }
        texto.append(f"<b>{i}. [{esc(f['seccion'].upper())}]</b> {esc(f['title'][:150])}\n"
                     f"   {f['medios']} medios · score {f['score']} · "
                     f"{f['horas']} h" + (" · con foto" if f["imagen"] else " · sin foto"))
    lote = guardar_lote(list(historias.values()))
    for i in range(1, len(historias) + 1):
        filas.append([(f"Publicar {i}", f"pub:{lote}:n{i}")])
    filas.append([("Ninguna hoy", f"pub:{lote}:nada")])
    mandar("\n".join(texto), filas)
    print("mandadas", len(historias), f"candidatas (lote {lote})")


COMANDOS = [
    ("nota", "Nota urgente: /nota <tema o enlace>"),
    ("notavideo", "Solo el video, para subirlo tu (no gasta cupo): /notavideo <tema>"),
    ("estado", "Que sigue, que salio hoy y el cupo de subidas"),
    ("pausa", "Pausa las franjas: /pausa, /pausa 3h, /pausa hoy, /pausa 2d"),
    ("reanudar", "Quita la pausa"),
    ("saltar", "Brinca la proxima franja (o una: /saltar noche)"),
    ("ayuda", "Lista de comandos"),
]
AYUDA = ("<b>El Ahorita · comandos</b>\n"
         + "\n".join(f"/{c} — {esc(d)}" for c, d in COMANDOS))


def registrar_comandos():
    """El menu de comandos de Telegram (el boton "/" del chat)."""
    return _llamar("setMyCommands", commands=json.dumps(
        [{"command": c, "description": d} for c, d in COMANDOS], ensure_ascii=False))


def _comando(texto):
    """'/pausa@ElAhoritaBot 3h' -> ('pausa', '3h'). Texto que no es comando -> (None, '')."""
    if not texto.startswith("/"):
        return None, ""
    cabeza, _, resto = texto[1:].partition(" ")
    return cabeza.split("@")[0].lower(), resto.strip()


def recoger(texto_libre=False):
    """Lee las respuestas nuevas y devuelve la ultima decision (compatibilidad)."""
    decisiones = recoger_todas(texto_libre)
    return decisiones[-1] if decisiones else None


def recoger_todas(texto_libre=True):
    """Lee los mensajes y botones nuevos de tu chat y devuelve las decisiones en orden."""
    estado = _estado()
    recibidos = _llamar("getUpdates", offset=estado.get("offset", 0), timeout=0)
    decisiones = []
    lotes = estado.get("lotes") or {}
    for r in recibidos:
        estado["offset"] = r["update_id"] + 1
        cb = r.get("callback_query")
        if cb:
            chat = ((cb.get("message") or {}).get("chat") or {}).get("id")
            if not es_mi_chat(chat):
                print(f"  boton ignorado: chat {chat} no autorizado")
                continue
            dato = cb.get("data", "")
            partes = dato.split(":")
            # "Subir asi" de una nota que salio corta: se rearma desde su guion
            if partes[0] == "subir" and len(partes) == 2 and re.fullmatch(r"[\w-]+", partes[1]):
                _llamar("answerCallbackQuery", callback_query_id=cb["id"], text="Va")
                decisiones.append({"accion": "subir", "guion": partes[1]})
                mandar("Va, la subo asi.")
                continue
            if partes[0] != "pub":
                _llamar("answerCallbackQuery", callback_query_id=cb["id"], text="Anotado")
                continue
            # pub:<lote>:<clave>. Los botones viejos (pub:n1) no traen lote: caducan.
            historia = None
            if len(partes) == 3:
                lote, clave = partes[1], partes[2]
                if clave == "nada" and lote in lotes:
                    historia = "nada"
                else:
                    historia = (lotes.get(lote) or {}).get(clave)
            if historia is None:
                _llamar("answerCallbackQuery", callback_query_id=cb["id"],
                        text="Esa lista ya caduco")
                mandar("Esa lista ya caduco. Usa los botones de la mas reciente.")
                continue
            _llamar("answerCallbackQuery", callback_query_id=cb["id"], text="Anotado")
            lote_de = partes[1]
            if historia == "nada":
                decisiones.append({"accion": "ninguna", "lote": lote_de})
            elif historia.get("tipo") in ("nota", "notavideo"):
                # opcion de una busqueda de /nota (o /notavideo): se arma desde su enlace
                accion = "nota_video" if historia["tipo"] == "notavideo" else "nota_manual"
                decisiones.append({"accion": accion, "texto": historia.get("link", "")})
                mandar(f"Va: <b>{esc(historia.get('titulo', '')[:120])}</b>")
            else:
                decisiones.append({"accion": "publicar", "historia": historia, "lote": lote_de})
                mandar(f"Va: <b>{esc(historia.get('titulo', '')[:120])}</b>")
        msg = r.get("message") or {}
        m = (msg.get("text") or "").strip()
        comando, argumento = _comando(m)
        if not texto_libre or not comando:
            continue
        chat = (msg.get("chat") or {}).get("id")
        if not es_mi_chat(chat):
            print(f"  /{comando} ignorado: chat {chat} no autorizado")
            continue
        if comando == "nota":
            decisiones.append({"accion": "nota_manual", "texto": argumento})
            if argumento:
                mandar("Recibido. Voy por esa nota.")
        elif comando == "notavideo":
            decisiones.append({"accion": "nota_video", "texto": argumento})
            if argumento:
                mandar("Recibido. Te armo el video para que lo subas tu.")
        elif comando in ("estado", "pausa", "reanudar", "saltar"):
            decisiones.append({"accion": comando, "argumento": argumento})
        else:                                   # /ayuda, /start o algo que no existe
            mandar(AYUDA)
    _guardar(estado)
    print(json.dumps(decisiones, ensure_ascii=False, indent=1) if decisiones else "sin novedades")
    return decisiones


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quien", action="store_true")
    ap.add_argument("--prueba", action="store_true")
    ap.add_argument("--candidatas", action="store_true")
    ap.add_argument("--recoger", action="store_true")
    ap.add_argument("--video", default="")
    ap.add_argument("--texto", default="")
    ap.add_argument("--nota-manual", action="store_true",
                    help="tambien escucha /nota <texto>")
    args = ap.parse_args()

    if args.quien:
        return quien()
    if args.prueba:
        mandar("<b>El Ahorita</b> · mesa de edicion conectada.\n"
               "Aqui van a llegar las historias candidatas con botones.",
               [[("Funciona", "prueba")]])
        print("mensaje de prueba enviado")
        return 0
    if args.candidatas:
        return mandar_candidatas()
    if args.video:
        m = mandar_video(args.video, args.texto)
        print("enviado · mensaje", m.get("message_id"))
        return 0
    if args.recoger:
        recoger(texto_libre=args.nota_manual)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
