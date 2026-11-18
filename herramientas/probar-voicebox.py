"""Prueba la voz clonada de punta a punta y manda el audio a tu Telegram.

Sirve igual en tu PC que en GitHub Actions (modo "probar_voz" del workflow, que
ademas entra a tu tailnet). Revisa, en orden:

  1. que VOICEBOX_URL y el perfil esten configurados
  2. que el servidor responda (/health)
  3. que el perfil exista (/profiles)
  4. que genere una frase con la misma funcion que usa el robot
  5. que Whisper saque los tiempos por palabra (subtitulos karaoke)
  6. arma un video corto de prueba con voz, marca y subtitulos, igual que el
     robot, y te lo manda al chat (si el video falla, manda solo el audio)

Uso: python herramientas/probar-voicebox.py ["frase a decir"]
"""
from __future__ import annotations

import html
import json
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

    print("5. tiempos por palabra con Whisper")
    try:
        import alinear
        pals = alinear.palabras(salida, frase, dur)
        con_tiempo = " ".join(f"{p['texto']}@{p['t0']:.1f}" for p in pals[:8])
        print(f"   ok: {len(pals)} palabras · {con_tiempo} …")
    except Exception as e:  # noqa: BLE001
        return fallar("whisper", f"{type(e).__name__}: {e}")

    print("6. video de prueba con subtitulos")
    guion = RAIZ / "build" / "prueba-voicebox-video.json"
    guion.write_text(json.dumps({"historias": [], "guion": {
        "gancho": "Esto es una prueba de El Ahorita con la voz de Carla.",
        "gancho_pantalla": "PRUEBA DE VOZ",
        "notas": [{"kicker": "PRUEBA", "pantalla": "Subtitulos sincronizados",
                   "texto": frase}],
        "cierre": "Esto es El Ahorita."}}, ensure_ascii=False), encoding="utf-8")
    pasos = [[sys.executable, str(RAIZ / "voz.py"), "--guion", str(guion),
              "--proveedor", "voicebox"],
             [sys.executable, str(RAIZ / "capsula.py"), "--guion", str(guion)]]
    for paso in pasos:
        r = subprocess.run(paso, cwd=RAIZ, capture_output=True, text=True, errors="replace")
        print(r.stdout[-1500:])
        if r.returncode != 0:
            print(r.stderr[-1500:])
            telegram.mandar_audio(salida, f"Prueba de Voicebox · {nombre} · el audio "
                                          f"funciona, pero el video de prueba fallo")
            return fallar("video de prueba", (r.stderr or r.stdout)[-500:])
    video = RAIZ / "docs" / "videos" / f"{guion.stem}.mp4"
    telegram.mandar_video(video, f"Prueba de Voicebox · {nombre} · voz y subtitulos "
                                 f"karaoke · {dur:.1f} s de la frase en {seg:.0f} s")
    print("\nlisto: Voicebox y los subtitulos funcionan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
