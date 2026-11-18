"""Tiempos por palabra para un audio cuyo texto ya conocemos (la voz de Voicebox).

edge-tts entrega el tiempo de cada palabra; Voicebox no. Sin esos tiempos no hay
subtitulos karaoke. Aqui se transcribe el audio con Whisper (faster-whisper, en
CPU) y se alinea esa transcripcion contra el texto del guion:

  - lo que se ve en pantalla es SIEMPRE el texto del guion, bien escrito;
  - Whisper solo pone los tiempos;
  - las palabras que Whisper oye distinto ("115" -> "ciento quince") toman su
    tiempo repartiendo el hueco entre las palabras vecinas que si coinciden.

Uso: python alinear.py audio.mp3 "texto que dice el audio"
"""
from __future__ import annotations

import difflib
import os
import re
import sys
import unicodedata

MODELO = os.environ.get("WHISPER_MODELO", "small")
DUR_MIN = 0.08
PUNTUACION = "\"'“”‘’«»¿¡.,;:!?()[]…—–-"

_modelo = None


def _cargar():
    global _modelo
    if _modelo is None:
        from faster_whisper import WhisperModel
        _modelo = WhisperModel(MODELO, device="cpu", compute_type="int8",
                               cpu_threads=os.cpu_count() or 2)
    return _modelo


def _norm(palabra):
    p = unicodedata.normalize("NFD", palabra.lower())
    p = "".join(c for c in p if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ]", "", p)


def tokens_del_guion(texto):
    """Palabras tal como se ven en pantalla: sin la puntuacion de los bordes."""
    salida = []
    for t in (texto or "").split():
        limpio = t.strip(PUNTUACION)
        if limpio:
            salida.append(limpio)
    return salida


def _muestras(audio):
    """Audio a 16 kHz mono float32, decodificado con ffmpeg.

    faster-whisper abre los archivos con PyAV, y PyAV 15+ ya no acepta el
    argumento que le pasa (metadata_errors): se decodifica aqui y Whisper recibe
    las muestras directamente.
    """
    import subprocess

    import numpy as np
    crudo = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-f", "f32le", "-ac", "1",
         "-ar", "16000", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(crudo, dtype=np.float32)


def transcribir(audio, texto=""):
    """[(palabra, inicio, fin)] segun Whisper. El texto del guion va como pista."""
    segmentos, _ = _cargar().transcribe(
        _muestras(audio), language="es", word_timestamps=True, beam_size=5,
        initial_prompt=texto[:800] or None, vad_filter=False,
        condition_on_previous_text=False)
    return [(w.word.strip(), float(w.start), float(w.end))
            for s in segmentos for w in (s.words or []) if w.word.strip()]


def alinear(guion_tokens, oidas, duracion):
    """Empata palabras del guion con las oidas y rellena los huecos.

    guion_tokens: ["Jensen", "Huang", ...]
    oidas: [(palabra, inicio, fin), ...] de Whisper
    duracion: largo del audio, para el ultimo hueco
    Devuelve [{"texto", "t0", "dur"}] y la proporcion de palabras empatadas.
    """
    n = len(guion_tokens)
    if not n or not oidas:
        return [], 0.0
    a = [_norm(t) for t in guion_tokens]
    b = [_norm(w) for w, _, _ in oidas]
    tiempos = [None] * n
    cm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for bloque in cm.get_matching_blocks():
        for k in range(bloque.size):
            _, ini, fin = oidas[bloque.b + k]
            tiempos[bloque.a + k] = (ini, fin)
    empatadas = sum(t is not None for t in tiempos)

    # huecos: se reparte el tiempo libre entre las palabras sin empate, segun su largo
    i = 0
    while i < n:
        if tiempos[i] is not None:
            i += 1
            continue
        j = i
        while j < n and tiempos[j] is None:
            j += 1
        desde = tiempos[i - 1][1] if i > 0 else 0.0
        hasta = tiempos[j][0] if j < n else max(duracion, desde + 0.3 * (j - i))
        if hasta <= desde:
            hasta = desde + DUR_MIN * (j - i)
        pesos = [max(len(guion_tokens[k]), 1) for k in range(i, j)]
        total, cursor = sum(pesos), desde
        for k, peso in zip(range(i, j), pesos):
            paso = (hasta - desde) * peso / total
            tiempos[k] = (cursor, cursor + paso)
            cursor += paso
        i = j

    salida, previo = [], 0.0
    for t, (ini, fin) in zip(guion_tokens, tiempos):
        ini = max(ini, previo)               # nunca hacia atras
        fin = max(fin, ini + DUR_MIN)
        salida.append({"texto": t, "t0": round(ini, 3), "dur": round(fin - ini, 3)})
        previo = ini
    return salida, empatadas / n


def palabras(audio, texto, duracion):
    """Tiempos por palabra del audio, en el mismo formato que da edge-tts."""
    guion_tokens = tokens_del_guion(texto)
    oidas = transcribir(audio, texto)
    salida, proporcion = alinear(guion_tokens, oidas, duracion)
    print(f"    whisper: {len(oidas)} oidas, {proporcion:.0%} de {len(guion_tokens)} empatadas")
    return salida


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit('uso: python alinear.py audio.mp3 "texto"')
    import subprocess
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", sys.argv[1]],
        capture_output=True, text=True, check=True).stdout)
    for p in palabras(sys.argv[1], sys.argv[2], dur):
        print(f"{p['t0']:>7.2f}  {p['dur']:.2f}  {p['texto']}")
