"""
Dos lecturas independientes de cada subtotal posicional del PDF (D-CU19):

    por posicion   las lineas del bloque (rol = linea en los hechos): lo que suma el 03b
    por codigo     las partes de la regla del catalogo, con los codigos que asigno el emparejador

Fallan por motivos distintos: la posicion cuando el corte del bloque se equivoca (un numero de nota, el
titulo, el bloque vecino); el codigo cuando el emparejador no asigno el codigo de una linea. Si la suma
por codigo cuadra con el mismo subtotal impreso, el no-suma por posicion es lectura nuestra.

Signo IMPRESO en las dos: con el signo oficial tambien "cuadraria" una cifra mal impresa con el signo
contrario (un saldo inicial negativo), que es un error y no presentacion.
"""
import pandas as pd

import catalogo
from comun import estructura
from motor import reglas

TOL = 2
COL = {"PeriodoActual": "actual", "PeriodoAnterior": "anterior"}


def dos_lecturas(h: pd.DataFrame, entidad: str = "fm") -> pd.DataFrame:
    """Por PDF, columna y subtotal posicional: total y suma por codigo, suma por posicion, y si cuadra cada una.
    h: hechos del PDF con estructura (motor/hechos.pdf)."""
    r = catalogo.reglas(entidad)
    r = r[r["clave_03b"].isin(estructura.POSICIONALES) & (r["activa"] == "si")]
    ident = {c: (t, catalogo.terminos(p)) for c, t, p in zip(r["clave_03b"], r["total"], r["partes"])}
    cod = reglas.por_columna(h, identidades=ident).reset_index().rename(
        columns={"identidad": "subtotal", "total": "total_cod", "suma_partes": "suma_cod"})
    li = h[h["rol"] == "linea"].assign(subtotal=lambda d: d["bloque"].str.split("|")).explode("subtotal")
    pos = li.groupby(["archivo", "contexto", "subtotal"], as_index=False)["valor"].sum().rename(columns={"valor": "suma_pos"})
    sub = (h[h["rol"] == "subtotal"].drop_duplicates(["archivo", "contexto", "bloque"])
           .rename(columns={"bloque": "subtotal", "valor": "total_pos"})[["archivo", "contexto", "subtotal", "total_pos"]])
    m = sub.merge(pos, how="left").merge(cod, how="outer")
    m["suma_pos"] = m["suma_pos"].fillna(0)
    m["cuadra_pos"] = m["total_pos"].notna() & ((m["total_pos"] - m["suma_pos"]).abs() <= TOL)
    m["cuadra_cod"] = m["total_cod"].notna() & ((m["total_cod"].abs() - m["suma_cod"].abs()).abs() <= TOL)
    m["rut"] = m["archivo"].str.split("_").str[0]
    m["anio"] = m["archivo"].str.split("_").str[1].astype(int)
    m["columna"] = m["contexto"].map(COL)
    return m[["rut", "anio", "columna", "subtotal", "total_pos", "suma_pos", "cuadra_pos", "total_cod", "suma_cod", "cuadra_cod"]]
