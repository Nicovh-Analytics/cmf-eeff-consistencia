"""03c (E5): las lineas salen de los hechos del PDF: el primer renglon del estado con el codigo, sus dos columnas."""
import importlib

import pandas as pd

m03c = importlib.import_module("validaciones.estructura.03c_identidades")
AN = m03c.LINEAS["activo_neto"]["codigo"]


def test_primer_renglon_con_el_codigo(monkeypatch):
    filas = [  # archivo, contexto, estado, codigo, valor, orden, coincide
        ("X_2020", "PeriodoActual", "ESF", AN, 100.0, 5, "ambos"),
        ("X_2020", "PeriodoAnterior", "ESF", AN, 90.0, 5, "ambos"),
        ("X_2020", "PeriodoActual", "ESF", AN, 7.0, 9, "glosa"),        # repetido mas abajo: no se usa
        ("X_2020", "PeriodoActual", "ERI", AN, 1.0, 1, "ambos"),        # otro estado: no es la linea
        ("Y_2021", "PeriodoAnterior", "ESF", AN, 50.0, 3, "valor"),     # solo columna anterior
    ]
    h = pd.DataFrame(filas, columns=["archivo", "contexto", "estado", "codigo", "valor", "orden", "coincide"])
    h = h.assign(metodo="tabla", pagina=2, ocr=False, espaciada=False)
    monkeypatch.setattr(m03c.hechos, "pdf", lambda: h)
    lin, est = m03c.lineas_pdf()
    x = lin["X_2020"]["activo_neto"]
    assert (x["actual"], x["anterior"], x["coincide"]) == (100.0, 90.0, "ambos")
    y = lin["Y_2021"]["activo_neto"]
    assert (y["actual"], y["anterior"]) == (None, 50.0)
    assert ("X_2020", "ERI") in est and "utilidad_operacion" not in lin["X_2020"]
