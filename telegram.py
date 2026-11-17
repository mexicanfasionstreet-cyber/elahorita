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
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402

ESTADO = RAIZ / "datos" / "telegram.json"
API = "https://api.telegram.org/bot{token}/{metodo}"


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
    return {"pendientes": {}, "offset": 0, "elegidas": []}


def _guardar(datos):
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ envio
def mandar(texto, botones=None):
    """Manda un mensaje; `botones` es [[(etiqueta, dato), ...], ...]."""
    params = {"chat_id": config.TELEGRAM_CHAT, "text": texto,
              "parse_mode": "HTML", "disable_web_page_preview": "true"}
    if botones:
        params["reply_markup"] = json.dumps({"inline_keyboard": [
            [{"text": t, "callback_data": d} for t, d in fila] for fila in botones]})
    return _llamar("sendMessage", **params)


def mandar_video(ruta, texto=""):
    """Sube el mp4 al chat (limite de Telegram para bots: 50 MB)."""
    import uuid
    ruta = Path(ruta)
    if not ruta.exists():
        raise SystemExit(f"no existe {ruta}")
    frontera = "----elahorita" + uuid.uuid4().hex
    trozos = []

    def campo(nombre, valor):
        trozos.append((f"--{frontera}\r\nContent-Disposition: form-data; "
                       f"name=\"{nombre}\"\r\n\r\n{valor}\r\n").encode("utf-8"))

    campo("chat_id", config.TELEGRAM_CHAT)
    if texto:
        campo("caption", texto[:900])
    campo("supports_streaming", "true")
    trozos.append((f"--{frontera}\r\nContent-Disposition: form-data; name=\"video\"; "
                   f"filename=\"{ruta.name}\"\r\nContent-Type: video/mp4\r\n\r\n").encode("utf-8"))
    trozos.append(ruta.read_bytes())
    trozos.append(f"\r\n--{frontera}--\r\n".encode("utf-8"))
    req = urllib.request.Request(
        API.format(token=config.TELEGRAM_TOKEN, metodo="sendVideo"), data=b"".join(trozos),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={frontera}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        respuesta = json.load(r)
    if not respuesta.get("ok"):
        raise SystemExit(f"Telegram: {respuesta}")
    return respuesta["result"]


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


def mandar_candidatas(n=3):
    estado = _estado()
    estado["pendientes"] = {}
    filas, texto = [], [f"<b>El Ahorita</b> · {datetime.now():%H:%M}\n"]
    for i, f in enumerate(candidatas(n), 1):
        clave = f"n{i}"
        estado["pendientes"][clave] = {
            "titulo": f["title"], "link": f["link"], "seccion": f["seccion"],
            "score": f["score"], "medios": f["medios"], "imagen": f["imagen"],
        }
        texto.append(f"<b>{i}. [{f['seccion'].upper()}]</b> {f['title'][:150]}\n"
                     f"   {f['medios']} medios · score {f['score']} · "
                     f"{f['horas']} h" + (" · con foto" if f["imagen"] else " · sin foto"))
        filas.append([(f"Publicar {i}", f"pub:{clave}")])
    filas.append([("Ninguna hoy", "pub:nada")])
    _guardar(estado)
    mandar("\n".join(texto), filas)
    print("mandadas", len(estado["pendientes"]), "candidatas")


def recoger(texto_libre=False):
    """Lee las respuestas nuevas y devuelve la decision."""
    estado = _estado()
    recibidos = _llamar("getUpdates", offset=estado.get("offset", 0), timeout=0)
    decision = None
    for r in recibidos:
        estado["offset"] = r["update_id"] + 1
        cb = r.get("callback_query")
        if cb:
            dato = cb.get("data", "")
            _llamar("answerCallbackQuery", callback_query_id=cb["id"],
                    text="Anotado")
            if dato.startswith("pub:"):
                clave = dato.split(":", 1)[1]
                if clave == "nada":
                    decision = {"accion": "ninguna"}
                else:
                    historia = estado["pendientes"].get(clave, {})
                    decision = {"accion": "publicar", "historia": historia}
                    mandar(f"Va: <b>{historia.get('titulo', '')[:120]}</b>")
        msg = r.get("message") or {}
        m = (msg.get("text") or "").strip()
        if texto_libre and m.startswith("/nota"):
            decision = {"accion": "nota_manual", "texto": m[5:].strip()}
            mandar("Recibido. Voy por esa nota.")
    _guardar(estado)
    if decision:
        print(json.dumps(decision, ensure_ascii=False, indent=1))
    else:
        print("sin novedades")
    return decision


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
               [[("Funciona", "pub:prueba")]])
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
