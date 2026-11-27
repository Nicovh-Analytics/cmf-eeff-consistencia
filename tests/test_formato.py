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
    fila = lambda c, a: dict(rut="X", anio=2020, estado="EFE", pagina=5, codigo=c, glosa="", actual=a, anterior=None,
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
