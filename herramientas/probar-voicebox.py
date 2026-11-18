"""Prueba la voz clonada de punta a punta y manda el audio a tu Telegram.

Sirve igual en tu PC que en GitHub Actions (modo "probar_voz" del workflow, que
ademas entra a tu tailnet). Revisa, en orden:

  1. que VOICEBOX_URL y el perfil esten configurados
  2. que el servidor responda (/health)
  3. que el perfil exista (/profiles)
  4. que genere una frase con la misma funcion que usa el robot
  5. te manda el mp3 al chat para que escuches a Carla

Uso: python herramientas/probar-voicebox.py ["frase a decir"]
"""
from __future__ import annotations

import html
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402
import telegram  # noqa: E402
import voz  # noqa: E402

FRASE = ("Hola, soy la voz de El Ahorita. Si escuchas esto, la conexión con "
         "Voicebox funciona y los próximos videos ya salen con mi voz.")


def fallar(paso, motivo):
    texto = f"<b>Prueba de Voicebox: falló en {paso}</b>\n<pre>{html.escape(str(motivo)[:600])}</pre>"
    print(f"FALLA en {paso}: {motivo}")
    try:
        telegram.mandar(texto)
    except BaseException:  # noqa: BLE001
        pass
    return 1


def diagnostico():
    """Distingue 'tu PC no esta en el tailnet' de 'esta, pero el puerto no responde'."""
    u = urllib.parse.urlparse(config.VOICEBOX_URL)
    host, puerto = u.hostname, u.port or 80
    lineas = []
    if shutil.which("tailscale"):
        r = subprocess.run(["tailscale", "ping", "-c", "3", "--timeout", "5s", host],
                           capture_output=True, text=True)
        salida = (r.stdout + r.stderr).strip().splitlines()
        pong = any("pong" in x for x in salida)
        lineas.append("tailscale ping: " + ("RESPONDE (tu PC esta en linea)" if pong
                                            else "NO responde (PC apagada, dormida o sin Tailscale)"))
    try:
        socket.create_connection((host, puerto), timeout=8).close()
        lineas.append(f"puerto {puerto}: ABIERTO")
    except ConnectionRefusedError:
        lineas.append(f"puerto {puerto}: RECHAZADO (Voicebox escucha solo en localhost: activa el modo remoto)")
    except OSError as e:
        lineas.append(f"puerto {puerto}: sin respuesta ({type(e).__name__}: firewall de Windows o PC fuera de linea)")
    return "\n".join(lineas)


def main():
    frase = " ".join(sys.argv[1:]).strip() or FRASE

    print("1. configuracion")
    if not config.VOICEBOX_URL:
        return fallar("configuracion", "VOICEBOX_URL llego vacio al script")
    if not config.VOICEBOX_PROFILE:
        return fallar("configuracion", "el perfil (VOICEBOX_PROFILE) llego vacio al script")
    print(f"   url con {len(config.VOICEBOX_URL)} caracteres, perfil con "
          f"{len(config.VOICEBOX_PROFILE)} caracteres")

    print("2. el servidor responde")
    try:
        salud = voz._vb_json("/health", timeout=15)
        print(f"   ok: {str(salud)[:160]}")
    except Exception as e:  # noqa: BLE001
        return fallar("conexion", f"{type(e).__name__}: {e}\n\n{diagnostico()}")

    print("3. el perfil existe")
    try:
        perfiles = voz._vb_json("/profiles", timeout=15)
    except Exception as e:  # noqa: BLE001
        return fallar("perfiles", e)
    ids = {p.get("id"): p.get("name", "?") for p in perfiles}
    if config.VOICEBOX_PROFILE not in ids:
        lista = "\n".join(f"{n}: {i}" for i, n in ids.items()) or "(ninguno)"
        return fallar("perfil", f"no existe el perfil configurado. Los que hay:\n{lista}")
    nombre = ids[config.VOICEBOX_PROFILE]
    print(f"   ok: {nombre}")

    print("4. generar una frase")
    salida = RAIZ / "build" / "prueba-voicebox.mp3"
    salida.parent.mkdir(parents=True, exist_ok=True)
    inicio = time.time()
    try:
        voz.con_voicebox(frase, salida)
    except Exception as e:  # noqa: BLE001
        return fallar("generacion", e)
    seg = time.time() - inicio
    dur = voz.duracion(salida)
    print(f"   ok: {dur:.1f} s de audio en {seg:.0f} s")

    print("5. mandar al chat")
    telegram.mandar_audio(salida, f"Prueba de Voicebox · {nombre} · {dur:.1f} s de audio, "
                                  f"generado en {seg:.0f} s")
    print("\nlisto: la conexion con Voicebox funciona")
    return 0


if __name__ == "__main__":
    sys.exit(main())
