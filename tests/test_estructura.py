"""Corte por posicion (comun/estructura): que renglones forman cada subtotal."""
from comun import estructura


def r(glosa, a, b=None, cod=None, metodo="espacial"):
    return dict(glosa=glosa, actual=a, anterior=b, previa="", pagina=1, codigo=cod, coincide="ambos", metodo=metodo)


def test_bloques_esf():
    rs = [r("Activo", None, None, metodo="encabezado"),
          r("Efectivo", 10, 8, "Efectivo"), r("Otros activos", 90, 92, "OtrosActivos"),
          r("Total activo", 100, 100, "TotalActivo"),
          r("Rescates por pagar", 20, 20, "RescatesPorPagar"), r("Nota 2015", 2015),      # fecha sin cuenta: no suma
          r("Total pasivo", 20, 20, "TotalPasivo")]
    L = estructura.lineas(rs)
    sub = {"total_activo": dict(codigo="TotalActivo", partes=["Efectivo", "OtrosActivos"]),
           "total_pasivo": dict(codigo="TotalPasivo", partes=["RescatesPorPagar"])}
    b = {x["i"]: (x["rol"], x["bloque"]) for x in estructura.bloques(L, sub, {"TotalActivo", "TotalPasivo"}, anio=2015)}
    glosa = {i: l[0] for i, l in enumerate(L)}
    assert [glosa[i] for i, v in b.items() if v == ("linea", "total_activo")] == ["Efectivo", "Otros activos"]
    assert [glosa[i] for i, v in b.items() if v == ("linea", "total_pasivo")] == ["Rescates por pagar"]
    assert b[2] == ("subtotal", "total_activo") and b[4][0] == "otro"      # L no trae el encabezado


def test_subtotal_sin_cuenta_corta():
    rs = [r("Compra", -50, cod="Compra"), r("Subtotal ajustes", 7), r("Venta", 60, cod="Venta"),
          r("Flujo neto operacion", 60, cod="FlujoOp")]
    L = estructura.lineas(rs)
    idx = estructura.miembros(L, 3, {"FlujoOp"} - {"FlujoOp"}, partes={"Compra", "Venta"})
    assert [L[j][0] for j in idx] == ["Venta"]            # "Subtotal ajustes" corta el bloque


def test_linea_en_dos_bloques_si_el_corte_falla():
    """Sin el total activo como corte, el bloque del pasivo sube hasta los activos (como el 03b)."""
    rs = [r("Efectivo", 10, cod="Efectivo"), r("Total activo", 10, cod="TotalActivo"),
          r("Rescates", 4, cod="Rescates"), r("Total pasivo", 4, cod="TotalPasivo")]
    L = estructura.lineas(rs)
    sub = {"total_activo": dict(codigo="TotalActivo", partes=["Efectivo"]),
           "total_pasivo": dict(codigo="TotalPasivo", partes=["Rescates", "TotalActivo", "Efectivo"])}
    b = {x["i"]: x["bloque"] for x in estructura.bloques(L, sub, {"TotalPasivo"})}
    assert b[0] == "total_activo|total_pasivo"
