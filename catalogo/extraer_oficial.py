"""
Extrae del generador oficial del XML (CMF, Circular 1997, fondos mutuos) los codigos del modelo, el
signo esperado de cada linea y las identidades que la planilla calcula por formula.

La planilla .xls viene cifrada con la clave de solo lectura por defecto de Excel: se abre y se guarda
como .xlsx (Excel: Guardar como; LibreOffice: soffice --headless --convert-to xlsx). Se lee con
openpyxl, que conserva las formulas.

Uso:
    python catalogo/extraer_oficial.py <generador.xlsx>
-> catalogo/fm/oficial/codigos.csv      estado, metodo, fila, codigo, por_serie, signo, glosa, espacio_final
   catalogo/fm/oficial/identidades.csv  estado, metodo, total, partes, alcance, formula

Alcance de una identidad: 'columna' (total y cada serie), o 'suma_series' (la columna Total Series del
ECP es la suma de las series: una identidad por fila).
"""
import csv
import re
import sys
from pathlib import Path

import openpyxl

SALIDA = Path(__file__).resolve().parent / "fm" / "oficial"
SECCIONES = [  # (texto del titulo en la columna A, estado, metodo)
    (r"^1\. ESTADO DE SITUACION", "ESF", ""),
    (r"^2\. ESTADO DE RESULTADOS", "ERI", ""),
    (r"^3\. ESTADO DE CAMBIOS", "ECP", ""),
    (r"^4\. ESTADO DE FLUJOS? DE EFECTIVO - METODO DIRECTO", "EFE", "directo"),
    (r"^4\. ESTADO DE FLUJOS? DE EFECTIVO - METODO INDIRECTO", "EFE", "indirecto"),
]
RE_REF = re.compile(r"([+-]?)\s*([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?")


def signo(glosa: str) -> str:
    g = glosa.replace(" ", "")
    return "+-" if "(+ó-)" in g or "(+o-)" in g else "-" if "(-)" in g else "+" if "(+)" in g else ""


def terminos(formula: str):
    """'=SUM(C29:C35)' -> [(+1, 29), ..., (+1, 35)]; '=+C36-C44' -> [(+1, 36), (-1, 44)]"""
    f = formula.lstrip("=")
    suma = f.upper().startswith("SUM(")
    out = []
    for s, c1, f1, c2, f2 in RE_REF.findall(f[4:-1] if suma else f):
        sg = -1 if s == "-" else 1
        out += [(sg, r) for r in range(int(f1), int(f2) + 1)] if f2 else [(sg, int(f1))]
    return out


def main(ruta):
    ws = openpyxl.load_workbook(ruta).worksheets[0]
    sec, vistos_ecp, filas_cod, codigos, ident = None, False, {}, [], []
    for r in range(1, ws.max_row + 1):
        a = str(ws.cell(r, 1).value or "").strip()
        for rx, est, met in SECCIONES:
            if re.search(rx, a):
                if est == "ECP" and vistos_ecp:     # segundo bloque del ECP: la columna anterior, repetida
                    sec = None
                    break
                vistos_ecp |= est == "ECP"
                sec = (est, met)
                break
        if sec is None:
            continue
        est, met = sec
        if est == "ECP":
            pares = [(ws.cell(r, 21).value, ""), (ws.cell(r, 20).value, "si")]      # U total, T por serie
        else:
            pares = [(ws.cell(r, 6).value, "")]
        for cod, serie in pares:
            if isinstance(cod, str) and re.fullmatch(r"[A-Z][a-z][A-Za-z0-9]{2,}", cod.strip()):   # no rotulos ("S4", "Total Series")
                codigos.append(dict(estado=est, metodo=met, fila=r, codigo=cod.strip(), por_serie=serie,
                                    signo=signo(a), glosa=re.sub(r"\s+", " ", a),
                                    espacio_final="si" if cod != cod.strip() else ""))
                if not serie:
                    filas_cod[(est, met, r)] = cod.strip()
    cod_de = lambda est, met, fila: filas_cod.get((est, met, fila))

    for c in codigos:
        if c["por_serie"]:
            continue
        est, met, r = c["estado"], c["metodo"], c["fila"]
        f = ws.cell(r, 3).value
        if isinstance(f, str) and f.startswith("="):
            partes = [(s, cod_de(est, met, fr)) for s, fr in terminos(f)]
            if all(p for _, p in partes):
                ident.append(dict(estado=est, metodo=met, total=c["codigo"],
                                  partes=";".join(f"{'+' if s > 0 else '-'}{p}" for s, p in partes),
                                  alcance="columna", formula=f))
        if est == "ECP":
            fr = ws.cell(r, 18).value                                   # R: Total Series
            if isinstance(fr, str) and re.fullmatch(r"=SUM\(C\d+:Q\d+\)", fr):
                ident.append(dict(estado=est, metodo=met, total=c["codigo"], partes="+suma de las series",
                                  alcance="suma_series", formula=fr))

    SALIDA.mkdir(parents=True, exist_ok=True)
    for nombre, filas in (("codigos.csv", codigos), ("identidades.csv", ident)):
        with open(SALIDA / nombre, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(filas)
    print(f"codigos: {len(codigos)} ({sum(not c['por_serie'] for c in codigos)} sin serie, "
          f"{len({c['codigo'] for c in codigos})} distintos); identidades: {len(ident)} "
          f"({sum(i['alcance'] == 'columna' for i in ident)} por columna, "
          f"{sum(i['alcance'] == 'suma_series' for i in ident)} suma de series) -> {SALIDA}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
