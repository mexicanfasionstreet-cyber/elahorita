"""Subida a YouTube: titulo del guion, fuentes y contenido sintetico declarado."""
import json

import publicar


def test_titulo_y_fuentes_salen_del_guion(tmp_path):
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"guion": {"gancho": "Nvidia no lo quiere de vuelta.", "gancho_pantalla": "JUNTA DE NVIDIA"},
                             "historias": [{"link": "https://elpais.com/x"}]}))
    titulo, desc = publicar.textos(tmp_path / "2026-11-17-elegida.mp4", g)
    assert "Elegida" not in titulo and titulo.startswith("Junta de nvidia")  # solo el rotulo: ultimo recurso
    assert "Fuentes: https://elpais.com/x" in desc


def test_declara_contenido_sintetico_y_respeta_privacidad(tmp_path, monkeypatch):
    monkeypatch.setattr(publicar, "token_de_acceso", lambda: "tok")
    enviado = {}

    class R:
        def __init__(self, cuerpo=b"{}", headers=None):
            self.cuerpo, self.headers = cuerpo, headers or {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self, *a):
            return self.cuerpo

    def falso(req, timeout=0):
        if "uploadType=resumable" in req.full_url:
            enviado["meta"] = json.loads(req.data)
            return R(headers={"Location": "https://subida"})
        return R(json.dumps({"id": "abc", "snippet": {}}).encode())

    monkeypatch.setattr(publicar.urllib.request, "urlopen", falso)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0" * 10)
    assert publicar.subir(video, "t", "d", "private") == "abc"
    status = enviado["meta"]["status"]
    assert status["containsSyntheticMedia"] is True and status["privacyStatus"] == "private"
