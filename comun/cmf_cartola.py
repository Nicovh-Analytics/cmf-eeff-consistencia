"""
Lector de la "Cartola diaria por fondo" de la CMF: el envio diario de cada AGF (valor cuota, patrimonio,
cuotas, participes, remuneraciones), un .txt separado por ";" con una fila por fondo, fecha y serie.

    RUN_ADM; NOM_ADM; RUN_FM; FECHA_INF (aaaammdd); ACTIVO_TOT (del fondo, se repite en cada serie);
    MONEDA ($$ pesos, PROM dolares); ...; SERIE; CUOTAS_APORTADAS; CUOTAS_RESCATADAS; CUOTAS_EN_CIRCULACION;
    VALOR_CUOTA; PATRIMONIO_NETO (en la moneda, no en miles); NUM_PARTICIPES; ...; REM_FIJA; REM_VARIABLE;
    GASTOS_AFECTOS; GASTOS_NO_AFECTOS; COMISION_INVERSION; COMISION_RESCATE; FACTOR DE AJUSTE; FACTOR DE REPARTO

Se baja a mano (tiene captcha), una por anio: fondo "Todos", inicio = termino = 31/12/aaaa.
"""
from pathlib import Path

import pandas as pd

NUM = ["ACTIVO_TOT", "CUOTAS_APORTADAS", "CUOTAS_RESCATADAS", "CUOTAS_EN_CIRCULACION", "VALOR_CUOTA",
       "PATRIMONIO_NETO", "NUM_PARTICIPES", "REM_FIJA", "REM_VARIABLE"]


def leer(ruta) -> pd.DataFrame:
    d = pd.read_csv(ruta, sep=";", dtype=str, encoding="latin1")
    d.columns = [c.strip() for c in d.columns]
    for c in NUM:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["fecha"] = pd.to_datetime(d["FECHA_INF"], format="%Y%m%d", errors="coerce")
    return pd.DataFrame({"rut": d["RUN_FM"].str.strip(), "rut_agf": d["RUN_ADM"].str.strip(), "fecha": d["fecha"],
                         "anio": d["fecha"].dt.year, "serie": d["SERIE"].astype(str).str.strip().str.upper(),
                         "moneda": d["MONEDA"].str.strip(), "activo_tot": d["ACTIVO_TOT"],
                         "cuotas": d["CUOTAS_EN_CIRCULACION"], "valor_cuota": d["VALOR_CUOTA"],
                         "patrimonio": d["PATRIMONIO_NETO"], "participes": d["NUM_PARTICIPES"],
                         "rem_fija": d["REM_FIJA"], "rem_variable": d["REM_VARIABLE"]})


def cargar(carpeta: Path) -> pd.DataFrame:
    """Todas las cartolas de la carpeta; por fondo, anio y serie, la fecha mas cercana al cierre (si se bajo
    tambien el ultimo dia habil por fondos que no informan el 31)."""
    partes = [leer(f).assign(archivo=f.name) for f in sorted(Path(carpeta).glob("*.txt"))]
    if not partes:
        return pd.DataFrame(columns=["rut", "rut_agf", "fecha", "anio", "serie", "moneda", "activo_tot", "cuotas",
                                     "valor_cuota", "patrimonio", "participes", "rem_fija", "rem_variable", "archivo"])
    v = pd.concat(partes, ignore_index=True)
    v = v[v["fecha"].dt.month == 12]
    return (v.sort_values("fecha").drop_duplicates(["rut", "anio", "serie"], keep="last")
             .reset_index(drop=True))
