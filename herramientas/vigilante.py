"""Vigilante: avisa por Telegram si el robot deja de correr o falla seguido.

Lo corre .github/workflows/vigilante.yml cada 30 minutos con el cron de GitHub,
independiente de cron-job.org (que es quien dispara al robot cada 5 minutos).

  - Sin pasadas en 30 min o mas: lanza una pasada de emergencia (workflow_dispatch)
    y avisa. Asi, si cron-job.org se cae, el robot sigue corriendo cada ~30 min.
  - 3 o mas pasadas seguidas fallidas: avisa con el enlace al ultimo error.
  - Mientras el problema siga, repite el aviso a las 2 h, 6 h y luego cada 12 h.
  - Cuando se recupera, avisa que volvio.

No guarda estado: todo se deduce del historial de pasadas en GitHub.

Uso (necesita GITHUB_TOKEN y GITHUB_REPOSITORY, como en Actions):
    python herramientas/vigilante.py
    python herramientas/vigilante.py --probar     # manda el estado actual al chat
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402

FLUJO = "ahorita.yml"
SILENCIO_MIN = 30            # sin pasadas por mas de esto = problema
FALLAS_SEGUIDAS = 3
CADA = 30                    # el vigilante corre cada 30 min: ventanas de ese ancho


# ------------------------------------------------------------------ decision (pura)
def _dt(iso):
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))


def toca_avisar(minutos):
    """Avisos a los 30 min, 2 h, 6 h y luego cada 12 h (una vez por ventana)."""
    for umbral in (30, 120, 360):
        if umbral <= minutos < umbral + CADA:
            return True
    return minutos >= 720 and (minutos - 720) % 720 < CADA


def _hace(minutos):
    return f"{minutos} min" if minutos < 120 else f"{minutos // 60} h {minutos % 60:02d} min"


def revisar(pasadas, ahora):
    """pasadas: las del robot en main, de la mas reciente a la mas vieja (API de GitHub).

    Devuelve {"avisos": [texto, ...], "despachar": bool, "resumen": texto}.
    """
    salida = {"avisos": [], "despachar": False, "resumen": ""}
    if not pasadas:
        salida["resumen"] = "no hay pasadas del robot"
        return salida
    hora = lambda iso: f"{_dt(iso).astimezone(config.TZ):%H:%M}"  # noqa: E731
    en_curso = [p for p in pasadas if p["status"] in ("queued", "in_progress", "waiting", "pending")]
    terminadas = [p for p in pasadas if p["status"] == "completed" and p.get("conclusion") != "cancelled"]

    # 1) silencio: nadie ha lanzado al robot en un rato
    ultima = _dt(pasadas[0]["created_at"])
    silencio = int((ahora - ultima).total_seconds() // 60)
    if silencio >= SILENCIO_MIN and not en_curso:
        salida["despachar"] = True
        if toca_avisar(silencio):
            salida["avisos"].append(
                f"🚨 <b>El Ahorita no ha corrido en {_hace(silencio)}</b> (ultima pasada "
                f"{hora(pasadas[0]['created_at'])}). Lance una pasada de emergencia y seguire "
                "lanzando una cada 30 min. Revisa cron-job.org.")

    # 2) fallas seguidas
    racha = []
    for p in terminadas:
        if p.get("conclusion") == "success":
            break
        racha.append(p)
    if len(racha) >= FALLAS_SEGUIDAS:
        desde = _dt(racha[-1]["created_at"])
        minutos = int((ahora - desde).total_seconds() // 60)
        if toca_avisar(max(minutos, SILENCIO_MIN)):
            salida["avisos"].append(
                f"🚨 <b>Las ultimas {len(racha)} pasadas del robot fallaron</b> (desde las "
                f"{hora(racha[-1]['created_at'])}).\nUltimo error: {html.escape(racha[0]['html_url'])}")

    # 3) recuperacion: la pasada buena mas reciente cerro un problema hace poco
    if terminadas and terminadas[0].get("conclusion") == "success":
        buena = terminadas[0]
        reciente = (ahora - _dt(buena["updated_at"])) < timedelta(minutes=CADA + 5)
        previas = terminadas[1:]
        fallidas = 0
        for p in previas:
            if p.get("conclusion") == "success":
                break
            fallidas += 1
        hueco = 0
        if len(pasadas) >= 2:
            siguiente = [p for p in pasadas if _dt(p["created_at"]) < _dt(buena["created_at"])]
            if siguiente:
                hueco = int((_dt(buena["created_at"]) - _dt(siguiente[0]["created_at"])).total_seconds() // 60)
        if reciente and (fallidas >= FALLAS_SEGUIDAS or hueco >= SILENCIO_MIN):
            motivo = (f"despues de {fallidas} fallas seguidas" if fallidas >= FALLAS_SEGUIDAS
                      else f"despues de {_hace(hueco)} sin pasadas")
            salida["avisos"].append(f"✅ El robot volvio a correr bien ({hora(buena['created_at'])}), {motivo}.")

    estado = terminadas[0].get("conclusion", "?") if terminadas else "?"
    salida["resumen"] = (f"ultima pasada {hora(pasadas[0]['created_at'])} (hace {_hace(silencio)}), "
                         f"ultima terminada: {estado}, fallas seguidas: {len(racha)}, "
                         f"en curso: {len(en_curso)}")
    return salida


# ------------------------------------------------------------------ GitHub
def _github(ruta, cuerpo=None):
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{ruta}",
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        method="POST" if cuerpo is not None else "GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as r:
        datos = r.read()
    return json.loads(datos) if datos else {}


def pasadas_del_robot():
    return _github(f"/actions/workflows/{FLUJO}/runs?branch=main&per_page=40").get("workflow_runs", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probar", action="store_true", help="manda el estado actual al chat")
    args = ap.parse_args()
    import telegram

    ahora = datetime.now(timezone.utc)
    r = revisar(pasadas_del_robot(), ahora)
    print(r["resumen"])
    if r["despachar"]:
        print("lanzando una pasada de emergencia")
        _github(f"/actions/workflows/{FLUJO}/dispatches", {"ref": "main"})
    for aviso in r["avisos"]:
        print(aviso)
        telegram.mandar(aviso)
    if args.probar:
        telegram.mandar("🛡 <b>Vigilante de El Ahorita</b>: prueba. Asi te aviso si el robot deja de "
                        f"correr o falla seguido.\nAhora: {html.escape(r['resumen'])}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
