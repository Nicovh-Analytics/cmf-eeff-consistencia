"""03j: de que lado esta el cruce de montos entre dos cuentas."""
import importlib

import pandas as pd

m = importlib.import_module("validaciones.testigos.03j_cruces")
TA, AN, EF, TP = "TotalActivo", "ActivoNetoAtribuibleALosParticipes", "EfectivoYEfectivoEquivalente", "TotalPasivo"
OT, RP = "OtrasCuentasPorCobrar", "RescatesPorPagar"
TOT = frozenset({TA, TP, AN})


def filas(anio, valores, ctx="PeriodoActual"):
    return [dict(archivo=f"X_{anio}", rut="X", anio=anio, contexto=ctx, estado="ESF", codigo=c, serie="", valor=v,
                 pagina=3, ocr=False, codigo_repetido=False) for c, v in valores.items()]


def correr(xml, pdf):
    x, vx = m.valores_xml(pd.DataFrame(xml), {})
    p = m.valores_pdf(pd.DataFrame(pdf))
    vp = p.set_index(["rut", "anio", "contexto", "estado", "codigo"])["valor"].to_dict()
    return m.votar(m.cruzados(p, x, vx, totales=TOT), x, vx, vp)


def test_xml_cruzado_por_identidad():
    # el XML trae el total activo y el activo neto cruzados solo en el actual: con la lectura del PDF cuadra
    c = correr(filas(2023, {EF: 100.0, TA: 90.0, TP: 10.0, AN: 100.0}),
               filas(2023, {EF: 100.0, TA: 100.0, TP: 10.0, AN: 90.0}))
    assert set(c["lado"]) == {"XML"} and set(c["tipo"]) == {"intercambio"} and set(c["columna"]) == {"actual"}


def test_xml_cruzado_por_vecino():
    # cruce dentro de la misma suma: la identidad no vota; el XML de t+1 trae lo que el PDF de t imprime
    xml = filas(2023, {EF: 30.0, OT: 70.0, TA: 100.0}) + filas(2024, {EF: 70.0, OT: 30.0}, "PeriodoAnterior")
    c = correr(xml, filas(2023, {EF: 70.0, OT: 30.0, TA: 100.0}))
    assert set(c["voto_identidad"]) == {""} and set(c["lado"]) == {"XML"}


def test_persistente_y_linea_contra_total():
    # cada documento igual a si mismo en t+1: la glosa del PDF y la cuenta del XML difieren de forma estable
    xml = filas(2023, {RP: 40.0, OT: 60.0, TP: 100.0}) + filas(2024, {RP: 40.0, OT: 60.0}, "PeriodoAnterior")
    pdf = filas(2023, {RP: 60.0, OT: 40.0, TP: 100.0}) + filas(2024, {RP: 60.0, OT: 40.0}, "PeriodoAnterior")
    assert set(correr(xml, pdf)["lado"]) == {"persistente"}
    # una linea con la cifra del total (linea sola = subtotal) no es cruce
    assert correr(filas(2023, {EF: 5.0, TA: 100.0}), filas(2023, {EF: 100.0, TA: 100.0})).empty


def test_04c_senales_cruces(tmp_path, monkeypatch):
    c04 = importlib.import_module("consolidacion.04c_casos_unicos")
    monkeypatch.setattr(c04, "P", tmp_path)
    base = dict(rut="X", anio=2019, estado="ESF", columna="actual", codigo=OT, monto_de=EF, pagina=3, xml_a=0.0,
                xml_vecino=None, pdf_vecino=None)
    pd.DataFrame([dict(base, pdf=5000.0, lado="XML"), dict(base, columna="anterior", pdf=5.0, lado="XML"),
                  dict(base, anio=2020, pdf=900.0, lado="persistente"),
                  dict(base, anio=2021, pdf=900.0, lado="sin_testigo")]).to_csv(tmp_path / "cruces.csv", index=False)
    pd.DataFrame([dict(rut="X", anio=a, moneda="$$", es_ultimo_envio=True) for a in (2019, 2020, 2021)]
                 ).to_csv(tmp_path / "encabezados.csv", index=False)
    s = c04.senales_cruces()
    assert s["clase"].tolist() == ["error", "inmaterial", "presentacion", "revisar"]
    assert s["documento"].tolist() == ["XML", "XML", "PDF", "PDF/XML"]


def test_por_glosa(tmp_path):
    # la glosa contradictoria esta en el PDF del anio vecino (testigo de la columna actual)
    c = pd.DataFrame([dict(rut="X", anio=2017, estado="EFE", columna="actual", codigo="OtrosIngresosDeOperacion",
                           monto_de="MontosRecibidosDeSociedadAdministradoraEIntermediarios", lado="XML"),
                      dict(rut="X", anio=2015, estado="EFE", columna="actual", codigo="OtrosIngresosDeOperacion",
                           monto_de="MontosRecibidosDeSociedadAdministradoraEIntermediarios", lado="XML")])
    pd.DataFrame([dict(rut="X", anio=2018, estado="EFE", codigo="OtrosIngresosDeOperacion", tipo="glosa_contradictoria")]
                 ).to_csv(tmp_path / "formato.csv", index=False)
    assert m.por_glosa(c, tmp_path / "formato.csv")["lado"].tolist() == ["glosa_contradictoria", "XML"]
