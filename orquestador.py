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


def correr(comando):
    """Ejecuta un script del proyecto y devuelve si salio bien."""
    print(f"  $ {' '.join(str(c) for c in comando[1:])}")
    hecho = subprocess.run([sys.executable, *comando], cwd=RAIZ)
    return hecho.returncode == 0


def armar_video(link="", tema=""):
    """Guion -> voz -> video -> chat para una historia o un tema."""
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
    if video.exists():
        bot.mandar_video(video, "El Ahorita · la nota que elegiste")
        return True
    return False


def atender_telegram():
    """Lee lo que hayas mandado y actua. Devuelve True si hizo algo."""
    decision = bot.recoger(texto_libre=True)
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
