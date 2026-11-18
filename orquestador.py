"""Orquestador: decide que hacer en cada corrida del robot.

Se ejecuta cada 15 minutos en GitHub Actions. En cada pasada:

  1. Atiende Telegram: si tocaste un boton o escribiste /nota, arma ese video.
  2. Si toca franja (05:00, 12:00, 15:00, 20:00 en Tijuana) y no se ha mandado hoy,
     actualiza el radar y manda las tres candidatas con botones.

Como la hora se calcula en Tijuana, el cambio de horario se ajusta solo: no hay
que tocar los cron dos veces al ano.

Uso:
    python orquestador.py              # una pasada (lo que hara el cron)
    python orquestador.py --estado     # solo dice que haria, sin ejecutar
    python orquestador.py --franja     # fuerza la franja ahora
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import telegram as bot  # noqa: E402

ESTADO = RAIZ / "datos" / "orquestador.json"
TZ = ZoneInfo("America/Tijuana")
FRANJAS = [(5, "manana"), (12, "mediodia"), (15, "tarde"), (20, "noche")]
MARGEN_FRANJA = 2      # horas de ventana para disparar la franja


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
            bot.mandar(f"<b>Fallo en {nombre}</b>\n<pre>{cola[-600:]}</pre>")
        except Exception:  # noqa: BLE001
            pass
    return False


def subir_a_youtube(video):
    """Sube el video al canal si hay credenciales. Devuelve el enlace o None."""
    import config
    if not (config.YT_CLIENT_ID and config.YT_CLIENT_SECRET and config.YT_REFRESH):
        return None
    privacidad = os.environ.get("YT_PRIVACIDAD", "public")
    print(f"  subiendo a YouTube ({privacidad})")
    hecho = subprocess.run(
        [sys.executable, str(RAIZ / "publicar.py"), "--video", str(video),
         "--privacidad", privacidad],
        cwd=RAIZ, capture_output=True, text=True, errors="replace")
    print(hecho.stdout[-1500:])
    if hecho.returncode != 0:
        bot.mandar(f"<b>No se pudo subir a YouTube</b>\n<pre>"
                   f"{(hecho.stderr or hecho.stdout)[-500:]}</pre>")
        return None
    for linea in (hecho.stdout or "").splitlines():
        if "youtube.com/shorts/" in linea:
            return linea.split()[-1]
    return None


def armar_video(link="", tema=""):
    """Guion -> voz -> video -> chat (y YouTube) para una historia o un tema."""
    sello = datetime.now(TZ).strftime("%Y-%m-%d")
    if tema:
        if not correr([str(RAIZ / "nota.py"), tema]):
            return False
        return True

    destino = RAIZ / "docs" / "guiones" / f"{sello}-elegida.json"
    if not correr([str(RAIZ / "guion.py"), "--link", link, "--franja", "elegida"]):
        return False
    if not correr([str(RAIZ / "voz.py"), "--guion", str(destino)]):
        return False
    if not correr([str(RAIZ / "capsula.py"), "--guion", str(destino)]):
        return False
    video = RAIZ / "docs" / "videos" / f"{sello}-elegida.mp4"
    if not video.exists():
        return False
    enlace = subir_a_youtube(video)
    pie = "El Ahorita · la nota que elegiste"
    if enlace:
        pie += f"\n{enlace}"
    bot.mandar_video(video, pie)
    return True


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


def atender_telegram():
    """Lee lo que hayas mandado y actua. Devuelve True si hizo algo."""
    decision = bot.recoger(texto_libre=True)
    if decision:
        guardar_offset()
    if not decision:
        return False
    if decision["accion"] == "publicar":
        historia = decision.get("historia") or {}
        print(f"  elegiste: {historia.get('titulo', '')[:70]}")
        return armar_video(link=historia.get("link", ""))
    if decision["accion"] == "nota_manual":
        texto = decision.get("texto", "")
        if not texto:
            bot.mandar("Escribe el tema o el enlace despues de /nota")
            return False
        print(f"  nota a mano: {texto[:70]}")
        return armar_video(tema=texto)
    print("  ninguna: no se publica")
    return True


def franja_pendiente(estado, ahora):
    """Que franja toca, si hay alguna dentro de su ventana y sin mandar."""
    for hora, nombre in FRANJAS:
        if not (hora <= ahora.hour < hora + MARGEN_FRANJA):
            continue
        clave = f"{ahora:%Y-%m-%d}-{nombre}"
        if estado["franjas"].get(clave):
            continue
        return clave, nombre
    return None, None


def mandar_franja(estado, clave):
    if not correr([str(RAIZ / "aggregate.py"), "--days", "2"]):
        print("  fallo el radar; se reintenta en la proxima pasada")
        return False
    if not correr([str(RAIZ / "telegram.py"), "--candidatas"]):
        return False
    estado["franjas"][clave] = datetime.now(TZ).isoformat(timespec="seconds")
    guardar(estado)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--estado", action="store_true")
    ap.add_argument("--franja", action="store_true")
    args = ap.parse_args()

    ahora = datetime.now(TZ)
    estado = cargar()
    clave, nombre = franja_pendiente(estado, ahora)
    print(f"{ahora:%Y-%m-%d %H:%M} Tijuana · franja pendiente: {nombre or 'ninguna'}")

    if args.estado:
        print(json.dumps(estado, ensure_ascii=False, indent=1))
        return 0

    if args.franja:
        print("forzando franja")
        return 0 if mandar_franja(estado, f"{ahora:%Y-%m-%d}-manual") else 1

    hubo = atender_telegram()
    if not hubo and clave:
        print(f"mandando candidatas de la franja {nombre}")
        hubo = mandar_franja(estado, clave)
    if not hubo:
        print("sin novedades")
    return 0


if __name__ == "__main__":
    sys.exit(main())
