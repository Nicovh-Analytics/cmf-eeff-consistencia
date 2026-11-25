"""
Catalogo: conceptos y reglas contables como datos, una sola definicion para todas las etapas.

    catalogo/<entidad>/conceptos.csv   cuentas del modelo: estado, codigo XML, orden, clave corta,
                                       codigo alternativo (EFE indirecto), por serie, glosa del PDF
    catalogo/<entidad>/reglas.csv      identidades: total = suma con signo de partes
                                       tipo suma | cruce (entre estados) | continuidad (entre columnas)
                                       activa = no: en el catalogo pero sin evaluar todavia (medir antes)
    catalogo/<entidad>/oficial/        lo extraido de la planilla oficial (extraer_oficial.py): codigos,
                                       signo esperado e identidades; las pruebas comparan contra esto

Formato de un termino: "ESTADO:Codigo"; codigos alternativos del mismo concepto con "|"
("EFE:AumentoNetoDeEfectivoYEfectivoEquivalente|EFE:AumentoDisminucionNetoDe..."). Las partes
llevan signo: "+ESF:TotalActivo;-ESF:TotalPasivo".

Origen (fondos mutuos): las identidades del 07 (planilla generadora oficial de la CMF, Circular 1997,
mas los cruces entre estados y la continuidad del proyecto) y la asignacion de estados de
comun/secciones.py. tests/test_catalogo.py verifica que el catalogo reproduce lo que hoy esta en el
codigo; mientras dure la migracion, las etapas leen de aqui con las funciones de compatibilidad.
"""
from functools import lru_cache
from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def conceptos(entidad: str = "fm") -> pd.DataFrame:
    return pd.read_csv(DIR / entidad / "conceptos.csv", dtype=str, keep_default_na=False)


@lru_cache(maxsize=None)
def reglas(entidad: str = "fm") -> pd.DataFrame:
    return pd.read_csv(DIR / entidad / "reglas.csv", dtype=str, keep_default_na=False)


def terminos(partes: str) -> list:
    """'+ESF:A;-ESF:B|ESF:C' -> [(1, 'ESF:A'), (-1, 'ESF:B|ESF:C')]"""
    return [(1 if p[0] == "+" else -1, p[1:]) for p in partes.split(";") if p]


def sin_estado(termino: str) -> str:
    """'EFE:A|EFE:B' -> 'A' (el codigo principal, sin estado)."""
    return termino.split("|")[0].split(":", 1)[1]


def regla(id_: str, entidad: str = "fm") -> dict:
    r = reglas(entidad)
    fila = r[r["id"] == id_]
    if fila.empty:
        raise KeyError(f"regla {id_!r} no esta en catalogo/{entidad}/reglas.csv")
    return fila.iloc[0].to_dict()


def codigo(clave: str, entidad: str = "fm") -> str:
    """Clave corta ('total_activo', 'saldo_final', 'ecp_cierre') -> codigo XML."""
    c = conceptos(entidad)
    fila = c[c["clave"] == clave]
    if fila.empty:
        raise KeyError(f"clave {clave!r} no esta en catalogo/{entidad}/conceptos.csv")
    return fila.iloc[0]["codigo"]


def estado(clave: str, entidad: str = "fm") -> str:
    c = conceptos(entidad)
    return c.loc[c["clave"] == clave, "estado"].iloc[0]


def estado_de_claves(entidad: str = "fm") -> dict:
    """{'total_activo': 'ESF', ...} para las claves cortas (reemplaza los ESTADO = {...} repetidos)."""
    c = conceptos(entidad)
    c = c[c["clave"] != ""]
    return dict(zip(c["clave"], c["estado"]))


# --- compatibilidad con las etapas actuales (se van cuando migran al motor) -----------------------

def identidades_07(entidad: str = "fm") -> dict:
    """Formato del 07: {nombre: (total, [(signo, 'ESTADO:Codigo'), ...])} (tipos suma y cruce)."""
    r = reglas(entidad)
    r = r[r["tipo"].isin(["suma", "cruce"]) & (r["activa"] == "si")]
    return {n: (t, terminos(p)) for n, t, p in zip(r["nombre"], r["total"], r["partes"])}


def entre_columnas_07(entidad: str = "fm") -> dict:
    """Formato del 07: {nombre: (apertura en PeriodoActual, cierre en PeriodoAnterior)}."""
    r = reglas(entidad)
    r = r[(r["tipo"] == "continuidad") & (r["activa"] == "si")]
    return {n: (t, terminos(p)[0][1]) for n, t, p in zip(r["nombre"], r["total"], r["partes"])}


def subtotal_03b(clave: str, entidad: str = "fm") -> dict:
    """Formato del 03b: codigo del subtotal y codigos de sus partes, para una regla de suma con
    clave_03b (operacion, financiamiento, total_activo, ...)."""
    r = reglas(entidad)
    fila = r[r["clave_03b"] == clave].iloc[0]
    return dict(estado=fila["total"].split(":")[0], codigo=sin_estado(fila["total"]),
                partes=[sin_estado(t) for _, t in terminos(fila["partes"])])


def glosa(clave: str, entidad: str = "fm") -> str:
    """Regex de la glosa del concepto en el PDF (se aplica sobre el texto sin espacios, en minuscula)."""
    c = conceptos(entidad)
    g = c.loc[c["clave"] == clave, "glosa"]
    if g.empty or not g.iloc[0]:
        raise KeyError(f"clave {clave!r} sin glosa en catalogo/{entidad}/conceptos.csv")
    return g.iloc[0]
