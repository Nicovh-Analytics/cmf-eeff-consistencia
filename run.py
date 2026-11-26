"""Corre el pipeline por etapas.

    python run.py --lista             # muestra las etapas
    python run.py                     # corre las etapas automáticas, en orden
    python run.py --solo 04 07        # solo esas
    python run.py --desde 03b         # desde esa etapa hasta el final
    python run.py --solo 01           # etapas manuales: solo si se piden
"""

import argparse
import subprocess
import sys
import time
import os
from pathlib import Path

from config import CMF_HOME

RAIZ = Path(__file__).resolve().parent

# (id, script, descripcion, automatica)
ETAPAS = [
("01",  "extraccion/01_recolector.py",                 "descarga XML/PDF desde CMF (red, lento)",        False, []),
("02",  "extraccion/02_parser.py",                     "XML -> tablas en procesado/",                    True,  []),
("07",  "validaciones/continuidad/07_continuidad.py",  "XML: continuidad e identidades oficiales",       True,  []),
("03",  "validaciones/fidelidad/03_cruce_PDF.py",      "cruce XML vs PDF (texto)",                       True,  []),
("03a", "validaciones/fidelidad/03a_coordenadas.py",   "coordenadas del PDF",                            True,  []),
("03o", "validaciones/fidelidad/03a_ocr.py",           "OCR de paginas imagen (requiere Tesseract)",     True,  []),
("03b", "validaciones/estructura/03b_estructura.py",   "subtotales del PDF (footing)",                   True,  []),
("03c", "validaciones/estructura/03c_identidades.py",  "identidades entre estados del PDF",              True,  []),
("03d", "validaciones/estructura/03d_ecp.py",          "ECP leido desde el PDF (series y total)",        True,  []),
("03e", "validaciones/estructura/03e_comparativos.py", "4 versiones: PDF/XML de t y comparativo t+1",    True,  []),
("03f", "validaciones/fidelidad/03f_documento.py",     "documento: periodo, PDF sin estados",            True,  []),
("03g", "validaciones/estructura/03g_localizacion.py", "cual cifra esta mala si un subtotal no suma",    True,  []),
("03h", "validaciones/formato/03h_formato.py",          "formato de presentacion vs modelo CMF",          True,  []),
("04",  "consolidacion/04_candidatos.py",              "candidatos PDF vs XML (espejo)",                 True,  []),
("04b", "consolidacion/04b_casos.py",                  "casos por linea con sus 4 versiones",            True,  []),
("04c", "consolidacion/04c_casos_unicos.py",           "conteo unico de casos",                          True,  []),
("04d", "consolidacion/04d_perfil_estado.py",          "escalera de verificacion por estado y AGF",      True,  []),
("05",  "consolidacion/05_resumen.py",                 "cifras de portada v1",                           True,  []),
("06",  "consolidacion/06_ficha.py",                   "fichas de verificacion (requiere muestra)",      False, ["--muestra"]),
]
IDS = [e[0] for e in ETAPAS]


def correr(script: str, args=()) -> int:
    t0 = time.time()
    print(f"\n=== {script} ===", flush=True)
    env = {**os.environ, "PYTHONPATH": str(RAIZ)}
    rc = subprocess.run([sys.executable, script, *args], cwd=RAIZ, env=env).returncode
    print(f"--- {script}: {'OK' if rc == 0 else f'ERROR ({rc})'} en {time.time() - t0:.0f}s", flush=True)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--lista", action="store_true")
    ap.add_argument("--solo", nargs="+", choices=IDS)
    ap.add_argument("--desde", choices=IDS)
    args = ap.parse_args()

    if args.lista:
        for i, s, d, auto, _ in ETAPAS:
            print(f"{i:>4}  {s:<22} {d}{'' if auto else '   [manual]'}")
        return 0

    if args.solo:
        sel = [e for e in ETAPAS if e[0] in args.solo]
    elif args.desde:
        sel = [e for e in ETAPAS[IDS.index(args.desde):] if e[3]]
    else:
        sel = [e for e in ETAPAS if e[3]]

    if not CMF_HOME.exists():
        print(f"CMF_HOME no existe: {CMF_HOME}")
        return 1
    print(f"datos: {CMF_HOME}")

    for _, script, _, _, extra in sel:
        if correr(script, extra) != 0:
            print("pipeline detenido")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())