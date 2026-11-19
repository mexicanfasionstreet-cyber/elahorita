"""De punta a punta: guion -> voz (Voicebox falso) -> subtitulos -> video con marca.

Lo unico simulado son Voicebox y Whisper; voz.py, subtitulos.py y capsula.py corren
de verdad con ffmpeg y Pillow. Tarda unos segundos.
"""
import json
import subprocess
import sys

import capsula
import subtitulos
import voz


def test_video_con_voz_clonada_y_subtitulos(tmp_path, monkeypatch, voicebox, whisper_falso, tg):
    corto = tmp_path / "corto.wav"          # 2 s por segmento: el video sale de ~7 s
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
                    "-ar", "24000", str(corto)], check=True)
    voicebox("ok", audio=corto)
    for mod, attr, valor in [(voz, "BUILD", tmp_path / "build"), (capsula, "BUILD", tmp_path / "build"),
                             (capsula, "SALIDA", tmp_path / "videos"), (subtitulos, "RAIZ", tmp_path)]:
        monkeypatch.setattr(mod, attr, valor)
    g = tmp_path / "e2e.json"
    g.write_text(json.dumps({"historias": [], "guion": {
        "gancho": "Esto es una prueba de El Ahorita.", "gancho_pantalla": "PRUEBA DE VOZ",
        "notas": [{"kicker": "PRUEBA", "pantalla": "Subtitulos sincronizados",
                   "texto": "En San Ysidro la espera llega a 115 minutos este martes."}],
        "cierre": "Esto es El Ahorita."}}, ensure_ascii=False))

    monkeypatch.setattr(sys, "argv", ["voz.py", "--guion", str(g), "--proveedor", "voicebox"])
    voz.main()
    manifiesto = json.loads((tmp_path / "build" / "e2e" / "voz.json").read_text())
    assert all(s["voz"] == "voicebox" and s["palabras"] for s in manifiesto["segmentos"])

    monkeypatch.setattr(sys, "argv", ["capsula.py", "--guion", str(g), "--sin-musica"])
    capsula.main()
    video = tmp_path / "videos" / "e2e.mp4"
    assert video.exists() and abs(voz.duracion(video) - manifiesto["total_seg"]) < 0.6
    assert (tmp_path / "build" / "e2e" / "subtitulos.mov").exists()

    # un cuadro a mitad de la nota: la banda de subtitulos no esta vacia
    cuadro = tmp_path / "cuadro.png"
    t = manifiesto["segmentos"][1]["inicio"] + 1.0
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                    str(cuadro)], check=True)
    from PIL import Image
    banda = Image.open(cuadro).convert("L").crop((0, 1300, 1080, 1560))
    assert banda.getextrema()[1] > 200          # hay texto blanco de subtitulos


def test_nota_larga_con_tomas_dato_y_barra(tmp_path, monkeypatch, voicebox, whisper_falso, tg):
    largo = tmp_path / "largo.wav"          # 12 s por segmento
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=12",
                    "-ar", "24000", str(largo)], check=True)
    voicebox("ok", audio=largo)
    for mod, attr, valor in [(voz, "BUILD", tmp_path / "build"), (capsula, "BUILD", tmp_path / "build"),
                             (capsula, "SALIDA", tmp_path / "videos"), (subtitulos, "RAIZ", tmp_path)]:
        monkeypatch.setattr(mod, attr, valor)
    g = tmp_path / "tomas.json"
    g.write_text(json.dumps({"historias": [{"link": "https://elpais.com/x", "foto": {}}], "guion": {
        "gancho": "Los democratas ya tienen candidato.", "gancho_pantalla": "JEFFRIES VA",
        "notas": [{"kicker": "MUNDO", "pantalla": "Democratas nominan a Jeffries",
                   "texto": ("Hakeem Jeffries fue elegido por los democratas para dirigir la Camara. "
                             "Lleva 12 años en el Congreso y seria el primer afroamericano en el puesto. "
                             "La votacion final sera en enero."),
                   "datos": ["12 años en el Congreso", "999 votos en contra"]}],
        "cierre": "Esto es El Ahorita."}}, ensure_ascii=False))
    monkeypatch.setattr(sys, "argv", ["voz.py", "--guion", str(g), "--proveedor", "voicebox"])
    voz.main()
    monkeypatch.setattr(sys, "argv", ["capsula.py", "--guion", str(g), "--sin-musica"])
    capsula.main()

    build = tmp_path / "build" / "tomas"
    trozos = sorted(build.glob("01-nota1-*.mp4"))
    assert len(trozos) >= 3                                     # la nota ya no es una sola imagen
    tarjetas = list((build / "slides").glob("*-dato.png"))
    assert len(tarjetas) == 1                                   # el dato que no se dice no sale

    video = tmp_path / "videos" / "tomas.mp4"
    total = voz.duracion(video)
    cuadro = tmp_path / "mitad.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(total / 2), "-i", str(video),
                    "-frames:v", "1", str(cuadro)], check=True)
    from PIL import Image
    fila = Image.open(cuadro).convert("RGB").crop((0, 3, 1080, 4))
    rojos = sum(1 for r, g_, b in fila.getdata() if r > 170 and g_ < 80 and b < 80)
    assert 0.35 < rojos / 1080 < 0.65                           # barra de progreso a la mitad
