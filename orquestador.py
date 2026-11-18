"""Orquestador: decide que hacer en cada corrida del robot (cada 5 minutos).

En cada pasada, en este orden:
  1. Telegram: si tocaste un boton o escribiste /nota, lo atiende.
  2. Caso especial pendiente: si te pregunto y pasaron 30 min, publica lo mejor.
  3. Franja (05:00, 12:00, 15:00, 20:00 en Tijuana): actualiza el radar, elige
     1 o 2 notas de su ventana (ver franjas.py) y publica sola. Si hay 2+ notas
     de alto impacto, te pregunta.

/nota solo corre si cabe en el limite diario de YouTube sin quitarle su lugar
a una franja. Como la hora se calcula en Tijuana, el cambio de horario se
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
TZ = config.TZ


def cargar():
    if ESTADO.exists():
        try:
            return json.loads(ESTADO.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"franjas": {}, "videos": []}


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
        bot.mandar(f"<b>No se pudo subir a YouTube</b>\n<pre>"
                   f"{html.escape((hecho.stderr or hecho.stdout)[-500:])}</pre>")
        return None
    for linea in (hecho.stdout or "").splitlines():
        if "youtube.com/shorts/" in linea:
            return linea.split()[-1]
    return None


def armar_video(links=(), previos=(), nombre="elegida", pie="El Ahorita",
                origen="elegida", prueba=False, reservas=()):
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
        bot.mandar_video(video, pie + "\n(prueba: no se sube a YouTube)")
        return True
    enlace = subir_a_youtube(video, destino)
    if enlace:
        pie += f"\n{enlace}"
        datos = json.loads(destino.read_text(encoding="utf-8"))
        franjas.registrar_publicada(datos.get("historias", []), origen, enlace)
    bot.mandar_video(video, pie)
    return bool(enlace) or not (config.YT_CLIENT_ID and config.YT_REFRESH)


def nota_a_mano(texto, estado):
    """/nota: solo si cabe en el limite diario sin quitarle lugar a una franja."""
    cupo = franjas.cupo_para_nota(estado)
    if cupo <= 0:
        bot.mandar(f"Hoy ya no cabe otra subida: {franjas.subidas_hoy()} hechas y "
                   f"{franjas.franjas_restantes(estado, config.ahora())} franja(s) por salir "
                   f"(limite {franjas.LIMITE_SUBIDAS} al dia).")
        return False
    return correr([str(RAIZ / "nota.py"), texto])


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
    """Lee lo que hayas mandado y actua. Devuelve True si hizo algo."""
    decision = bot.recoger(texto_libre=True)
    if decision:
        guardar_offset()
    if not decision:
        return False
    pendiente = estado.get("pendiente") or {}
    de_pendiente = bool(pendiente) and decision.get("lote") == pendiente.get("lote")

    if decision["accion"] == "publicar":
        historia = decision.get("historia") or {}
        print(f"  elegiste: {historia.get('titulo', '')[:70]}")
        if de_pendiente:
            return resolver_pendiente(estado, [historia], "elegiste")
        return armar_video([historia.get("link", "")], [historia.get("seguimiento_de", "")],
                           pie="El Ahorita · la nota que elegiste")
    if decision["accion"] == "ninguna" and de_pendiente:
        print(f"  ninguna: se salta la franja {pendiente['clave']}")
        cerrar_franja(estado, pendiente["clave"], "saltada")
        bot.mandar("Va, esta franja no sale.")
        return True
    if decision["accion"] == "nota_manual":
        texto = decision.get("texto", "")
        if not texto:
            bot.mandar("Escribe el tema o el enlace despues de /nota")
            return False
        print(f"  nota a mano: {texto[:70]}")
        return nota_a_mano(texto, estado)
    if decision["accion"] == "subir":
        print(f"  subir nota corta: {decision['guion']}")
        if franjas.cupo_para_nota(estado) <= 0:
            bot.mandar("Hoy ya no cabe otra subida sin quitarle lugar a una franja.")
            return False
        return correr([str(RAIZ / "nota.py"), "--subir", decision["guion"]])
    print("  ninguna: no se publica")
    return True


# ------------------------------------------------------------------ franjas
def cerrar_franja(estado, clave, como):
    estado.setdefault("franjas", {})[clave] = f"{como} {config.ahora():%H:%M}"
    estado.pop("pendiente", None)
    estado.get("intentos", {}).pop(clave, None)
    guardar(estado)


def publicar_franja(estado, clave, nombre, historias, como, reservas=()):
    """Arma y sube el video de la franja; si falla, se reintenta en la proxima pasada."""
    previos = [h.get("seguimiento_de", "") for h in historias]
    etiqueta = {"madrugada": "la noche y la madrugada", "manana": "la manana",
                "tarde": "la tarde", "noche": "el cierre del dia"}.get(nombre, nombre)
    ok = armar_video([h["link"] for h in historias], previos, nombre=nombre,
                     pie=f"El Ahorita · {etiqueta}", origen=f"franja-{nombre}",
                     reservas=reservas)
    if ok:
        cerrar_franja(estado, clave, como)
        return True
    intentos = estado.setdefault("intentos", {})
    intentos[clave] = intentos.get(clave, 0) + 1
    if intentos[clave] >= 2:
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
    args = ap.parse_args()

    ahora = config.ahora()
    estado = cargar()
    clave, franja = franja_pendiente(estado, ahora)
    print(f"{ahora:%Y-%m-%d %H:%M} Tijuana · franja pendiente: "
          f"{franja[1] if franja else 'ninguna'}")

    if args.estado:
        print(json.dumps(estado, ensure_ascii=False, indent=1))
        return 0

    if args.franja:
        forzada = franjas.franja_por_nombre(args.franja)
        print(f"forzando franja {forzada[1]}" + (" (prueba)" if args.prueba else ""))
        ok = correr_franja(estado, f"{ahora:%Y-%m-%d}-{forzada[1]}", forzada, ahora,
                           prueba=args.prueba)
        return 0 if ok else 1

    hubo = atender_telegram(estado)
    if not hubo:
        hubo = revisar_pendiente(estado, ahora)
    if not hubo and franja:
        print(f"corriendo la franja {franja[1]}")
        hubo = correr_franja(estado, clave, franja, ahora)
    if not hubo:
        print("sin novedades")
    return 0


if __name__ == "__main__":
    sys.exit(main())
