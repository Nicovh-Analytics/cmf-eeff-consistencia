"""04e: casos con la misma |dif| unidos por las vias PDF->XML y t->t+1; el origen es el primero."""
import importlib

import pandas as pd

m = importlib.import_module("consolidacion.04e_origen")


def test_cadena():
    c = pd.DataFrame([
        dict(caso_id=1, rut="X", anio_doc=2021, columna="actual", tipo="error_PDF", estado_raiz="EFE", linea_raiz="operacion", nivel="subtotal", dif=2269130),
        dict(caso_id=2, rut="X", anio_doc=2021, columna="actual", tipo="error_XML", estado_raiz="EFE", linea_raiz="saldo_final", nivel="total", dif=2269131),
        dict(caso_id=3, rut="X", anio_doc=2022, columna="actual", tipo="error_continuidad", estado_raiz="EFE", linea_raiz="cruce", nivel="identidad", dif=2269130),
        dict(caso_id=4, rut="X", anio_doc=2021, columna="actual", tipo="error_PDF", estado_raiz="ERI", linea_raiz="x", nivel="linea", dif=500),
        dict(caso_id=5, rut="Y", anio_doc=2021, columna="actual", tipo="error_XML", estado_raiz="EFE", linea_raiz="y", nivel="total", dif=2269130)])
    c["doc"] = c["tipo"].map(m.doc)
    c["orden"] = m.orden(c)
    p = m.enlaces(c)
    assert sorted((a, b, v) for a, b, v in p) == [(1, 2, "PDF->XML"), (1, 3, "t->t+1"), (2, 3, "t->t+1")]
    g = m.grupos(list(c["caso_id"]), p)
    assert g[1] == g[2] == g[3] and len({g[4], g[5], g[1]}) == 3


def test_dentro_del_documento_tolerancia_relativa():
    c = pd.DataFrame([
        dict(caso_id=1, rut="X", anio_doc=2021, columna="actual", tipo="error_PDF", estado_raiz="EFE", linea_raiz="aumento_neto", nivel="subtotal", dif=2914),
        dict(caso_id=2, rut="X", anio_doc=2021, columna="actual", tipo="error_PDF", estado_raiz="EFE", linea_raiz="saldo_final", nivel="total", dif=2923),
        dict(caso_id=3, rut="X", anio_doc=2022, columna="anterior", tipo="error_PDF", estado_raiz="EFE", linea_raiz="saldo_final", nivel="total", dif=2930)])
    c["doc"] = c["tipo"].map(m.doc)
    c["orden"] = m.orden(c)
    assert [(a, b, v) for a, b, v in m.enlaces(c)] == [(1, 2, "dentro_del_documento")]      # t->t+1 exige la misma cifra


def test_componente_antes_que_agregado():
    c = pd.DataFrame([
        dict(caso_id=1, rut="X", anio_doc=2024, columna="actual", tipo="error_PDF", estado_raiz="EFE", linea_raiz="aumento_neto", nivel="subtotal", dif=71234554),
        dict(caso_id=2, rut="X", anio_doc=2024, columna="actual", tipo="error_PDF", estado_raiz="EFE", linea_raiz="financiamiento", nivel="subtotal", dif=71270017)])
    c["doc"] = c["tipo"].map(m.doc)
    c["orden"] = m.orden(c)
    assert [(a, b) for a, b, _ in m.enlaces(c)] == [(2, 1)]
