"""E7: la glosa decide el codigo (catalogo), un concepto por renglon; el XML es testigo (monto_de)."""
from comun.emparejar import _catalogo, _orden, emparejar

R = lambda g, a, b, p=1: dict(glosa=g, previa="", metodo="espacial", actual=a, anterior=b, pagina=p)
OP, FI = "FlujoNetoOriginadoPorActividadesDeLaOperacion", "FlujoNetoOriginadoPorActividadesDeFinanciamiento"
SI, SF = "SaldoInicialDeEfectivoYEfectivoEquivalente", "SaldoFinalDeEfectivoYEfectivoEquivalente"


def efe(rs, xml, est="EFE"):
    voc, canon = _catalogo()
    return emparejar(rs, xml, est, vocabulario=voc[est], canon=canon, orden=_orden()[est])


def test_rotulo_de_otro_subtotal():
    # subtotal de financiamiento impreso con el rotulo de la operacion: no toma el sinonimo de la operacion
    rs = efe([R("Flujo neto originado por actividades de la operacion", -86698.0, -23055.0),
              R("Colocacion de cuotas en circulacion", 159592.0, 38013.0),
              R("Flujo neto originado por actividades de la operacion", 92824.0, 24773.0)],
             {OP: (-86698, -23055), "ColocacionDeCuotasEnCirculacion": (159592, 38013), FI: (92824, 24773)})
    assert [r["codigo"] for r in rs] == [OP, "ColocacionDeCuotasEnCirculacion", FI]
    assert rs[2]["glosa_de"] == OP


def test_montos_cruzados_no_se_esconden():
    # PDF: inicial y final con los montos de la otra cuenta del XML -> manda la glosa, el XML marca monto_de
    rs = efe([R("Saldo inicial de efectivo y efectivo equivalente", 17871.0, 206324.0),
              R("Saldo final efectivo y efectivo equivalente", 206324.0, 40221.0)],
             {SI: (206324, 40221), SF: (17871, 206324)})
    assert [(r["codigo"], r["coincide"], r["monto_de"]) for r in rs] == [(SI, "glosa", SF), (SF, "glosa", SI)]


def test_sin_asignacion_por_valor():
    rs = efe([R("Linea sin glosa reconocible", 7.0, 1.0)], {"OtrosIngresosDeOperacion": (7, 1)})
    assert rs[0]["codigo"] is None and rs[0]["monto_de"] is None


def test_concepto_y_plantilla(monkeypatch):
    # leer_y_emparejar informa el concepto (codigo directo) y deja el sinonimo elegido en codigo_plantilla
    import pandas as pd
    import comun.emparejar as e
    import comun.lector as lector
    r = R("Aumento (disminucion) neto de efectivo y efectivo equivalente", 6126.0, 1718.0)
    r["estado"] = "EFE"
    monkeypatch.setattr(lector, "paginas_de", lambda p, c: ([1], None))
    monkeypatch.setattr(lector, "leer_estados", lambda c, p, base=None: ([r], {}))
    cta = pd.DataFrame(dict(estado_fin="EFE", serie=[None], contexto="PeriodoActual",
                            codigo="AumentoNetoDeEfectivoYEfectivoEquivalente", valor=6126.0))
    out, _ = e.leer_y_emparejar({}, "", cta)
    q = out["EFE"][0]
    assert q["codigo"] == "AumentoNetoDeEfectivoYEfectivoEquivalente"
    assert q["codigo_plantilla"] in ("AumentoNetoDeEfectivoYEfectivoEquivalente",
                                     "AumentoDisminucionNetoDeEfectivoYEfectivoEquivalente")


ANT = "AumentoDisminucionDeActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionAntesDeDistribucionDeBeneficios"
DES = ANT.replace("Antes", "Despues")


def test_posicion_subtotal_en_el_titulo_siguiente():
    # el monto de la operacion impreso en el titulo de financiamiento: por posicion es la operacion
    rs = efe([R("Flujos de efectivo originado por actividades de la operacion:", None, None),   # titulo sin montos
              R("Otros gastos de operacion pagados", -2.0, 0.0),
              R("Flujos de efectivo originado por actividades de financiamiento:", -89946832.0, 3238475.0),
              R("Colocacion de cuotas en circulacion", 159592.0, 38013.0),
              R("Flujo neto (utilizado en)/originado por actividades de financiamiento", 92824.0, 24773.0)], {})
    assert (rs[2]["codigo"], rs[2]["coincide"], rs[2]["glosa_de"]) == (OP, "posicion", FI)


def test_posicion_resultado_despues_repetido():
    # "despues de distribucion" impreso dos veces: el primero (sobre la distribucion) es el antes
    rs = efe([R("Utilidad (perdida) de la operacion despues de impuesto", -7475846.0, 10021325.0),
              R("Aumento (disminucion) de activo neto atribuible a participes originadas por actividades de la "
                "operacion despues de distribucion de beneficios", -7475846.0, 10021325.0),
              R("Distribucion de beneficios", -1.0, -1.0),
              R("Aumento (disminucion) de activo neto atribuible a participes originadas por actividades de la "
                "operacion despues de distribucion de beneficios", -7475900.0, 10021300.0)],
             {DES: (-7475900, 10021300)}, "ERI")            # el XML solo desempata las dos glosas iguales
    assert (rs[1]["codigo"], rs[1]["coincide"]) == (ANT, "posicion") and rs[3]["codigo"] == DES
    assert rs[1]["glosa_de"] == DES                          # rotulo de otra cuenta: hallazgo de presentacion


def test_posicion_glosa_cortada():
    rs = efe([R("Utilidad (perdida) de la operacion despues de impuesto", -2560.0, -631.0),
              R("Aumento/(disminucion) de activo neto atribuible a participes originadas por", -2560.0, -631.0),
              R("Aumento (disminucion) de activo neto atribuible a participes originadas por actividades de la "
                "operacion despues de distribucion de beneficios", -2560.0, -631.0)], {}, "ERI")
    assert [r["codigo"] for r in rs[1:]] == [ANT, DES]


def test_posicion_con_cuentas_impresas_sin_montos():
    # "Otros ingresos" y "Otros gastos" impresos con guion: estan, no son el hueco
    rs = efe([R("Montos pagados a sociedad administradora e intermediarios", -5.0, -4.0),
              R("Otros ingresos de operacion", None, None),
              R("Otros gastos de operacion pagados", None, None),
              R("Flujos de efectivo originado por actividades de financiamiento:", -89946832.0, 3238475.0),
              R("Colocacion de cuotas en circulacion", 159592.0, 38013.0),
              R("Flujo neto originado por actividades de financiamiento", 92824.0, 24773.0)], {})
    assert (rs[3]["codigo"], rs[3]["coincide"]) == (OP, "posicion")


def test_rotulo_repetido_con_xml_cruzado():
    # el XML trae antes y despues cruzados: el desempate por XML daba el "despues" al de arriba;
    # el orden de la plantilla los pone en su lugar y el XML queda como testigo de los dos
    g = ("Aumento (disminucion) de activo neto atribuible a participes originadas por actividades de la "
         "operacion despues de distribucion de beneficios")
    rs = efe([R("Utilidad (perdida) de la operacion despues de impuesto", -6718569.0, 10021325.0),
              R(g, -6718569.0, 10021325.0),
              R("Distribucion de beneficios", -757277.0, -5000.0),
              R(g, -7475846.0, 10016325.0)],
             {ANT: (-7475846, 10016325), DES: (-6718569, 10021325)}, "ERI")
    assert [(r["codigo"], r["monto_de"]) for r in (rs[1], rs[3])] == [(ANT, DES), (DES, ANT)]
    assert rs[1]["glosa_de"] == DES


def test_pagina_de_notas_no_toma_cuentas():
    # el lector dejo en el EFE una pagina de notas con "Saldo final al 31 de diciembre": no toma la cuenta
    rs = efe([R("Saldo inicial de efectivo y efectivo equivalente", 10.0, 5.0, 6),
              R("Aumento neto de efectivo y efectivo equivalente", 3.0, 5.0, 6),
              R("Saldo final de efectivo y efectivo equivalente", 13.0, 10.0, 6),
              R("Saldo final al 31 de diciembre", 528715907.0, 526130307.0, 23)], {})
    assert rs[2]["codigo"] == SF and rs[3]["codigo"] is None


def test_texto_duplicado_es_lectura():
    rs = efe([R("SSAALLDDOO FFIINNAALL", 66887711000011.0, 33882266666699.0)], {})
    assert rs[0]["codigo"] is None


def test_total_no_toma_una_linea_por_posicion():
    voc, canon = _catalogo()
    rs = emparejar([R("Remuneraciones sociedad administradora", 100.0, 0.0),
                    R("Total pasivos corrientes", 8208.0, 0.0),
                    R("Total pasivos (excluido el activo neto atribuible a participes)", 8208.0, 0.0)],
                   {}, "ESF", vocabulario=voc["ESF"], canon=canon, orden=_orden()["ESF"])
    assert rs[1]["codigo"] is None and rs[2]["codigo"] == "TotalPasivo"


def test_total_activo_corriente_como_unico_total():
    voc, canon = _catalogo()
    rs = emparejar([R("Efectivo y efectivo equivalente", 407965.0, 17477.0),
                    R("Total activo corriente", 407965.0, 17477.0)],
                   {}, "ESF", vocabulario=voc["ESF"], canon=canon, orden=_orden()["ESF"])
    assert rs[1]["codigo"] == "TotalActivo"


def test_total_activo_neto_no_es_total_activo():
    # ESF 10369 2023: "Total activo corriente" es el total; "Total activo neto atribuible" es el activo neto
    voc, canon = _catalogo()
    rs = emparejar([R("Efectivo y efectivo equivalente", 4794.0, 1500.0),
                    R("Activos financieros a valor razonable con efecto en resultados", 382629.0, 0.0),
                    R("Total activo corriente", 387423.0, 1500.0),
                    R("Rescate por pagar", 450.0, 0.0),
                    R("Total pasivos (excluido el activo neto atribuible a participes)", 545.0, 0.0),
                    R("Total activo neto atribuible a los participes", 386878.0, 1500.0)],
                   {}, "ESF", vocabulario=voc["ESF"], canon=canon, orden=_orden()["ESF"])
    assert rs[2]["codigo"] == "TotalActivo" and rs[5]["codigo"] == "ActivoNetoAtribuibleALosParticipes"
