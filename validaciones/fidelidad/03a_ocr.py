"""
03a_ocr: OCR de las paginas de estados publicadas como imagen
==============================================================

Complemento del 03a para lo que pdfplumber no puede leer:
  - paginas_sin_tabla (fondos con estado "ok" del 03): paginas con el titulo de un
    estado y casi sin texto -> el estado es una imagen.
  - con --sin-texto: PDF escaneados completos (estado "sin_texto" del 03). Se hace
    OCR de las primeras MAX_PAG paginas y se guardan las que tienen el titulo de un
    estado y montos.

Salida: {CMF_HOME}/coords_pdf/{rut}/{anio}/{pdf}.ocr.json.gz, con el mismo formato
del 03a y origen="ocr" por pagina. No toca el cache del 03a; lector_espacial.
cargar_coords une ambos (las paginas con texto tienen prioridad).

Uso:  python run.py --solo 03o                 (paginas imagen de fondos "ok")
      PYTHONPATH=. python validaciones/fidelidad/03a_ocr.py --sin-texto
Si Tesseract no esta instalado, avisa y termina sin error (el pipeline sigue).
"""
import gzip
import json
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from config import CMF_HOME

DIR_PROC = CMF_HOME / "procesado"
DIR_ARCHIVOS = CMF_HOME / "archivos"
DIR_COORDS = CMF_HOME / "coords_pdf"
N_PROCESOS = max(1, (os.cpu_count() or 2) - 2)
MAX_PAG = 15
VERSION = 1
RE_TITULO = re.compile(r"estados?\s+de\s+(situaci[oó]n\s+financiera|resultados?\s+integral"
                       r"|cambios?\s+en\s+(el|los)\s+activos?\s+netos?|flujos?\s+de\s+efectivo)", re.I)
RE_MONTO = re.compile(r"\(?\d{1,3}(?:\.\d{3})+\)?")


def ruta_ocr(rut, anio, pdf):
    return DIR_COORDS / str(rut) / str(anio) / (Path(pdf).stem + ".ocr.json.gz")


def es_pagina_de_estado(datos):
    texto = " ".join(w[0] for w in datos["palabras"])
    return bool(RE_TITULO.search(texto)) and len(RE_MONTO.findall(texto)) >= 5


_LANG = None


def _init():
    global _LANG
    from comun.ocr import configurar
    _LANG = configurar()


def tarea(args):
    from comun.ocr import ocr_pdf
    rut, anio, pdf, paginas, filtrar = args
    salida = {"pdf": pdf, "version": VERSION, "error": None, "lang": _LANG, "paginas": {}}
    try:
        res = ocr_pdf(DIR_ARCHIVOS / str(rut) / str(anio) / pdf, paginas, lang=_LANG)
        salida["paginas"] = {p: d for p, d in res.items() if not filtrar or es_pagina_de_estado(d)}
    except Exception as e:                                   # PDF danado, etc.: queda registrado
        salida["error"] = f"{type(e).__name__}: {e}"
    destino = ruta_ocr(rut, anio, pdf)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".part")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(salida, f)
    tmp.replace(destino)
    return rut, anio, len(salida["paginas"]), salida["error"]


def main():
    try:
        _init()
    except Exception as e:
        print(f"03a_ocr omitido: {e}")
        return 0
    sin_texto = "--sin-texto" in sys.argv
    # str: una sola pagina ("7") se leeria como numero y se perderia
    res = pd.read_csv(DIR_PROC / "cruce_resumen.csv", dtype={"rut": str, "paginas_sin_tabla": str})

    tareas = []
    for r in res.itertuples(index=False):
        if not isinstance(r.pdf, str):
            continue
        if r.estado == "ok" and isinstance(r.paginas_sin_tabla, str) and r.paginas_sin_tabla.strip():
            paginas, filtrar = [int(p) for p in r.paginas_sin_tabla.split(",") if p.strip().isdigit()], False
        elif sin_texto and r.estado == "sin_texto":
            paginas, filtrar = list(range(1, MAX_PAG + 1)), True
        else:
            continue
        pdf = DIR_ARCHIVOS / r.rut / str(r.anio) / r.pdf
        cache = ruta_ocr(r.rut, r.anio, r.pdf)
        if not pdf.exists() or (cache.exists() and cache.stat().st_mtime >= pdf.stat().st_mtime):
            continue
        tareas.append((r.rut, int(r.anio), r.pdf, paginas, filtrar))

    print(f"OCR ({_LANG}): {len(tareas)} fondo-anio por procesar "
          f"({sum(len(t[3]) for t in tareas)} paginas), {N_PROCESOS} procesos")
    t0, hechas, con_error, paginas_ok = time.time(), 0, 0, 0
    with ProcessPoolExecutor(N_PROCESOS, initializer=_init) as ex:
        for fut in as_completed([ex.submit(tarea, t) for t in tareas]):
            rut, anio, n, err = fut.result()
            hechas += 1
            paginas_ok += n
            con_error += bool(err)
            if hechas % 20 == 0 or hechas == len(tareas):
                print(f"  {hechas}/{len(tareas)}  ({time.time() - t0:.0f}s)", flush=True)
    print(f"listo: {paginas_ok} paginas de estados con OCR; {con_error} con error -> {DIR_COORDS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
