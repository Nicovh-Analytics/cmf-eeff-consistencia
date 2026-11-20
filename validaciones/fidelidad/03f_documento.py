"""
03f: el PDF y el XML de un fondo-anio, son el mismo documento?
==============================================================

Los chequeos de fidelidad comparan el PDF con el XML linea a linea. Si uno de los dos no es el
documento de ese fondo-anio, cada linea difiere y el error se cuenta muchas veces (o ninguna: sin
ninguna cifra en comun, el cruce y las identidades no encuentran pares). Aqui se mira el documento
completo, por conjuntos de montos (>= 1.000, sin anios), sin emparejar cuentas:

  normal       montos del PDF actual que estan en el XML actual
  adelantado   montos del PDF anterior que estan en el XML actual
  xml_repite   montos del XML actual (t) que estan en el XML actual de t-1
  vecinos      el PDF y el XML contra los XML de t-1 y t+1 del mismo fondo

Tipos (solo con normal < 0,4 y >= 5 montos):
  xml_periodo_desfasado  el XML de t trae las cifras de t-1 (repite el XML anterior con las
                         fechas de t): el comparativo del PDF es el actual del XML.   -> error XML
  xml_no_corresponde     el PDF calza con los XML vecinos (su actual con el comparativo del XML
                         de t+1, o su comparativo con el XML de t-1) y el XML de t con nada. -> error XML
  pdf_no_corresponde     el XML de t calza con sus vecinos y el PDF con ninguno.    -> error PDF
  sin_explicar           resto (lectura: primer anio NIIF, OCR)                     -> no es senal
Con normal < 0,1 y >= 20 montos para los "no_corresponde": con pocos montos o lectura parcial
(primer anio NIIF: 3 columnas en el ESF) la fraccion baja sin que el documento sea otro.

Revision (2026-11-11): 4 xml_periodo_desfasado (3 de un mismo anio; el XML trae las fechas del
periodo y las cifras del anterior), 1 xml_no_corresponde y 1 pdf_no_corresponde (el PDF es el de otro
fondo de la misma AGF), contra 4.469 normales; los 6 confirmados a mano.

PDF sin estados: hay PDF pero ningun estado ubicado (ni subtotales del 03b, ni lineas del
03c, ni bloques del ECP del 03d): solo notas (precision 04c: un PDF 2011 con solo notas explicativas
salia como diferencias PDF/XML por linea). Se lista aparte para revisar: con OCR ilegible pasa lo
mismo sin que el documento este incompleto (columna ocr).

Lee:      renglones_pdf.csv (03b), encabezados.csv, cuentas.csv, estructura_efe.csv (03b),
          lineas_03c.csv (03c), ecp_bloques.csv (03d), cruce_resumen.csv
Escribe:  data/procesado/documento_periodo.csv   1 fila por fondo-anio con normal < 0,4
          data/procesado/pdf_sin_estados.csv     PDF sin ningun estado ubicado
"""
import bisect
import sys

import pandas as pd

from config import CMF_HOME

P = CMF_HOME / "procesado"
MIN_MONTO = 1000
MIN_N = 5
MIN_N_AJENO = 20
UMBRAL = 0.6
TOL = 2


def en(vals, ref):
    """Fraccion de vals que esta en ref (+- TOL); None sin vals o sin ref."""
    if not vals or not ref:
        return None
    r = sorted(ref)
    hit = 0
    for v in vals:
        i = bisect.bisect_left(r, v - TOL)
        hit += i < len(r) and r[i] <= v + TOL
    return hit / len(vals)


def montos(s):
    """Materiales y sin anios (encabezados leidos como monto: coinciden en cualquier fondo)."""
    return [abs(v) for v in s.dropna() if abs(v) >= MIN_MONTO and not 1990 <= abs(v) <= 2035]


def tipo_de(f):
    if f["normal"] >= 1 - UMBRAL:
        return "normal"
    alto = lambda k: (f[k] or 0) >= UMBRAL
    if alto("adelantado") and alto("xml_repite"):
        return "xml_periodo_desfasado"
    if f["normal"] < 0.1 and f["n_pdf"] >= MIN_N_AJENO:
        pdf_vec = alto("pdf_en_xml_siguiente_ant") or alto("pdf_ant_en_xml_previo")
        xml_vec = alto("xml_en_xml_siguiente_ant") or alto("xml_ant_en_xml_previo")
        if pdf_vec and not xml_vec:
            return "xml_no_corresponde"
        if xml_vec and not pdf_vec:
            return "pdf_no_corresponde"
    return "sin_explicar"


def verdad(s):
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "si", "sí", "1.0"])


def sin_estados(l):
    """Fondo-anio con PDF y ningun estado ubicado por el 03b, el 03c ni el 03d."""
    est = pd.read_csv(P / "estructura_efe.csv", dtype={"rut": str}, usecols=["rut", "anio", "ubicado", "pagina_ocr"])
    l3c = pd.read_csv(P / "lineas_03c.csv", dtype={"rut": str}, usecols=["rut", "anio", "pdf"])
    ecp = pd.read_csv(P / "ecp_bloques.csv", dtype={"rut": str}, usecols=["rut", "anio"])
    con = (set(map(tuple, est[verdad(est["ubicado"])][["rut", "anio"]].values))
           | set(map(tuple, l3c[l3c["pdf"].notna()][["rut", "anio"]].values))
           | set(map(tuple, ecp[["rut", "anio"]].values)))
    # base: todos los fondo-anio con PDF (un PDF sin paginas de estados puede no tener renglones del 03b)
    cr = pd.read_csv(P / "cruce_resumen.csv", dtype={"rut": str},
                     usecols=["rut", "anio", "pdf", "pdf_paginas", "paginas_estados", "pct_encontrado"])
    cr = cr[cr["pdf"].notna()].drop(columns="pdf")
    d = cr[[(r, a) not in con for r, a in zip(cr["rut"], cr["anio"])]]
    n = l.groupby(["rut", "anio"]).size().rename("renglones").reset_index()
    ocr = est.assign(o=est["pagina_ocr"].notna() & (est["pagina_ocr"].astype(str) != "")) \
             .groupby(["rut", "anio"])["o"].any().rename("ocr").reset_index()
    d = d.merge(n, on=["rut", "anio"], how="left").merge(ocr, on=["rut", "anio"], how="left")
    return d.assign(renglones=d["renglones"].fillna(0).astype(int))


def main():
    l = pd.read_csv(P / "renglones_pdf.csv", dtype={"rut": str}, usecols=["rut", "anio", "actual", "anterior", "metodo"])
    l = l[l["metodo"] != "encabezado"]
    enc = pd.read_csv(P / "encabezados.csv", dtype={"rut": str})
    enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "archivo"]]
    cta = pd.read_csv(P / "cuentas.csv", usecols=["archivo", "contexto", "serie", "valor"], dtype={"serie": str})
    cta = cta[cta["serie"].isna() & cta["valor"].notna()].merge(enc, on="archivo")
    cta["v"] = cta["valor"].abs()
    cta = cta[(cta["v"] >= MIN_MONTO) & ~cta["v"].between(1990, 2035)]
    X = {k: set(g["v"]) for k, g in cta.groupby(["rut", "anio", "contexto"])}
    A, B = "PeriodoActual", "PeriodoAnterior"

    filas = []
    for (rut, anio), g in l.groupby(["rut", "anio"]):
        pa, pb = montos(g["actual"]), montos(g["anterior"])
        xa, xb = X.get((rut, anio, A)), X.get((rut, anio, B))
        if len(pa) < MIN_N or not xa:
            continue
        f = dict(rut=rut, anio=anio, n_pdf=len(pa), normal=en(pa, xa),
                 adelantado=en(pb, xa) if len(pb) >= MIN_N else None,
                 xml_repite=en(sorted(xa), X.get((rut, anio - 1, A))),
                 pdf_en_xml_siguiente_ant=en(pa, X.get((rut, anio + 1, B))),
                 pdf_ant_en_xml_previo=en(pb, X.get((rut, anio - 1, A))) if len(pb) >= MIN_N else None,
                 xml_en_xml_siguiente_ant=en(sorted(xa), X.get((rut, anio + 1, B))),
                 xml_ant_en_xml_previo=en(sorted(xb), X.get((rut, anio - 1, A))) if xb else None)
        f["tipo"] = tipo_de(f)
        if f["tipo"] != "normal":
            filas.append(f)
    d = pd.DataFrame(filas, columns=["rut", "anio", "tipo", "n_pdf", "normal", "adelantado", "xml_repite",
                                     "pdf_en_xml_siguiente_ant", "pdf_ant_en_xml_previo",
                                     "xml_en_xml_siguiente_ant", "xml_ant_en_xml_previo"])
    d.to_csv(P / "documento_periodo.csv", index=False, encoding="utf-8-sig")

    n = l[["rut", "anio"]].drop_duplicates().shape[0]
    print(f"fondo-anio con renglones del PDF: {n}; con el PDF actual poco presente en el XML (< 40%): {len(d)}")
    print(d["tipo"].value_counts().to_string() if len(d) else "  ninguno")
    pd.set_option("display.width", 220)
    if len(d):
        print("\n" + d.sort_values(["tipo", "rut", "anio"]).round(2).to_string(index=False))
    print(f"\nsalida: {P / 'documento_periodo.csv'}")

    se = sin_estados(l)
    se.to_csv(P / "pdf_sin_estados.csv", index=False, encoding="utf-8-sig")
    print(f"\nPDF sin ningun estado ubicado (03b, 03c, 03d): {len(se)}  (con OCR: {int(se['ocr'].fillna(False).sum())})")
    if len(se):
        print(se.sort_values(["anio", "rut"]).to_string(index=False))
    print(f"salida: {P / 'pdf_sin_estados.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())