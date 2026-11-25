"""
Evaluacion de las reglas del catalogo sobre los hechos.

Una regla es total = suma con signo de partes, con codigos "ESTADO:Codigo" y alternativos "A|B"
(el primero que este informado). Se evalua sobre los totales del fondo (serie ''):

    por_columna(hechos)       suma y cruce, en cada archivo y contexto (actual y anterior por separado);
                              solo donde el total esta informado; una parte ausente cuenta 0
    entre_columnas(hechos)    continuidad: apertura del periodo actual = cierre del anterior, en el
                              mismo archivo; solo donde ambos estan informados

Devuelven: archivo, [contexto,] identidad (nombre de la regla), total, suma_partes.

signo_oficial (para el PDF): el PDF imprime signos de presentacion (gastos sin parentesis, rescates
positivos). Con signo_oficial=True cada PARTE cuyo signo en el modelo oficial es estricto ("+" o "-",
catalogo/fm/conceptos.csv) se toma como signo * |valor|. Los totales y las partes "+ o -" quedan como se
imprimieron: el modelo marca el flujo neto como "(+)" aunque pueda ser negativo.
"""
import pandas as pd

import catalogo


def _totales(hechos: pd.DataFrame) -> pd.DataFrame:
    tot = hechos[hechos["serie"] == ""]
    return tot.assign(col=tot["estado"] + ":" + tot["codigo"])


def _columna(w: pd.DataFrame, cod: str):
    """'A|B' -> valor de A; si falta, el de B (codigos alternativos por plantilla)."""
    alts = [a for a in cod.split("|") if a in w]
    if not alts:
        return None
    v = w[alts[0]]
    for a in alts[1:]:
        v = v.fillna(w[a])
    return v


def signos_estrictos(entidad: str = "fm") -> dict:
    """{'ERI:ComisionDeAdministracion': -1, 'EFE:VentaCobroDeActivosFinancieros': 1, ...}"""
    c = catalogo.conceptos(entidad)
    c = c[c["signo"].isin(["+", "-"])]
    return {f"{e}:{k}": (1 if s == "+" else -1) for e, k, s in zip(c["estado"], c["codigo"], c["signo"])}


def por_columna(hechos: pd.DataFrame, entidad: str = "fm", identidades: dict | None = None,
                signo_oficial: bool = False) -> pd.DataFrame:
    identidades = catalogo.identidades_07(entidad) if identidades is None else identidades
    w = _totales(hechos).pivot_table(index=["archivo", "contexto"], columns="col", values="valor", aggfunc="first")
    if signo_oficial:
        totales = {a for t, _ in identidades.values() for a in t.split("|")}
        for col, sg in signos_estrictos(entidad).items():
            if col in w and col not in totales:
                w[col] = sg * w[col].abs()
    filas = []
    for nombre, (total, partes) in identidades.items():
        t = _columna(w, total)
        if t is None:
            continue
        presentes = t.notna()                   # se evalua solo si el total esta informado
        rhs = 0
        for sg, c in partes:
            v = _columna(w, c)
            rhs = rhs + (sg * v.fillna(0) if v is not None else 0)
        filas.append(pd.DataFrame({"identidad": nombre, "total": t, "suma_partes": rhs})[presentes])
    return pd.concat(filas) if filas else pd.DataFrame(columns=["identidad", "total", "suma_partes"])


def entre_columnas(hechos: pd.DataFrame, entidad: str = "fm", pares: dict | None = None) -> pd.DataFrame:
    pares = catalogo.entre_columnas_07(entidad) if pares is None else pares
    w = _totales(hechos).pivot_table(index="archivo", columns=["contexto", "col"], values="valor", aggfunc="first")
    filas = []
    for nombre, (apertura, cierre) in pares.items():
        a, c = ("PeriodoActual", apertura), ("PeriodoAnterior", cierre)
        if a not in w or c not in w:
            continue
        ambos = w[a].notna() & w[c].notna()
        filas.append(pd.DataFrame({"identidad": nombre, "total": w.loc[ambos, a], "suma_partes": w.loc[ambos, c]}))
    return pd.concat(filas) if filas else pd.DataFrame(columns=["identidad", "total", "suma_partes"])
