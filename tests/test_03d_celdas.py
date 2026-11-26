"""03d (E6): las celdas del bloque del ECP salen como hechos, con el codigo del catalogo por serie y Total."""
import importlib

m03d = importlib.import_module("validaciones.estructura.03d_ecp")


def test_celdas_del_bloque():
    b = dict(total=2, pagina=7, ocr=False,
             filas={"inicio": {0: 10.0, 1: 5.0, 2: 15.0}, "aportes": {2: 3.0}, "otra": {0: 1.0}})
    c = {(x["fila"], x["k"]): x for x in m03d.celdas(dict(rut="X", anio=2020), "actual", b)}
    assert len(c) == 5
    t = c[("inicio", 2)]
    assert (t["es_total"], t["serie"], t["codigo"], t["valor"]) == (True, "", m03d.XML["inicio"], 15.0)
    s = c[("inicio", 0)]
    assert (s["es_total"], s["serie"], s["codigo"]) == (False, "serie_1", m03d.XML["inicio"] + "PorSerie")
    assert c[("otra", 0)]["codigo"] == ""            # fila sin codigo en el catalogo
