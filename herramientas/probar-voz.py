"""Prueba la voz del robot de punta a punta y te manda el audio a Telegram.

Usa el mismo proveedor que usarian las franjas (ElevenLabs si esta configurado,
si no Voicebox, si no la voz de respaldo). Revisa que genere la frase, que
traiga los tiempos por palabra (subtitulos) y te manda el audio al chat con un
resumen. Si es Voicebox, delega en probar-voicebox.py (con su diagnostico de red).

Uso: python herramientas/probar-voz.py ["frase a decir"]
"""
from __future__ import annotations

import html
import runpy
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402
import telegram  # noqa: E402
import voz  # noqa: E402

FRASE = ("Hola, soy la voz de El Ahorita. Si escuchas esto, la voz nueva ya funciona "
         "y los próximos videos salen así.")


def main():
    frase = " ".join(sys.argv[1:]) or FRASE
    proveedor = voz.proveedor_auto()
    print(f"proveedor: {proveedor}")
    if proveedor == "voicebox":
        sys.argv = [str(RAIZ / "herramientas" / "probar-voicebox.py"), *sys.argv[1:]]
        runpy.run_path(sys.argv[0], run_name="__main__")
        return 0
    salida = RAIZ / "build" / "prueba-voz.mp3"
    salida.parent.mkdir(parents=True, exist_ok=True)
    t = time.time()
    try:
        if proveedor == "elevenlabs":
            palabras = voz.con_elevenlabs(frase, salida)
        else:
            palabras = voz.con_edge_tts(frase, salida)
    except Exception as e:  # noqa: BLE001
        texto = (f"<b>Prueba de voz ({proveedor}): falló</b>\n"
                 f"<pre>{html.escape(str(e)[:600])}</pre>")
        print(texto)
        telegram.mandar(texto)
        return 1
    seg = voz.duracion(salida)
    resumen = (f"Prueba de voz · {proveedor}"
               + (f" · voz {config.ELEVENLABS_VOZ[:8]}… · {config.ELEVENLABS_MODELO}"
                  if proveedor == "elevenlabs" else "")
               + f"\n{seg:.1f} s de audio en {time.time() - t:.1f} s · "
               f"{len(palabras)} palabras con tiempo (subtítulos)")
    print(resumen)
    if proveedor == "edge":
        resumen += ("\nOjo: es la voz de RESPALDO. Falta ELEVENLABS_API_KEY (Secret) "
                    "o ELEVENLABS_VOICE_ID (Variable) en el repo.")
    telegram.mandar_audio(salida, resumen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
