"""Coordenadas de la pagina del ECP (estado de cambios en el activo neto), para disenar su lector.

Uso:
  PYTHONPATH=. python herramientas/diag_ecp.py --buscar            fondos de ejemplo segun numero de series
  PYTHONPATH=. python herramientas/diag_ecp.py <rut> <anio> [p=N]  coordenadas de la pagina del ECP

A diferencia de diag_coords, muestra TODAS las palabras de la mitad derecha de la pagina con su
posicion (x0-x1): en el ECP las columnas son series y sus nombres van en el encabezado.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pdfplumber

from config import CMF_HOME

P = CMF_HOME / "procesado"
RE_ECP = re.compile(r"cambios?\s+en\s+(el\s+|los\s+)?activos?\s+netos?", re.I)
RE_MONTO = re.compile(r"\d{1,3}(?:\.\d{3})+")
COD_CIERRE = "ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuotaPorSerie"


def buscar():
    """Ejemplos de fondo-anio (2016+, cruce ok) por numero de series del ECP."""
    enc = pd.read_csv(P / "encabezados.csv", dtype={"rut": str})
    enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "archivo"]]
    c = pd.read_csv(P / "cuentas.csv", usecols=["archivo", "contexto", "codigo", "serie"], dtype={"serie": str})
    c = c[(c["codigo"] == COD_CIERRE) & (c["contexto"] == "PeriodoActual")]
    n = c.groupby("archivo")["serie"].nunique().rename("series").reset_index().merge(enc, on="archivo")
    res = pd.read_csv(P / "cruce_resumen.csv", dtype={"rut": str}, usecols=["rut", "anio", "estado"])
    n = n.merge(res[res["estado"] == "ok"], on=["rut", "anio"])
    n = n[n["anio"] >= 2016]
    n["grupo"] = pd.cut(n["series"], [0, 1, 3, 6, 99], labels=["1 serie", "2-3", "4-6", "7+"])
    print(n["grupo"].value_counts().sort_index().to_string(), "\n")
    for g, d in n.groupby("grupo", observed=True):
        ej = d.sample(min(3, len(d)), random_state=1)
        print(f"{g:<8} " + "   ".join(f"{r.rut} {r.anio} ({r.series})" for r in ej.itertuples()))


def pagina_ecp(rut, anio):
    r = res_fila(rut, anio)
    pdf = CMF_HOME / "archivos" / rut / str(anio) / r["pdf"]
    if len(sys.argv) > 3 and sys.argv[3].startswith("p="):
        return pdf, int(sys.argv[3][2:])
    txt = json.load(open(CMF_HOME / "texto_pdf" / rut / str(anio) / (Path(r["pdf"]).stem + ".json"),
                         encoding="utf-8"))["paginas"]
    pags = [int(p) for p in str(r["paginas_estados"]).split(",") if p.strip().isdigit()]
    cand = [p for p in pags if RE_ECP.search(txt[p - 1])] or pags
    return pdf, max(cand, key=lambda q: len(RE_MONTO.findall(txt[q - 1])))


def res_fila(rut, anio):
    res = pd.read_csv(P / "cruce_resumen.csv", dtype={"rut": str, "paginas_estados": str})
    return res[(res["rut"] == rut) & (res["anio"] == anio)].iloc[0]


def mostrar(rut, anio):
    pdf, p = pagina_ecp(rut, anio)
    with pdfplumber.open(pdf) as doc:
        page = doc.pages[p - 1].dedupe_chars()
        ws = page.extract_words(x_tolerance=3, y_tolerance=3)
        ancho = page.width
    print(f"\n=== {rut} {anio}  {pdf.name}  pagina {p}  ancho={ancho:.0f} ===")
    lineas = {}
    for w in ws:
        lineas.setdefault(round(w["top"] / 3), []).append(w)
    for k in sorted(lineas):
        fila = sorted(lineas[k], key=lambda w: w["x0"])
        izq = " ".join(w["text"] for w in fila if w["x1"] <= ancho * 0.40)[:42]
        der = "  ".join(f"{w['text']}[{w['x0']:.0f}-{w['x1']:.0f}]" for w in fila if w["x1"] > ancho * 0.40)
        print(f"{fila[0]['top']:5.0f} | {izq:<42} | {der}")


if __name__ == "__main__":
    if "--buscar" in sys.argv:
        buscar()
    else:
        mostrar(sys.argv[1], int(sys.argv[2]))
