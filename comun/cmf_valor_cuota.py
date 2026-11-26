"""
Lector del Excel de la CMF "Informe por Periodos de Patrimonio, Rentabilidad, Participes y Valor de la
Cuota" (consulta "Periodos por Fondo Mutuo", periodicidad mensual): una fila por mes y serie.

    periodo "DICIEMBRE/2023" | RUN "9084-0" | tipo | administradora | serie | moneda | patrimonio (1) |
    variacion real | % sistema | rentabilidad nominal | participes | variacion | % sistema | valor cuota
    (1) millones de pesos o de la moneda del fondo, en moneda corriente al ultimo dia del mes

Devuelve: rut (sin digito verificador, como el XML), anio, mes, serie, moneda, patrimonio_mm,
participes, valor_cuota.
"""
import re
from pathlib import Path

import pandas as pd

MESES = {m: i + 1 for i, m in enumerate(["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
                                         "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"])}
RE_PERIODO = re.compile(r"^\s*([A-Z]+)/(\d{4})\s*$")
RE_RUN = re.compile(r"^\s*(\d+)-[\dkK]\s*$")


def leer_excel(ruta) -> pd.DataFrame:
    """El .xls de la CMF (formato Excel 97). Requiere xlrd o python-calamine."""
    for motor in ("xlrd", "calamine"):
        try:
            return pd.read_excel(ruta, header=None, engine=motor)
        except ImportError:
            continue
    raise ImportError("para leer el .xls de la CMF: pip install xlrd")


def filas(d: pd.DataFrame) -> pd.DataFrame:
    """Las filas de datos de la hoja (sin encabezado ni notas al pie)."""
    out = []
    for r in d.itertuples(index=False):
        p, run = str(r[0]), str(r[1])
        mp, mr = RE_PERIODO.match(p), RE_RUN.match(run)
        if not (mp and mr) or mp.group(1) not in MESES:
            continue
        out.append(dict(rut=mr.group(1), anio=int(mp.group(2)), mes=MESES[mp.group(1)],
                        serie=str(r[4]).strip().upper(), moneda=str(r[5]).strip(),
                        patrimonio_mm=pd.to_numeric(r[6], errors="coerce"),
                        participes=pd.to_numeric(r[10], errors="coerce"),
                        valor_cuota=pd.to_numeric(r[13], errors="coerce")))
    return pd.DataFrame(out, columns=["rut", "anio", "mes", "serie", "moneda", "patrimonio_mm", "participes",
                                      "valor_cuota"])


def cargar(carpeta: Path) -> pd.DataFrame:
    """Todos los .xls de la carpeta; si un fondo-mes-serie viene en dos archivos, vale el ultimo leido."""
    partes = [filas(leer_excel(f)).assign(archivo=f.name) for f in sorted(Path(carpeta).glob("*.xls*"))]
    if not partes:
        return filas(pd.DataFrame())
    v = pd.concat(partes, ignore_index=True)
    return v.drop_duplicates(["rut", "anio", "mes", "serie"], keep="last").reset_index(drop=True)
