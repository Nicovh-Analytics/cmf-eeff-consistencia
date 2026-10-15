"""Mira las coordenadas reales de las palabras en la pagina del EFE (no va al repo).
Uso: python herramientas/diag_coords.py <rut> <anio> [<rut> <anio> ...]

Imprime cada linea reconstruida por altura (top) con sus palabras como
texto@x1 (borde derecho). Los montos van alineados a la derecha, asi que
las columnas deberian verse como x1 que se repiten de linea en linea."""
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pdfplumber

res = pd.read_csv("data/procesado/cruce_resumen.csv", dtype={"rut": str})
RE_EFE = re.compile(r"flujos?\s+de\s+efectivo", re.I)
RE_NUM = re.compile(r"[\d()\-.]")


def pagina_efe(rut, anio):
    r = res[(res.rut == rut) & (res.anio == anio)].iloc[0]
    pdf = Path("data/archivos") / rut / str(anio) / r["pdf"]
    datos = json.load(open(Path("data/texto_pdf") / rut / str(anio) / (Path(r["pdf"]).stem + ".json"), encoding="utf-8"))
    pags = [int(p) for p in str(r["paginas_estados"]).split(",") if p.strip().isdigit()]
    # la pagina de estados con el titulo del EFE y mas montos
    cand = [p for p in pags if RE_EFE.search(datos["paginas"][p - 1])]
    p = max(cand or pags, key=lambda q: len(re.findall(r"\d{1,3}(?:\.\d{3})+", datos["paginas"][q - 1])))
    return pdf, p


for rut, anio in zip(sys.argv[1::2], map(int, sys.argv[2::2])):
    pdf, p = pagina_efe(rut, anio)
    with pdfplumber.open(pdf) as doc:
        page = doc.pages[p - 1].dedupe_chars()
        palabras = page.extract_words(x_tolerance=3, y_tolerance=3)
        print(f"\n=== {rut} {anio}  {pdf.name}  pagina {p}  ancho={page.width:.0f} ===")
    lineas = {}
    for w in palabras:
        lineas.setdefault(round(w["top"] / 3), []).append(w)
    for k in sorted(lineas)[:60]:
        ws = sorted(lineas[k], key=lambda w: w["x0"])
        glosa = " ".join(w["text"] for w in ws if not RE_NUM.fullmatch(w["text"][:1] or "x"))[:45]
        nums = "  ".join(f"{w['text']}[{w['x0']:.1f}-{w['x1']:.1f}]" for w in ws if RE_NUM.match(w["text"]))
        print(f"{ws[0]['top']:6.0f} | {glosa:<45} | {nums}")