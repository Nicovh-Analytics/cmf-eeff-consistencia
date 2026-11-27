"""03j: de que lado esta el cruce de montos entre dos cuentas."""
import importlib

import pandas as pd

m = importlib.import_module("validaciones.testigos.03j_cruces")
TA, AN, EF, TP = "TotalActivo", "ActivoNetoAtribuibleALosParticipes", "EfectivoYEfectivoEquivalente", "TotalPasivo"


def xml(anio, valores, ctx="PeriodoActual"):
    return [dict(archivo=f"X_{anio}", rut="X", anio=anio, contexto=ctx, estado="ESF", codigo=c, serie="", valor=v)
            for c, v in valores.items()]


def renglones(anio, pares):
    return pd.DataFrame([dict(rut="X", anio=anio, estado="ESF", pagina=3, codigo=a, monto_de=b, monto_de_vecino=False,
                              ocr=False) for a, b in pares])


def test_xml_cruzado_por_identidad():
    # el XML trae el total activo y el activo neto cruzados: con la lectura del PDF cuadran las identidades
    x = pd.DataFrame(xml(2023, {EF: 100.0, TA: 90.0, TP: 10.0, AN: 100.0}))
    r = renglones(2023, [(TA, AN), (AN, TA)])
    c = m.votar(m.cruzados(r), x, pd.DataFrame(columns=x.columns.tolist() + ["codigo_repetido"]), {})
    assert set(c["lado"]) == {"XML"} and set(c["voto_identidad"]) == {"XML"}
    assert set(c["tipo"]) == {"intercambio"}


def test_pdf_cruzado_por_vecino():
    # dos cuentas de la misma suma: la identidad no vota; el PDF de t+1 rotula bien el comparativo
    OT = "OtrasCuentasPorCobrar"
    x = pd.DataFrame(xml(2023, {EF: 30.0, OT: 70.0, TA: 100.0}) + xml(2024, {EF: 30.0, OT: 70.0}, "PeriodoAnterior"))
    p = pd.DataFrame([dict(archivo="X_2024", rut="X", anio=2024, contexto="PeriodoAnterior", estado="ESF", codigo=EF,
                           serie="", valor=30.0, codigo_repetido=False)])
    c = m.votar(m.cruzados(renglones(2023, [(EF, OT), (OT, EF)])), x, p, {})
    act = c[c["columna"] == "actual"]
    assert set(act["voto_identidad"]) == {""} and act["voto_pdf_vecino"].any()
    assert set(act["lado"]) == {"PDF"}
