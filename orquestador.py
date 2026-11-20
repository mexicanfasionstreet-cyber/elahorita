"""Orquestador: decide que hacer en cada corrida del robot (cada 5 minutos).

En cada pasada, en este orden:
  1. Telegram: botones, /nota y los comandos de control (/estado, /pausa,
     /reanudar, /saltar, /ayuda), en el orden en que los mandaste.
  2. Caso especial pendiente: si te pregunto y pasaron 30 min, publica lo mejor.
  3. Franja (05:00, 12:00, 15:00, 20:00 en Tijuana): actualiza el radar, elige
     1 o 2 notas de su ventana (ver franjas.py) y publica sola. Si hay 2+ notas
     de alto impacto, te pregunta.

/nota solo corre si cabe en el limite diario de YouTube sin quitarle su lugar
a una franja. En pausa, las franjas no salen pero /nota si. A partir de las
21:00, cuando cierra la franja de la noche (o a las 22:00), manda el resumen
del dia. Como la hora se calcula en Tijuana, el cambio de horario se
ajusta solo.

Uso:
    python orquestador.py                          # una pasada (lo que hace el cron)
    python orquestador.py --estado                 # que haria, sin ejecutar
    python orquestador.py --franja tarde           # corre esa franja ahora
    python orquestador.py --franja tarde --prueba  # video al chat, sin subir ni guardar
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402
import franjas  # noqa: E402
import telegram as bot  # noqa: E402

ESTADO = RAIZ / "datos" / "orquestador.json"
COMANDOS_VERSION = 2      # subir este numero si cambia la lista de comandos de Telegram
TZ = config.TZ


def cargar():
    try:
        estado = json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        estado = {"franjas": {}}
    return migrar(estado)


_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T(\d{2}:\d{2})")


def migrar(estado):
    """Estado del sistema anterior (candidatas por Telegram) -> formato actual.

    Antes la franja de las 12:00 se llamaba "mediodia" y cada franja guardaba la
    fecha y hora en que mando candidatas. El dia de la migracion no lleva resumen:
    corrio con el sistema anterior y el resumen diria "no se publico nada".
    """
    franjas_viejas = estado.get("franjas", {})
    if not any(_ISO.match(str(v)) for v in franjas_viejas.values()):
        return estado
    nuevas = {}
    for clave, valor in franjas_viejas.items():
        m = _ISO.match(str(valor))
        if clave.endswith("-mediodia"):
            clave = clave[:-len("mediodia")] + "manana"
        nuevas[clave] = f"candidatas (sistema anterior) {m.group(1)}" if m else valor
    estado["franjas"] = nuevas
    estado.pop("videos", None)
    estado.setdefault("resumen", f"{config.ahora():%Y-%m-%d}")
    print("  estado del sistema anterior migrado")
    return estado


def guardar(estado):
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")


def correr(comando, avisar=True):
    """Ejecuta un script del proyecto; si falla, manda el motivo al chat."""
    print(f"  $ {' '.join(str(c) for c in comando[1:])}")
    import time as _t
    inicio = _t.time()
    hecho = subprocess.run([sys.executable, *comando], cwd=RAIZ,
                           capture_output=True, text=True, errors="replace")
    print(f"  ({_t.time() - inicio:.1f} s)")
    print(hecho.stdout[-2000:])
    if hecho.returncode == 0:
        return True
    cola = ((hecho.stderr or "") + (hecho.stdout or "")).strip()[-700:]
    print(cola)
    if avisar:
        nombre = Path(comando[0]).name
        franjas.registrar_evento("fallo", f"{nombre}: {cola.strip().splitlines()[-1] if cola.strip() else ''}")
        try:
            # el traceback trae "<module>": sin escapar, Telegram rechaza el
            # mensaje y el aviso de error se perdia en silencio
            bot.mandar(f"<b>Fallo en {html.escape(nombre)}</b>\n"
                       f"<pre>{html.escape(cola[-600:])}</pre>")
        except Exception:  # noqa: BLE001
            pass
    return False


def subir_a_youtube(video, guion_path):
    """Sube el video al canal si hay credenciales. Devuelve el enlace o None.

    El guion es obligatorio: de ahi salen el titulo y las fuentes de la
    descripcion. Sin el, el Short subia como "2026 11 17 Elegida" y sin creditos.
    """
    if not (config.YT_CLIENT_ID and config.YT_CLIENT_SECRET and config.YT_REFRESH):
        return None
    # mismo valor por defecto que nota.py: si falta la variable, nunca publico
    privacidad = os.environ.get("YT_PRIVACIDAD", "private") or "private"
    print(f"  subiendo a YouTube ({privacidad})")
    hecho = subprocess.run(
        [sys.executable, str(RAIZ / "publicar.py"), "--video", str(video),
         "--guion", str(guion_path), "--privacidad", privacidad],
        cwd=RAIZ, capture_output=True, text=True, errors="replace")
    print(hecho.stdout[-1500:])
    if hecho.returncode != 0:
        franjas.registrar_evento("youtube", (hecho.stderr or hecho.stdout)[-200:])
        bot.mandar(f"<b>No se pudo subir a YouTube</b>\n<pre>"
                   f"{html.escape((hecho.stderr or hecho.stdout)[-500:])}</pre>")
        return None
    for linea in (hecho.stdout or "").splitlines():
        if "youtube.com/shorts/" in linea:
            return linea.split()[-1]
    return None


def armar_video(links=(), previos=(), nombre="elegida", pie="El Ahorita",
                origen="elegida", prueba=False, reservas=(), ya_salio=None):
    """Guion -> voz -> video -> YouTube -> chat para 1 o 2 historias del ranking.

    Devuelve True si el video quedo hecho (y subido, salvo en prueba).
    """
    links = [lk for lk in links if lk]
    # sin enlace, guion.py entra en modo automatico y publicaria otra historia
    if not links:
        bot.mandar("No encontre la historia de ese boton. Usa la lista mas reciente.")
        return False

    # la ruta del guion la decide el orquestador y se la pasa a guion.py: asi los
    # dos usan el mismo nombre aunque cambie el dia en UTC
    sello = config.ahora().strftime("%Y-%m-%d")
    carpeta = RAIZ / ("build" if prueba else "docs/guiones")
    destino = carpeta / f"{sello}-{nombre}.json"
    comando = [str(RAIZ / "guion.py"), "--franja", nombre, "--json", str(destino)]
    for i, link in enumerate(links):
        comando += ["--link", link, "--previo", previos[i] if i < len(previos) else ""]
    for link in reservas:
        comando += ["--reserva", link]
    if not correr(comando):
        return False
    if not correr([str(RAIZ / "voz.py"), "--guion", str(destino)]):
        return False
    if not correr([str(RAIZ / "capsula.py"), "--guion", str(destino)]):
        return False
    video = RAIZ / "docs" / "videos" / f"{destino.stem}.mp4"
    if not video.exists():
        return False
    if prueba:
        _mandar_video_o_enlace(video, pie + "\n(prueba: no se sube a YouTube)")
        return True
    if ya_salio and ya_salio():
        return "ya"
    enlace = subir_a_youtube(video, destino)
    if enlace:
        pie += f"\n{enlace}"
        datos = json.loads(destino.read_text(encoding="utf-8"))
        franjas.registrar_publicada(datos.get("historias", []), origen, enlace)
    # si Telegram falla aqui, el video YA esta en YouTube: no se puede tumbar la
    # corrida, o la franja quedaria abierta y se subiria otra vez
    _mandar_video_o_enlace(video, pie)
    return bool(enlace) or not (config.YT_CLIENT_ID and config.YT_REFRESH)


def _mandar_video_o_enlace(video, pie):
    try:
        bot.mandar_video(video, pie)
    except Exception as e:  # noqa: BLE001
        print(f"  aviso: Telegram no acepto el video ({type(e).__name__}: {e}); va el texto")
        try:
            bot.mandar(bot.esc(pie) + "\n(el video no se pudo mandar al chat)")
        except Exception:  # noqa: BLE001
            pass


def nota_a_mano(texto, estado):
    """/nota: solo si cabe en el limite diario sin quitarle lugar a una franja."""
    cupo = franjas.cupo_para_nota(estado)
    if cupo <= 0:
        bot.mandar(f"Hoy ya no cabe otra subida: {franjas.subidas_hoy()} hechas y "
                   f"{franjas.franjas_restantes(estado, config.ahora())} franja(s) por salir "
                   f"(limite {franjas.LIMITE_SUBIDAS} al dia).\n"
                   "Si la quieres igual, /notavideo te manda el video para subirlo tu.")
        return False
    return correr([str(RAIZ / "nota.py"), texto])


def nota_en_video(texto):
    """/notavideo: arma la nota y manda el video al chat. No sube ni gasta cupo."""
    return correr([str(RAIZ / "nota.py"), texto, "--solo-video"])


def guardar_offset():
    """Sube el estado de Telegram al repositorio de inmediato.

    Si se deja para el final del run, otro run puede arrancar antes de que se
    guarde y volver a leer el mismo mensaje: de ahi salian los videos repetidos.
    """
    try:
        subprocess.run(["git", "add", "datos/telegram.json"], cwd=RAIZ,
                       capture_output=True, timeout=60)
        hecho = subprocess.run(["git", "commit", "-m", "telegram: mensajes leidos"],
                               cwd=RAIZ, capture_output=True, text=True, timeout=60)
        if hecho.returncode != 0:
            return
        for _ in range(3):
            empuje = subprocess.run(["git", "push"], cwd=RAIZ,
                                    capture_output=True, timeout=120)
            if empuje.returncode == 0:
                print("  offset guardado en el repo")
                return
            subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=RAIZ,
                           capture_output=True, timeout=120)
    except Exception as e:  # noqa: BLE001
        print(f"  aviso: no se pudo guardar el offset ({type(e).__name__})")


def atender_telegram(estado):
    """Atiende todo lo que mandaste desde la pasada anterior, en orden.

    Devuelve True si armo (o intento armar) algun video: entonces esa pasada no
    corre ademas la franja.
    """
    decisiones = bot.recoger_todas(texto_libre=True)
    if decisiones:
        guardar_offset()
    hubo = False
    for d in decisiones:
        hubo = atender(estado, d) or hubo
    return hubo


def atender(estado, decision):
    """Una decision tuya. True si fue un video (publicar, /nota, /notavideo, subir)."""
    accion = decision["accion"]
    ahora = config.ahora()
    if accion in CONTROL:
        CONTROL[accion](estado, decision.get("argumento", ""), ahora)
        guardar(estado)
        return False
    pendiente = estado.get("pendiente") or {}
    de_pendiente = bool(pendiente) and decision.get("lote") == pendiente.get("lote")

    if accion == "publicar":
        historia = decision.get("historia") or {}
        print(f"  elegiste: {historia.get('titulo', '')[:70]}")
        if de_pendiente:
            return resolver_pendiente(estado, [historia], "elegiste")
        return armar_video([historia.get("link", "")], [historia.get("seguimiento_de", "")],
                           pie="El Ahorita · la nota que elegiste")
    if accion == "ninguna" and de_pendiente:
        print(f"  ninguna: se salta la franja {pendiente['clave']}")
        cerrar_franja(estado, pendiente["clave"], "saltada")
        bot.mandar("Va, esta franja no sale.")
        return False
    if accion == "nota_manual":
        texto = decision.get("texto", "")
        if not texto:
            bot.mandar("Escribe el tema o el enlace despues de /nota")
            return False
        print(f"  nota a mano: {texto[:70]}")
        return nota_a_mano(texto, estado)
    if accion == "nota_video":
        texto = decision.get("texto", "")
        if not texto:
            bot.mandar("Escribe el tema o el enlace despues de /notavideo")
            return False
        print(f"  nota solo en video: {texto[:70]}")
        return nota_en_video(texto)
    if accion == "subir":
        print(f"  subir nota corta: {decision['guion']}")
        if franjas.cupo_para_nota(estado) <= 0:
            bot.mandar("Hoy ya no cabe otra subida sin quitarle lugar a una franja.")
            return False
        return correr([str(RAIZ / "nota.py"), "--subir", decision["guion"]])
    print("  ninguna: no se publica")
    return False


# ------------------------------------------------------------------ control por Telegram
DIAS = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
NOMBRE_FRANJA = {"madrugada": "madrugada", "manana": "mañana", "tarde": "tarde", "noche": "noche"}


def _cuando(dt):
    return f"{DIAS[dt.weekday()]} {dt.day} {dt:%H:%M}"


def en_pausa(estado, ahora):
    """(True, hasta) si las franjas estan en pausa; hasta=None es "hasta /reanudar"."""
    pausa = estado.get("pausa")
    if not pausa:
        return False, None
    hasta = datetime.fromisoformat(pausa["hasta"]) if pausa.get("hasta") else None
    if hasta and ahora >= hasta:
        estado.pop("pausa", None)
        bot.mandar("Se acabo la pausa: las franjas vuelven a salir solas.")
        guardar(estado)
        return False, None
    return True, hasta


def pausar(estado, argumento, ahora):
    """/pausa, /pausa 3h, /pausa 2d, /pausa hoy, /pausa manana."""
    arg = argumento.lower().replace("ñ", "n").strip()
    fin_del_dia = ahora.replace(hour=23, minute=59, second=0, microsecond=0)
    m = re.fullmatch(r"(\d{1,3})\s*(h|hr|hrs|horas?|d|dias?)", arg)
    if not arg:
        hasta = None
    elif arg == "hoy":
        hasta = fin_del_dia
    elif arg == "manana":
        hasta = fin_del_dia + timedelta(days=1)
    elif m:
        n = int(m.group(1))
        hasta = ahora + (timedelta(hours=n) if m.group(2).startswith("h") else timedelta(days=n))
    else:
        bot.mandar("No entendi la pausa. Usa: /pausa · /pausa 3h · /pausa 2d · /pausa hoy · /pausa manana")
        return
    estado["pausa"] = {"desde": ahora.isoformat(timespec="seconds"),
                       "hasta": hasta.isoformat(timespec="seconds") if hasta else None}
    franjas.registrar_evento("pausa", f"hasta {_cuando(hasta)}" if hasta else "hasta /reanudar")
    bot.mandar("⏸ <b>Franjas en pausa</b> "
               + (f"hasta el {_cuando(hasta)}" if hasta else "hasta que mandes /reanudar")
               + ".\n/nota sigue funcionando.")


def reanudar(estado, argumento, ahora):
    if not estado.pop("pausa", None):
        bot.mandar("No habia pausa: las franjas ya salen solas.")
        return
    franjas.registrar_evento("pausa", "reanudada")
    dia, franja = proxima_franja(estado, ahora)
    bot.mandar("▶️ Listo, las franjas vuelven a salir solas."
               + (f" Sigue la de la {NOMBRE_FRANJA[franja[1]]} ({DIAS[dia.weekday()]} "
                  f"{franja[0]:02d}:00)." if franja else ""))


def proxima_franja(estado, ahora, nombre=""):
    """(dia, franja) de la proxima franja que no ha salido (hoy o manana)."""
    hechas = estado.get("franjas", {})
    esperando = (estado.get("pendiente") or {}).get("clave")
    for delta in (0, 1):
        dia = ahora + timedelta(days=delta)
        for f in franjas.FRANJAS:
            if nombre and f[1] != nombre:
                continue
            if not nombre and f"{dia:%Y-%m-%d}-{f[1]}" == esperando:
                continue                          # esa ya te pregunto: no es "la proxima"
            if delta == 0 and ahora.hour >= f[0] + franjas.MARGEN_FRANJA:
                continue                          # su ventana ya paso
            if not hechas.get(f"{dia:%Y-%m-%d}-{f[1]}"):
                return dia, f
    return None, None


def saltar(estado, argumento, ahora):
    """/saltar (la proxima) o /saltar noche."""
    nombre = argumento.lower().replace("ñ", "n").strip()
    if nombre and nombre not in NOMBRE_FRANJA:
        bot.mandar("¿Cual? /saltar madrugada · manana · tarde · noche (o solo /saltar)")
        return
    dia, franja = proxima_franja(estado, ahora, nombre)
    if not franja:
        bot.mandar("No hay franja pendiente que saltar.")
        return
    clave = f"{dia:%Y-%m-%d}-{franja[1]}"
    if (estado.get("pendiente") or {}).get("clave") == clave:
        estado.pop("pendiente", None)
    estado.setdefault("franjas", {})[clave] = f"saltada (/saltar) {ahora:%H:%M}"
    franjas.registrar_evento("saltada", NOMBRE_FRANJA[franja[1]])
    bot.mandar(f"⏭ Va, la franja de la {NOMBRE_FRANJA[franja[1]]} del "
               f"{DIAS[dia.weekday()]} {dia.day} no sale.")


ICONOS = [("candidatas", "📋"), ("automatica", "✅"), ("elegiste", "✅"), ("sin respuesta (solo", "⏭"),
          ("sin respuesta", "✅"), ("saltada", "⏭"), ("pausada", "⏸"), ("fallida", "❌"),
          ("sin noticias", "➖")]


def _estado_franja(texto):
    for prefijo, icono in ICONOS:
        if texto.startswith(prefijo):
            return f"{icono} {texto}"
    return texto


def _linea_franjas(estado, dia, ahora):
    hechas = estado.get("franjas", {})
    pendiente = estado.get("pendiente") or {}
    partes = []
    for hora, nombre, _ in franjas.FRANJAS:
        clave = f"{dia:%Y-%m-%d}-{nombre}"
        if hechas.get(clave):
            como = _estado_franja(hechas[clave])
        elif pendiente.get("clave") == clave:
            como = "⏳ esperando tu eleccion"
        elif ahora.hour < hora:
            como = f"a las {hora:02d}:00"
        elif ahora.hour < hora + franjas.MARGEN_FRANJA:
            como = "en curso"
        else:
            como = "no corrio"
        partes.append(f"  {NOMBRE_FRANJA[nombre]}: {como}")
    return "\n".join(partes)


def voicebox_responde():
    if not (config.VOICEBOX_URL and config.VOICEBOX_PROFILE):
        return "sin configurar (voz de respaldo)"
    import urllib.request
    try:
        with urllib.request.urlopen(f"{config.VOICEBOX_URL}/health", timeout=5):
            return "responde ✅"
    except Exception:  # noqa: BLE001
        return "no responde ❌ (sale la voz de respaldo)"


def mostrar_estado(estado, argumento, ahora):
    """/estado"""
    pausa, hasta = en_pausa(estado, ahora)
    dia, franja = proxima_franja(estado, ahora)
    pendiente = estado.get("pendiente")
    lineas = [f"<b>El Ahorita · estado</b> ({_cuando(ahora)})"]
    if pausa:
        lineas.append("⏸ <b>En pausa</b> " + (f"hasta el {_cuando(hasta)}" if hasta else "hasta /reanudar"))
    lineas.append("Hoy:\n" + _linea_franjas(estado, ahora, ahora))
    if pendiente:
        limite = datetime.fromisoformat(pendiente["publica_a"])
        lineas.append(f"⏳ Esperando tu eleccion para la {NOMBRE_FRANJA.get(pendiente['nombre'], '')} "
                      f"hasta las {limite:%H:%M}.")
    if franja:
        lineas.append(f"Proxima: {NOMBRE_FRANJA[franja[1]]}, {DIAS[dia.weekday()]} {dia.day} "
                      f"a las {franja[0]:02d}:00" + (" (en pausa)" if pausa else ""))
    lineas.append(f"Subidas hoy: {franjas.subidas_hoy(ahora)} de {franjas.LIMITE_SUBIDAS} · "
                  f"caben {max(franjas.cupo_para_nota(estado, ahora), 0)} /nota")
    lineas.append(f"Voicebox: {voicebox_responde()}")
    bot.mandar("\n".join(lineas))


def mostrar_ayuda(estado, argumento, ahora):
    bot.mandar(bot.AYUDA)


CONTROL = {"estado": mostrar_estado, "pausa": pausar, "reanudar": reanudar,
           "saltar": saltar, "ayuda": mostrar_ayuda}


# ------------------------------------------------------------------ resumen diario
EVENTOS_TEXTO = {
    "voz_respaldo": "Voicebox no respondio: salio con la voz de respaldo",
    "subtitulos": "subtitulos incompletos",
    "fallo": "fallo",
    "youtube": "no se pudo subir a YouTube",
    "franja_fallida": "no salio la franja",
    "nota_corta": "nota corta sin subir",
    "nota_video": "video para subir a mano",
    "saltada": "saltaste la franja",
    "pausa": "pausa",
}
HORA_RESUMEN = 21


def resumen_diario(estado, ahora, forzar=False):
    """A partir de las 21:00, cuando la franja de la noche ya cerro (o a las 22:00)."""
    hoy = f"{ahora:%Y-%m-%d}"
    if not forzar:
        if estado.get("resumen") == hoy or ahora.hour < HORA_RESUMEN:
            return False
        noche_cerrada = bool(estado.get("franjas", {}).get(f"{hoy}-noche"))
        if not noche_cerrada and ahora.hour < HORA_RESUMEN + 1:
            return False
    publicadas = franjas.publicadas_de(ahora)
    eventos = franjas.eventos_de(ahora)
    lineas = [f"<b>El Ahorita · resumen del {_cuando(ahora)[:-6]}</b>"]
    if publicadas:
        lineas.append(f"\nPublicado ({len(publicadas)}):")
        for p in publicadas:
            hora = str(p.get("cuando", ""))[11:16]
            origen = p.get("origen", "").replace("franja-", "")
            origen = NOMBRE_FRANJA.get(origen, origen)
            lineas.append(f"• {hora} {html.escape(origen)} · {html.escape(p.get('titulo', '')[:90])}"
                          + (f"\n  {html.escape(p['video'])}" if p.get("video") else ""))
    else:
        lineas.append("\nHoy no se publico nada.")
    lineas.append("\nFranjas:\n" + _linea_franjas(estado, ahora, ahora))
    if eventos:
        lineas.append(f"\nAvisos ({len(eventos)}):")
        for e in eventos[-8:]:
            lineas.append(f"• {e['hora']} {html.escape(EVENTOS_TEXTO.get(e['tipo'], e['tipo']))}"
                          + (f": {html.escape(e['texto'][:90])}" if e.get("texto") else ""))
    lineas.append(f"\nSubidas: {franjas.subidas_hoy(ahora)} de {franjas.LIMITE_SUBIDAS}")
    pausa, hasta = en_pausa(estado, ahora)
    if pausa:
        lineas.append("⏸ En pausa " + (f"hasta el {_cuando(hasta)}" if hasta else "hasta /reanudar"))
    else:
        dia, franja = proxima_franja(estado, ahora)
        if franja:
            lineas.append(f"Sigue: {NOMBRE_FRANJA[franja[1]]}, {DIAS[dia.weekday()]} {dia.day} "
                          f"a las {franja[0]:02d}:00")
    bot.mandar("\n".join(lineas))
    estado["resumen"] = hoy
    guardar(estado)
    return True


# ------------------------------------------------------------------ franjas
def franja_cerrada_afuera(clave):
    """True si otra corrida ya publico esta franja (estado en el remoto).

    Candado contra duplicados: armar el video tarda varios minutos y otra
    corrida pudo publicar la misma franja mientras tanto. Sin red o sin git,
    False (se sigue como siempre).
    """
    rama = os.environ.get("GITHUB_REF_NAME") or "main"
    try:
        subprocess.run(["git", "fetch", "-q", "origin", rama], cwd=RAIZ, check=True,
                       capture_output=True, timeout=60)
        crudo = subprocess.run(["git", "show", f"FETCH_HEAD:datos/{ESTADO.name}"], cwd=RAIZ,
                               check=True, capture_output=True, timeout=30).stdout
        return clave in (json.loads(crudo).get("franjas") or {})
    except Exception as e:  # noqa: BLE001
        print(f"  aviso: no pude revisar el estado remoto ({type(e).__name__})")
        return False


def cerrar_franja(estado, clave, como):
    estado.setdefault("franjas", {})[clave] = f"{como} {config.ahora():%H:%M}"
    estado.pop("pendiente", None)
    estado.get("intentos", {}).pop(clave, None)
    guardar(estado)


def publicar_franja(estado, clave, nombre, historias, como, reservas=()):
    """Arma y sube el video de la franja; si falla, se reintenta en la proxima pasada."""
    if franja_cerrada_afuera(clave):
        print(f"  {clave}: otra corrida ya la publico; no se repite")
        cerrar_franja(estado, clave, "ya publicada")
        return True
    previos = [h.get("seguimiento_de", "") for h in historias]
    etiqueta = {"madrugada": "la noche y la madrugada", "manana": "la manana",
                "tarde": "la tarde", "noche": "el cierre del dia"}.get(nombre, nombre)
    ok = armar_video([h["link"] for h in historias], previos, nombre=nombre,
                     pie=f"El Ahorita · {etiqueta}", origen=f"franja-{nombre}",
                     reservas=reservas, ya_salio=lambda: franja_cerrada_afuera(clave))
    if ok == "ya":
        print(f"  {clave}: otra corrida la publico mientras se armaba; no se sube")
        cerrar_franja(estado, clave, "ya publicada")
        return True
    if ok:
        cerrar_franja(estado, clave, como)
        return True
    intentos = estado.setdefault("intentos", {})
    intentos[clave] = intentos.get(clave, 0) + 1
    if intentos[clave] >= 2:
        franjas.registrar_evento("franja_fallida", nombre)
        bot.mandar(f"<b>La franja {html.escape(nombre)} no salio</b> tras 2 intentos. "
                   "Revisa los avisos de arriba.")
        cerrar_franja(estado, clave, "fallida")
    else:
        guardar(estado)
    return False


def resolver_pendiente(estado, historias, como):
    p = estado["pendiente"]
    return publicar_franja(estado, p["clave"], p["nombre"], historias, como)


def revisar_pendiente(estado, ahora):
    """Caso especial sin respuesta: pasado el plazo se publica lo mejor."""
    p = estado.get("pendiente")
    if not p:
        return False
    limite = datetime.fromisoformat(p["publica_a"])
    if ahora < limite:
        print(f"  esperando tu eleccion para {p['nombre']} hasta {limite:%H:%M}")
        return False
    elegidas = p.get("sin_respuesta")
    if elegidas is None:                     # pendientes de antes de este cambio
        elegidas = franjas.elegir([o for o in p["opciones"] if not o.get("sensible")])
    if not elegidas:
        bot.mandar(f"No elegiste en {franjas.ESPERA_MIN} min y todas las opciones eran de tema "
                   "sensible: esta franja no sale.")
        cerrar_franja(estado, p["clave"], "sin respuesta (solo sensibles)")
        return True
    bot.mandar(f"No elegiste en {franjas.ESPERA_MIN} min: publico "
               f"<b>{html.escape(elegidas[0]['titulo'][:100])}</b>"
               + (" y la segunda" if len(elegidas) > 1 else "") + ".")
    return publicar_franja(estado, p["clave"], p["nombre"], elegidas, "sin respuesta")


def preguntar(estado, clave, nombre, opciones, ahora, sin_respuesta, motivo="especial"):
    """Lista con botones y plazo. `sin_respuesta` es lo que sale si no contestas.

    motivo "especial": 2+ notas de alto impacto. "sensible": la elegida es de un
    tema que no sale solo (suicidio, violencia sexual o menores, violencia grafica).
    """
    import secciones
    lote = bot.guardar_lote(opciones)
    publica_a = ahora + timedelta(minutes=franjas.ESPERA_MIN)
    if motivo == "sensible":
        cabeza = "la nota elegida es de <b>tema sensible</b>. ¿La publico?"
    else:
        cabeza = f"hay {len(opciones)} notas de alto impacto. ¿Cual sale?"
    lineas = [f"<b>El Ahorita · {html.escape(nombre)}</b>: {cabeza}\n"]
    for i, o in enumerate(opciones, 1):
        seg = f"\n   seguimiento de: {html.escape(o['seguimiento_de'][:80])}" if o["seguimiento_de"] else ""
        sens = (f"\n   ⚠️ sensible: {secciones.NOMBRES_SENSIBLES.get(o['sensible'], o['sensible'])}"
                if o.get("sensible") else "")
        lineas.append(f"<b>{i}.</b> {html.escape(o['titulo'][:140])}\n"
                      f"   {o['medios']} medios · peso {o['peso']}{seg}{sens}")
    if sin_respuesta:
        lineas.append(f"\nSi no eliges, a las {publica_a:%H:%M} publico "
                      f"<b>{html.escape(sin_respuesta[0]['titulo'][:90])}</b>"
                      + (" y la segunda no sensible" if len(sin_respuesta) > 1 else "") + ".")
    else:
        lineas.append(f"\nSi no eliges, a las {publica_a:%H:%M} esta franja no sale "
                      "(no hay opcion sin tema sensible).")
    botones = [[(f"Publicar {i}", f"pub:{lote}:n{i}")] for i in range(1, len(opciones) + 1)]
    botones.append([("Ninguna (saltar franja)", f"pub:{lote}:nada")])
    bot.mandar("\n".join(lineas), botones)
    estado["pendiente"] = {"clave": clave, "nombre": nombre, "lote": lote, "motivo": motivo,
                           "publica_a": publica_a.isoformat(timespec="seconds"),
                           "opciones": opciones, "sin_respuesta": sin_respuesta}
    guardar(estado)


def correr_franja(estado, clave, franja, ahora, prueba=False):
    """Toca franja: radar, seleccion y publicacion (o pregunta si es caso especial)."""
    nombre = franja[1]
    if not correr([str(RAIZ / "aggregate.py"), "--days", "2"]):
        print("  fallo el radar; se reintenta en la proxima pasada")
        return False
    ruta = RAIZ / "docs" / "data" / "latest.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    # las que pueden publicarse se revisan con IA: seccion y region (la etiqueta
    # del video) mas finas que las del clasificador por palabras
    import secciones
    cambios = secciones.refinar(datos["items"])
    print(f"  secciones revisadas con IA: {cambios} cambio(s)")
    if cambios:
        ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    filas = franjas.candidatas(datos["items"], franja, ahora)
    print(f"  {len(filas)} historias desde {franjas.inicio_ventana(franja, ahora):%d %H:%M}")
    for f in filas[:4]:
        print(f"   {f['score']:>5} peso {f['peso_cobertura']:>5} · {f['title'][:70]}")
    if not filas:
        bot.mandar(f"El Ahorita · {nombre}: no hay historias nuevas en la ventana; no sale video.")
        if not prueba:
            cerrar_franja(estado, clave, "sin noticias")
        return True
    resumenes = [franjas.resumen(f) for f in filas]
    opciones = resumenes[:3]
    elegidas = franjas.elegir(opciones)
    seguras = franjas.no_sensibles(resumenes)          # lo que sale si no contestas
    # de repuesto, por si ninguna elegida se deja leer (nunca una sensible)
    usados = {o["link"] for o in elegidas}
    reservas = [o["link"] for o in resumenes if o["link"] not in usados and not o["sensible"]][:2]
    especial = franjas.es_especial(filas)
    sensibles = [o for o in elegidas if o["sensible"]]
    if prueba:
        aviso = (" (en serio: CASO ESPECIAL, te preguntaria)" if especial else
                 " (en serio: TEMA SENSIBLE, te preguntaria; sin respuesta saldria otra)" if sensibles
                 else "")
        return armar_video([o["link"] for o in elegidas], [o["seguimiento_de"] for o in elegidas],
                           nombre=f"prueba-{nombre}", prueba=True, reservas=reservas,
                           pie=f"El Ahorita · prueba de la franja {nombre}{aviso}")
    if especial:
        print("  caso especial: se pregunta")
        preguntar(estado, clave, nombre, opciones, ahora, seguras, "especial")
        return True
    if sensibles:
        print(f"  tema sensible ({sensibles[0]['sensible']}): se pregunta")
        # la sensible y, como alternativa, lo que saldria si no contestas
        alternativas = [o for o in seguras if o["link"] not in usados][:2]
        preguntar(estado, clave, nombre, elegidas + alternativas, ahora, seguras, "sensible")
        return True
    return publicar_franja(estado, clave, nombre, elegidas, "automatica", reservas)


def franja_pendiente(estado, ahora):
    """La franja que toca ahora, si no ha salido ni esta esperando respuesta."""
    franja = franjas.franja_actual(ahora)
    if not franja:
        return None, None
    clave = f"{ahora:%Y-%m-%d}-{franja[1]}"
    if estado.get("franjas", {}).get(clave):
        return None, None
    if (estado.get("pendiente") or {}).get("clave") == clave:
        return None, None
    return clave, franja


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--estado", action="store_true")
    ap.add_argument("--franja", default="",
                    help="correr esta franja ahora (madrugada, manana, tarde, noche)")
    ap.add_argument("--prueba", action="store_true",
                    help="con --franja: arma el video y lo manda al chat, sin subir ni guardar")
    ap.add_argument("--mostrar", choices=["estado", "resumen", "ayuda"],
                    help="manda al chat ese mensaje ahora, sin cambiar nada")
    args = ap.parse_args()

    ahora = config.ahora()
    estado = cargar()
    clave, franja = franja_pendiente(estado, ahora)
    print(f"{ahora:%Y-%m-%d %H:%M} Tijuana · franja pendiente: "
          f"{franja[1] if franja else 'ninguna'}")

    if args.estado:
        print(json.dumps(estado, ensure_ascii=False, indent=1))
        return 0

    if args.mostrar:
        if args.mostrar == "resumen":
            resumen_diario(dict(estado), ahora, forzar=True)   # copia: no marca el dia
        else:
            CONTROL[args.mostrar](estado, "", ahora)
        return 0

    if args.franja:
        forzada = franjas.franja_por_nombre(args.franja)
        print(f"forzando franja {forzada[1]}" + (" (prueba)" if args.prueba else ""))
        ok = correr_franja(estado, f"{ahora:%Y-%m-%d}-{forzada[1]}", forzada, ahora,
                           prueba=args.prueba)
        return 0 if ok else 1

    if estado.get("comandos") != COMANDOS_VERSION:
        try:
            bot.registrar_comandos()          # el menu "/" del chat
            estado["comandos"] = COMANDOS_VERSION
            guardar(estado)
        except BaseException as e:  # noqa: BLE001
            print(f"  aviso: no se registraron los comandos ({e})")

    hubo = atender_telegram(estado)
    pausa, _ = en_pausa(estado, ahora)
    if not hubo and estado.get("pendiente"):
        if pausa:
            p = estado["pendiente"]
            print(f"  en pausa: la franja {p['nombre']} que esperaba respuesta no sale")
            cerrar_franja(estado, p["clave"], "pausada")
        else:
            hubo = revisar_pendiente(estado, ahora)
    clave, franja = franja_pendiente(estado, ahora)
    if not hubo and franja:
        if pausa:
            print(f"  en pausa: la franja {franja[1]} no sale")
            cerrar_franja(estado, clave, "pausada")
        else:
            print(f"corriendo la franja {franja[1]}")
            hubo = correr_franja(estado, clave, franja, ahora)
    resumen_diario(estado, config.ahora())
    if not hubo:
        print("sin novedades")
    return 0


if __name__ == "__main__":
    sys.exit(main())
