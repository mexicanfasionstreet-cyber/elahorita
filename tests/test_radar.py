"""Radar: el archivo de noticias guarda solo los ultimos ARCHIVO_DIAS dias."""
import json
from datetime import datetime, timedelta, timezone

import aggregate


def fila(i, dias_atras):
    fecha = (datetime.now(timezone.utc) - timedelta(days=dias_atras)).isoformat()
    return {"id": f"v{i}", "published": fecha, "title": f"Vieja {i}", "source": "M", "tags": ["politica"],
            "lang": "es", "link": f"l{i}", "excerpt": "", "image": "", "also": [], "mirror": False, "weight": 3}


def test_archivo_suma_nuevas_y_recorta_lo_viejo(tmp_path):
    (tmp_path / "datos").mkdir()
    jl = tmp_path / "datos" / "noticias.jsonl"
    viejas = [fila(i, 45) for i in range(3)] + [fila(i, 5) for i in range(3, 5)]
    jl.write_text("".join(json.dumps({**v, "section": "politica"}) + "\n" for v in viejas))
    nuevos, total = aggregate.update_archive([fila(9, 0), fila(3, 5)], tmp_path)
    ids = [json.loads(l)["id"] for l in jl.read_text().splitlines()]
    assert nuevos == 1                               # v3 ya estaba
    assert total == 3 and sorted(ids) == ["v3", "v4", "v9"]
    assert not (tmp_path / "datos" / "noticias.csv").exists()


def test_el_radar_ya_no_tiene_panel_ni_digest():
    assert not hasattr(aggregate, "write_digest") and not hasattr(aggregate, "ui")
