"""Plan de tomas: varias imagenes por nota y datos cuando la voz los dice."""
import tomas


def palabras(texto, cada=0.4):
    return [{"texto": w, "t0": round(i * cada, 3)} for i, w in enumerate(texto.split())]


TEXTO = ("Hakeem Jeffries fue elegido por los democratas para dirigir la Camara . "
         "Lleva 12 años en el Congreso y seria el primer afroamericano en el puesto . "
         "La votacion final sera en enero cuando arranque la nueva legislatura de EU .")


def cubre(plan, dur):
    assert plan[0]["t0"] == 0 and plan[-1]["t1"] == dur
    for a, b in zip(plan, plan[1:]):
        assert a["t1"] == b["t0"]


def test_nota_larga_se_parte_en_tomas_cortas():
    plan = tomas.planear(30.0, hay_foto=True, hay_foto2=True)
    cubre(plan, 30.0)
    assert plan[0]["tipo"] == "principal"
    assert all(t["t1"] - t["t0"] <= tomas.TOMA_MAX + 0.01 for t in plan)
    assert {"principal", "limpia", "foto2"} <= {t["tipo"] for t in plan}


def test_dato_sale_cuando_la_voz_lo_dice():
    pal = palabras(TEXTO)
    t_dicho = next(p["t0"] for p in pal if p["texto"] == "12")
    plan = tomas.planear(30.0, ["12 años en el Congreso"], pal)
    cubre(plan, 30.0)
    dato = next(t for t in plan if t["tipo"] == "dato")
    assert abs(dato["t0"] - (t_dicho - tomas.DATO_ANTES)) < 0.01
    assert dato["t1"] - dato["t0"] <= tomas.DATO_DUR + 0.01


def test_dato_que_no_se_narra_no_sale():
    plan = tomas.planear(30.0, ["500 millones de pesos"], palabras(TEXTO))
    assert not any(t["tipo"] == "dato" for t in plan)


def test_datos_no_se_enciman():
    pal = palabras(TEXTO)
    plan = tomas.planear(30.0, ["12 años en el Congreso", "Primer afroamericano"], pal)
    datos = [t for t in plan if t["tipo"] == "dato"]
    assert all(b["t0"] - a["t0"] >= tomas.DATO_SEPARACION for a, b in zip(datos, datos[1:]))


def test_sin_foto_no_hay_toma_limpia():
    plan = tomas.planear(20.0, hay_foto=False)
    assert {t["tipo"] for t in plan} == {"principal"}
    assert {t["mov"] for t in plan} == {"acerca", "aleja"}       # al menos se mueve distinto


def test_gancho_es_una_toma_con_golpe():
    plan = tomas.planear(7.3, es_gancho=True)
    assert len(plan) == 1 and plan[0]["mov"] == "golpe"


def test_cifras_con_coma_coinciden():
    pal = palabras("hubo 1,500 detenidos en el operativo")
    assert tomas.momento_del_dato("1500 detenidos", pal) is not None


def test_cada_movimiento_es_un_filtro_valido():
    for mov in ("golpe", "acerca", "aleja", "derecha", "izquierda", "suave"):
        f = tomas.zoompan(mov, 120, 1080, 1920, 30)
        assert f.startswith("scale=2160:3840") and "zoompan=" in f and f.count("'") % 2 == 0
