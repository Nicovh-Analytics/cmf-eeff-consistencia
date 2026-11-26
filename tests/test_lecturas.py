"""Dos lecturas (motor/lecturas): un corte que toma un renglon de mas no cuadra por posicion y si por codigo."""
import pandas as pd

from motor import lecturas

OP = "FlujoNetoOriginadoPorActividadesDeLaOperacion"


def hechos(filas):
    h = pd.DataFrame(filas, columns=["codigo", "valor", "rol", "bloque"])
    return h.assign(archivo="X_2020", contexto="PeriodoActual", estado="EFE", serie="")


def test_corte_con_renglon_de_mas():
    h = hechos([
        ("", 7.0, "linea", "operacion"),                      # numero de nota que el corte tomo
        ("CompraDeActivosFinancieros", -40.0, "linea", "operacion"),
        ("VentaCobroDeActivosFinancieros", 100.0, "linea", "operacion"),
        (OP, 60.0, "subtotal", "operacion"),
    ])
    r = lecturas.dos_lecturas(h).set_index("subtotal").loc["operacion"]
    assert (r["rut"], r["anio"], r["columna"]) == ("X", 2020, "actual")
    assert (r["total_pos"], r["suma_pos"], bool(r["cuadra_pos"])) == (60.0, 67.0, False)
    assert (r["total_cod"], r["suma_cod"], bool(r["cuadra_cod"])) == (60.0, 60.0, True)


def test_signo_impreso_no_se_corrige():
    # la compra impresa en positivo: con el signo oficial cuadraria; con el impreso no
    h = hechos([
        ("CompraDeActivosFinancieros", 40.0, "linea", "operacion"),
        ("VentaCobroDeActivosFinancieros", 100.0, "linea", "operacion"),
        (OP, 60.0, "subtotal", "operacion"),
    ])
    r = lecturas.dos_lecturas(h).set_index("subtotal").loc["operacion"]
    assert not r["cuadra_pos"] and not r["cuadra_cod"]
