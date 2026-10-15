"""
Extraccion con coordenadas de las paginas de estados (etapa cara, una vez)
=========================================================================

El cache del 03 (data/texto_pdf) guarda solo TEXTO: al leer un EFE hay que
adivinar a que columna pertenece cada monto, si un "2" es nota o digito, etc.
Este script guarda las PALABRAS con su posicion en la pagina, para que el
lector espacial del 03b asigne columnas por geometria y sin usar el XML.

Por cada fondo-anio con paginas de estados detectadas por el 03:
  - abre el PDF, toma solo esas paginas
  - dedupe_chars(): elimina la negrita simulada por sobreimpresion
  - extract_words(): palabras con x0, x1 (bordes), top, bottom
  - guarda data/coords_pdf/{rut}/{anio}/{pdf}.json.gz

Se salta lo ya extraido (salvo que el PDF sea mas nuevo que el cache).
Paralelo como la etapa 1 del 03.

Lee:      data/procesado/cruce_resumen.csv, data/archivos/{rut}/{anio}/FMNO*.pdf
Escribe:  data/coords_pdf/...
"""

import gzip
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DIR_ARCHIVOS = BASE_DIR / "data" / "archivos"
DIR_PROC = BASE_DIR / "data" / "procesado"
DIR_COORDS = BASE_DIR / "data" / "coords_pdf"
N_PROCESOS = max(1, (os.cpu_count() or 2) - 2)
VERSION = 1


def ruta_cache(rut, anio, pdf):
    return DIR_COORDS / str(rut) / str(anio) / (Path(pdf).stem + ".json.gz")


def extraer(args):
    """Corre en un proceso aparte (funcion de nivel superior por Windows)."""
    import pdfplumber

    rut, anio, pdf, paginas = args
    ruta_pdf = DIR_ARCHIVOS / str(rut) / str(anio) / pdf
    destino = ruta_cache(rut, anio, pdf)
    salida = {"pdf": pdf, "version": VERSION, "error": None, "paginas": {}}
    try:
        with pdfplumber.open(ruta_pdf) as doc:
            for p in paginas:
                if not 1 <= p <= len(doc.pages):
                    continue
                page = doc.pages[p - 1].dedupe_chars()
                palabras = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
                salida["paginas"][str(p)] = {
                    "ancho": round(page.width, 1),
                    # [texto, x0, x1, top, bottom]: listas en vez de dicts -> ~3x menos espacio
                    "palabras": [[w["text"], round(w["x0"], 1), round(w["x1"], 1),
                                  round(w["top"], 1), round(w["bottom"], 1)] for w in palabras],
                }
    except Exception as e:  # noqa: BLE001 - se registra y se sigue
        salida["error"] = f"{type(e).__name__}: {e}"[:300]

    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".part")
    with gzip.open(temporal, "wt", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False)
    temporal.replace(destino)       # escritura atomica
    return "error" if salida["error"] else "ok"


def main():
    res = pd.read_csv(DIR_PROC / "cruce_resumen.csv", dtype={"rut": str})
    res = res[res["paginas_estados"].notna() & res["pdf"].notna()]
    tareas = []
    for r in res.itertuples(index=False):
        paginas = [int(p) for p in str(r.paginas_estados).split(",") if p.strip().isdigit()]
        ruta_pdf = DIR_ARCHIVOS / str(r.rut) / str(r.anio) / r.pdf
        destino = ruta_cache(r.rut, r.anio, r.pdf)
        if not paginas or not ruta_pdf.exists():
            continue
        if destino.exists() and destino.stat().st_mtime >= ruta_pdf.stat().st_mtime:
            continue                        # ya extraido y el PDF no cambio
        tareas.append((r.rut, r.anio, r.pdf, paginas))

    print(f"fondo-anio con paginas de estados: {len(res)} | por extraer: {len(tareas)} "
          f"| procesos: {N_PROCESOS}")
    if not tareas:
        return 0
    inicio, hechos, errores = time.time(), 0, 0
    with ProcessPoolExecutor(max_workers=N_PROCESOS) as ex:
        for fut in as_completed([ex.submit(extraer, t) for t in tareas]):
            hechos += 1
            errores += fut.result() == "error"
            if hechos % 200 == 0 or hechos == len(tareas):
                seg = time.time() - inicio
                resta = seg / hechos * (len(tareas) - hechos)
                print(f"  {hechos}/{len(tareas)}  errores={errores}  "
                      f"{seg/60:.1f} min, faltan ~{resta/60:.1f} min", flush=True)
    print(f"listo: {DIR_COORDS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())