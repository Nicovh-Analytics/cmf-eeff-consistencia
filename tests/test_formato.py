"""03h: hallazgos de formato desde los renglones del lector."""
import importlib

import pandas as pd

m = importlib.import_module("validaciones.formato.03h_formato")


def test_hallazgos():
    glosa, signo, sinon = m.oficial()
    r = pd.DataFrame([
        dict(rut="X", anio=2020, estado="EFE", pagina=5, codigo="RescatesDeCuotasEnCirculacion", glosa="Rescates",
             actual=135.0, anterior=-14.0, formato=None, glosa_de=None, monto_de="ColocacionDeCuotasEnCirculacion",
             rotulo=None, ocr=False, metodo="espacial"),
        dict(rut="X", anio=2020, estado="ESF", pagina=3, codigo="EfectivoYEfectivoEquivalente", glosa="Efectivo",
             actual=-59820025.0, anterior=1.0, formato="parentesis:59.820.025)", glosa_de=None, monto_de=None,
             rotulo=None, ocr=False, metodo="espacial")])
    h = m.hallazgos(r, signo)
    t = sorted(zip(h["tipo"], h["columna"].fillna("")))
    assert t == [("monto_cruzado", ""), ("parentesis", ""), ("signo_mixto", "actual"), ("signo_modelo", "actual")]
    ad = m.adherencia(r, glosa, sinon)
    assert ad["parecido"].between(0, 1).all() and len(ad) == 2


def test_convencion_signo():
    _, signo, _ = m.oficial()
    fila = lambda c, a: dict(rut="X", anio=2020, estado="EFE", pagina=5, codigo=c, glosa="Linea", actual=a, anterior=None,
                             formato=None, glosa_de=None, monto_de=None, rotulo=None, ocr=False, metodo="espacial")
    r = pd.DataFrame([fila("RescatesDeCuotasEnCirculacion", -10.0), fila("CompraDeActivosFinancieros", -5.0),
                      fila("MontosPagadosASociedadAdministradoraEIntermediarios", 3.0)])
    _, c = m.convencion_signo(r, signo)
    assert c["convencion"].tolist() == ["mixta"]
    h = m.hallazgos(r, signo)
    assert h["tipo"].tolist() == ["signo_mixto"] and h["codigo"].tolist() == ["MontosPagadosASociedadAdministradoraEIntermediarios"]


def test_rotulo_distingue():
    glosa, _, sinon = m.oficial()
    ANT = "AumentoDisminucionDeActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionAntesDeDistribucionDeBeneficios"
    DES = ANT.replace("Antes", "Despues")
    g = "Aumento (disminucion) de activo neto atribuible a participes originadas por actividades de la operacion"
    assert m.distingue(g + " antes de distribucion de beneficios", DES, ANT, glosa, sinon)
    assert not m.distingue(g, DES, ANT, glosa, sinon)                 # glosa que no dice antes ni despues


def test_glosa_contradictoria():
    glosa, signo, sinon = m.oficial()
    assert m.contradictoria("Otros ingresos de operación pagados") and not m.contradictoria("Dividendos pagados")
    assert not m.contradictoria("Otros ingresos (egresos) de operación")
    assert not m.contradictoria("Intereses, diferencias de cambio, pagos de capital (cupones) y reajustes recibidos")
    assert m.contradictoria("Otros gastos de operación percibidos")
    fila = lambda g, c: dict(rut="X", anio=2018, estado="EFE", pagina=5, codigo=c, glosa=g, actual=59964.0,
                             anterior=None, formato=None, glosa_de=None, monto_de=None, rotulo=None, ocr=False,
                             metodo="espacial")
    r = pd.DataFrame([fila("Otros ingresos de operación pagados", "OtrosIngresosDeOperacion"),
                      fila("Otros gastos de operación pagados", "OtrosGastosDeOperacionPagados")])
    h = m.hallazgos(r, signo, glosa=glosa, sinon=sinon)
    g = h[h["tipo"] == "glosa_contradictoria"]
    assert len(g) == 1 and g["detalle"].iloc[0].startswith("glosa del modelo CMF")


def test_modelo_contradictorio():
    glosa, signo, sinon = m.oficial()
    fila = lambda rut, g: dict(rut=rut, anio=2018, estado="EFE", pagina=5, codigo="OtrosIngresosDeOperacion", glosa=g,
                               actual=1.0, anterior=None, formato=None, glosa_de=None, monto_de=None, rotulo=None,
                               ocr=False, metodo="espacial")
    r = pd.DataFrame([fila("A", "Otros ingresos de operación pagados"), fila("B", "Otros ingresos de operación")])
    h = m.hallazgos(r, signo, glosa=glosa, sinon=sinon)
    enc = pd.DataFrame([dict(rut="A", anio=2018, nombre_agf="X"), dict(rut="B", anio=2018, nombre_agf="Y")])
    mc = m.modelo_contradictorio(r, h, glosa, enc)
    assert mc[["fondo_anio_cuenta", "copian", "agf_cuenta", "agf_copian"]].values.tolist() == [[2, 1, 2, 1]]


def test_desalineado_columna_y_sin_glosa():
    # ERI 2022: la utilidad antes de impuestos en blanco en el actual y su monto impreso en "Impuestos"
    fila = lambda g, c, a, b: dict(rut="X", anio=2022, estado="ERI", pagina=7, codigo=c, glosa=g, actual=a,
                                   anterior=b, formato=None, glosa_de=None, monto_de=None, rotulo=None, ocr=False,
                                   metodo="espacial")
    UA, IMP = "UtilidadPerdidaDeLaOperacionAntesDeImpuesto", "ImpuestosALasGananciasPorInversionesEnElExterior"
    r = pd.DataFrame([fila("Resultado en venta de instrumentos financieros", "ResultadoEnVentaDeInstrumentosFinancieros",
                           -365177.0, 20455004.0),
                      fila("", None, 71.0, None),
                      fila("Utilidad de la operacion antes de impuestos", UA, None, -2030102.0),
                      fila("Impuestos a las ganancias por inversiones en el exterior", IMP, 1188551.0, None)])
    vx = {("X", 2022, "ERI", UA, "actual"): 1188551.0, ("X", 2022, "ERI", IMP, "actual"): 0.0}
    glosa, signo, sinon = m.oficial()
    h = m.hallazgos(r, signo, vx=vx)
    d = h[h["tipo"] == "monto_desalineado_columna"]
    assert d[["codigo", "columna", "monto"]].values.tolist() == [[IMP, "actual", 1188551.0]]
    assert h[h["tipo"] == "monto_sin_glosa"]["monto"].tolist() == [71.0]
    # la linea de montos de una glosa partida no es monto sin glosa
    r2 = pd.DataFrame([fila("Activos financieros a valor razonable 05-07-", None, None, None),
                       fila("30", "ActivosFinancierosAValorRazonableConEfectoEnResultados", 110955999.0, 185335359.0)])
    assert m.sin_glosa(r2).empty


def test_desalineado_ecp():
    # 9061 2015 (comparativo 2014): resultado antes de distribucion con guion y su monto en "Distribucion"
    cod = importlib.import_module("validaciones.estructura.03d_ecp").CODIGO_FILA
    celda = lambda f, v: dict(rut="X", anio=2015, contexto="PeriodoAnterior", fila=f, valor=v, es_total=True,
                              pagina=8, ocr=False)
    e = pd.DataFrame([celda("neto", 20743089.0), celda("res_antes", 0.0), celda("dist", 179735.0),
                      celda("res_despues", 179735.0), celda("cierre", 20922824.0)])
    vx = {("X", 2015, "ECP", cod["res_antes"], "anterior"): 179735.0,
          ("X", 2015, "ECP", cod["dist"], "anterior"): 0.0,
          ("X", 2015, "ECP", cod["res_despues"], "anterior"): 179735.0}
    d = m.desalineado_ecp(e, vx)
    assert d[["codigo", "columna", "monto"]].values.tolist() == [[cod["dist"], "anterior", 179735.0]]


def test_guion_entre_dos_lineas_no_es_desalineado():
    # dos lineas vecinas, una con guion: monto corrido y cuentas cruzadas se ven igual -> lo decide el 03j
    fila = lambda g, c, a: dict(rut="X", anio=2012, estado="ESF", pagina=5, codigo=c, glosa=g, actual=a,
                                anterior=None, formato=None, glosa_de=None, monto_de=None, rotulo=None, ocr=False,
                                metodo="espacial")
    CI, OC = "CuentasPorCobrarAIntermediarios", "OtrasCuentasPorCobrar"
    r = pd.DataFrame([fila("Cuentas por cobrar a intermediarios", CI, 289032.0), fila("Otras cuentas por cobrar", OC, 0.0)])
    vx = {("X", 2012, "ESF", CI, "actual"): 0.0, ("X", 2012, "ESF", OC, "actual"): 289032.0}
    assert m.desalineado_columna(r, vx, frozenset({"TotalActivo"})).empty
    assert len(m.desalineado_columna(r.assign(actual=[289032.0, None]), vx)) == 1     # en blanco: si
