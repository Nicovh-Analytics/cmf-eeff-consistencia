"""
03i: testigo externo, lo que la AGF informa a diario a la CMF (cartola diaria) al 31 de diciembre
=================================================================================================

Cada AGF envia a diario a la CMF, por fondo y serie: valor cuota, cuotas en circulacion, patrimonio neto,
participes, remuneraciones, y el activo total del fondo. Es un dato que no sale de los EEFF: si el
balance del 31 de diciembre no calza con el envio de ese dia, uno de los dos esta mal o hubo un ajuste
posterior al cierre (auditoria). Primero se MIDE la distribucion de las diferencias; no se llama error
a nada todavia.

  activo_total   ACTIVO_TOT de la cartola        vs  total activo del ESF (XML; PDF del 03b)
  activo_neto    suma del patrimonio de las series vs  activo neto del ESF (XML; PDF del 03c)
  serie          patrimonio de la serie          vs  cierre del ECP por serie en el XML
  cuotas         cuotas x valor cuota = patrimonio  (coherencia de la propia cartola)

Fuente: CMF_HOME/externo/cartola/*.txt (cartola diaria, fondo "Todos", 31/12 de cada anio; se baja a
mano, tiene captcha). Sin cartolas, usa los Excel de la consulta "Periodos por Fondo Mutuo"
(externo/valor_cuota/*.xls: patrimonio por serie, sin activo total).

Unidades: la cartola informa en la moneda (pesos, dolares); los EEFF por lo general en miles. La escala
se deduce por fondo-anio de la razon EEFF / cartola (potencia de 10).

Escribe:  testigo_cmf.csv
"""
import math
import re
import sys

import pandas as pd

from comun import cmf_cartola, cmf_valor_cuota
from config import CMF_HOME
from motor import hechos

P = CMF_HOME / "procesado"
EXT = CMF_HOME / "externo"
AN_ESF, TA_ESF = "ActivoNetoAtribuibleALosParticipes", "TotalActivo"
AN_ECP_SERIE = "ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuotaPorSerie"
COLS = ["rut", "anio", "testigo", "serie", "escala", "cmf", "xml", "pdf", "dif_xml", "dif_pdf", "rel_xml", "rel_pdf"]


def escala(ef, cmf):
    """Potencia de 10 de EEFF / CMF (-3 = miles, 0 = unidades); None si no es cercana a una potencia."""
    if not ef or not cmf or pd.isna(ef) or pd.isna(cmf):
        return None
    x = math.log10(abs(ef) / abs(cmf))
    k = round(x)
    return k if abs(x - k) < 0.05 else None


def tramo(rel, dif=None):
    """Tramo de la diferencia relativa. Hasta 1 unidad de los EEFF (un fondo de M$ 248 contra 248,72 de la
    CMF) es el redondeo a miles, no una diferencia."""
    if pd.isna(rel):
        return "sin_dato"
    if dif is not None and pd.notna(dif) and abs(dif) <= 1:
        return "exacto"
    a = abs(rel)
    return ("exacto" if a < 1e-6 else "<0,01%" if a < 1e-4 else "<0,1%" if a < 1e-3 else "<1%" if a < 1e-2
            else ">=1%")


def norm_serie(s):
    """Nombre de serie comparable entre la cartola y el XML: sin espacios ni guiones, en mayusculas."""
    return re.sub(r"[\s\-_.]", "", str(s)).upper()


def patron(cmf, xml, pdf, tol_rel=1e-4):
    """Quien difiere de quien (diferencia > 1 unidad y > 0,01%):
    coinciden | eeff_vs_cmf (PDF = XML, la CMF distinta: ajuste posterior al cierre o error en uno de los dos
    lados) | pdf_distinto (XML = CMF) | xml_distinto (PDF = CMF) | tres_distintos | sin_pdf_*."""
    igual = lambda a, b: pd.notna(a) and pd.notna(b) and (abs(a - b) <= 1 or abs(a - b) <= tol_rel * max(abs(a), abs(b)))
    if pd.isna(cmf) or pd.isna(xml):
        return "sin_dato"
    if pd.isna(pdf):
        return "sin_pdf_coincide" if igual(xml, cmf) else "sin_pdf_xml_vs_cmf"
    if igual(xml, cmf) and igual(pdf, cmf):
        return "coinciden"
    if igual(pdf, xml):
        return "eeff_vs_cmf"
    if igual(xml, cmf):
        return "pdf_distinto"
    if igual(pdf, cmf):
        return "xml_distinto"
    return "tres_distintos"


def fuente():
    """(serie: rut, anio, serie, patrimonio, cuotas, valor_cuota, activo_tot) en la moneda, al cierre."""
    c = cmf_cartola.cargar(EXT / "cartola") if (EXT / "cartola").exists() else None
    if c is not None and len(c):
        print(f"cartola: {c['rut'].nunique()} fondos, anios {sorted(c['anio'].unique())}")
        return c
    v = cmf_valor_cuota.cargar(EXT / "valor_cuota") if (EXT / "valor_cuota").exists() else None
    if v is not None and len(v):
        v = v[v["mes"] == 12].assign(patrimonio=lambda d: d["patrimonio_mm"] * 1e6, activo_tot=float("nan"),
                                     cuotas=float("nan"))
        print(f"valor cuota (Excel): {v['rut'].nunique()} fondos (sin activo total)")
        return v
    return None


def comparar(base, xml, pdf, nombre):
    """base: rut, anio, cmf (en la moneda); xml/pdf: rut, anio, valor (unidad de los EEFF)."""
    t = base.merge(xml.rename(columns={"valor": "xml"}), on=["rut", "anio"], how="left")
    t = t.merge(pdf.rename(columns={"valor": "pdf"}), on=["rut", "anio"], how="left") if pdf is not None else t.assign(pdf=float("nan"))
    t["escala"] = [escala(e, c) for e, c in zip(t["xml"], t["cmf"])]
    t["cmf"] = t["cmf"] * 10.0 ** t["escala"].astype(float)
    t["pdf"] = pd.to_numeric(t["pdf"], errors="coerce")
    t["dif_xml"], t["dif_pdf"] = t["xml"] - t["cmf"], t["pdf"] - t["cmf"]
    t["rel_xml"], t["rel_pdf"] = t["dif_xml"] / t["cmf"], t["dif_pdf"] / t["cmf"]
    return t.assign(testigo=nombre, serie="")


def main():
    c = fuente()
    if c is None:
        print(f"sin cartolas en {EXT / 'cartola'} ni Excel en {EXT / 'valor_cuota'}")
        return 0
    x = hechos.xml()
    x = x[x["contexto"] == "PeriodoActual"]
    sel = lambda cod: x[(x["codigo"] == cod) & (x["serie"] == "")][["rut", "anio", "valor"]]

    # PDF: activo neto (03c) y total activo (03b)
    pdf_an = pdf_ta = None
    if (P / "lineas_03c.csv").exists():
        l = pd.read_csv(P / "lineas_03c.csv", dtype={"rut": str})
        pdf_an = l[(l["linea"] == "activo_neto") & (l["columna"] == "actual")][["rut", "anio", "pdf"]].rename(columns={"pdf": "valor"})
    if (P / "estructura_efe.csv").exists():
        e = pd.read_csv(P / "estructura_efe.csv", dtype={"rut": str}, low_memory=False)
        pdf_ta = e[(e["subtotal"] == "total_activo") & (e["columna"] == "actual") & (e["ubicado"] == True)]
        pdf_ta = pdf_ta[["rut", "anio", "subtotal_pdf"]].rename(columns={"subtotal_pdf": "valor"})

    fa = c.groupby(["rut", "anio"], as_index=False).agg(patrimonio=("patrimonio", "sum"), activo_tot=("activo_tot", "first"))
    an = comparar(fa[["rut", "anio"]].assign(cmf=fa["patrimonio"]), sel(AN_ESF), pdf_an, "activo_neto")
    ta = comparar(fa[["rut", "anio"]].assign(cmf=fa["activo_tot"]), sel(TA_ESF), pdf_ta, "activo_total")

    ecp = x[(x["codigo"] == AN_ECP_SERIE) & (x["serie"] != "")][["rut", "anio", "serie", "valor"]]
    ecp = ecp.assign(serie=ecp["serie"].map(norm_serie)).rename(columns={"valor": "xml"})
    s = c[["rut", "anio", "serie", "patrimonio"]].assign(serie=lambda d: d["serie"].map(norm_serie))
    s = s.merge(ecp, on=["rut", "anio", "serie"], how="left")
    s = s.merge(an[["rut", "anio", "escala"]], on=["rut", "anio"], how="left")
    s["cmf"] = s["patrimonio"] * 10.0 ** s["escala"].astype(float)
    s["dif_xml"] = s["xml"] - s["cmf"]
    s["rel_xml"] = s["dif_xml"] / s["cmf"]
    s["testigo"] = "serie"

    q = c.dropna(subset=["cuotas"]).copy()
    q["cmf"], q["xml"] = q["patrimonio"], q["cuotas"] * q["valor_cuota"]
    q["dif_xml"] = q["xml"] - q["cmf"]
    q["rel_xml"] = q["dif_xml"] / q["cmf"]
    q["testigo"] = "cuotas"

    for d in (an, ta):
        d["patron"] = [patron(a, b, c_) for a, b, c_ in zip(d["cmf"], d["xml"], d["pdf"])]
    out = pd.concat([d.reindex(columns=COLS + ["patron"]) for d in (an, ta, s, q)], ignore_index=True)
    out.to_csv(P / "testigo_cmf.csv", index=False, encoding="utf-8-sig")

    # --- Consola: solo distribucion ---
    pd.set_option("display.width", 200)
    print(f"\nfondo-anio en la fuente: {len(fa)}; con activo neto XML: {an['xml'].notna().sum()}, "
          f"PDF: {an['pdf'].notna().sum()}")
    print("escala EEFF/cartola (potencia de 10):", an["escala"].value_counts(dropna=False).to_dict())
    tab = {}
    for nom, d, r, df in (("activo neto XML", an, "rel_xml", "dif_xml"), ("activo neto PDF", an, "rel_pdf", "dif_pdf"),
                          ("activo total XML", ta, "rel_xml", "dif_xml"), ("activo total PDF", ta, "rel_pdf", "dif_pdf"),
                          ("serie XML", s, "rel_xml", "dif_xml"), ("cuotas x valor cuota", q, "rel_xml", "dif_xml")):
        tab[nom] = pd.Series([tramo(a, b) for a, b in zip(d[r], d[df])]).value_counts()
    print("\ndiferencia relativa con la CMF (filas):")
    print(pd.DataFrame(tab).fillna(0).astype(int).reindex(["exacto", "<0,01%", "<0,1%", "<1%", ">=1%", "sin_dato"])
          .fillna(0).astype(int).to_string())
    print("\npor anio, % de fondo-anio con el activo neto XML exacto o <0,01%:")
    an["ok"] = an["rel_xml"].abs() < 1e-4
    print((an[an["xml"].notna()].groupby("anio")["ok"].mean() * 100).round(1).to_string())
    sx = s[s["xml"].notna()]
    print(f"\nseries: {s['serie'].size} en la cartola de los fondo-anio con XML; con su serie en el ECP del XML: "
          f"{len(sx)}; series del XML sin pareja en la cartola: "
          f"{len(set(zip(ecp['rut'], ecp['anio'], ecp['serie'])) - set(zip(s['rut'], s['anio'], s['serie'])))}")
    print("\nquien difiere de quien (fondo-anio con XML):")
    print(pd.DataFrame({n: d.loc[d["xml"].notna(), "patron"].value_counts() for n, d in
                        (("activo neto", an), ("activo total", ta))}).fillna(0).astype(int).to_string())
    for nom, d in (("activo neto", an), ("activo total", ta)):
        for p in ("eeff_vs_cmf", "pdf_distinto", "xml_distinto", "tres_distintos"):
            x_ = d[d["patron"] == p]
            if len(x_):
                print(f"\n{nom} / {p} ({len(x_)}), los de mayor diferencia:")
                print(x_.assign(a=x_["rel_xml"].abs()).sort_values("a", ascending=False)
                      [["rut", "anio", "cmf", "xml", "pdf", "rel_xml", "rel_pdf"]].head(8).to_string(index=False))
    print(f"\nsalida: {P / 'testigo_cmf.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
