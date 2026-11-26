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
from functools import lru_cache

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


@lru_cache(maxsize=None)
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


@lru_cache(maxsize=None)
def _regla(id_regla: str, entidad: str) -> dict:
    """La regla del catalogo como dict, una vez: evaluar se llama por cifra (decenas de miles de veces) y
    filtrar el DataFrame del catalogo en cada llamada costaba mas que la evaluacion."""
    return dict(catalogo.regla(id_regla, entidad))


def evaluar(id_regla: str, valores: dict, entidad: str = "fm") -> tuple:
    """Una regla sobre cifras sueltas (una columna de un documento), con el signo como se imprimio.

    valores: {'ESTADO:Codigo': cifra} con el codigo principal de cada termino. Las partes con signo
    oficial estricto se toman como signo * |cifra|; en un cruce (la misma cifra en dos estados) se
    comparan los montos sin signo. Devuelve
    (dif, laxa):
      dif   suma de partes - total (cruce: total - parte, la convencion de presentacion del 03c)
      laxa  la menor diferencia admitiendo UN signo de presentacion: el total invertido o una parte sin
            signo estricto invertida (perdida impresa sin parentesis, ingresos netos negativos). Decide
            si cuadra: un signo invertido no es un error de cifra.
    """
    r = _regla(id_regla, entidad)
    sig = signos_estrictos(entidad)

    def norm(termino, normalizar=True):
        cod = termino.split("|")[0]
        v = valores[cod]
        s = sig.get(cod) if normalizar else None
        return (s * abs(v), False) if s else (v, True)          # (cifra, se puede invertir)

    if r["tipo"] == "cruce":          # la misma cifra en dos estados: se compara el monto, sin signo
        t = abs(valores[r["total"].split("|")[0]])
        partes = [(sg, abs(valores[c.split("|")[0]]), False) for sg, c in catalogo.terminos(r["partes"])]
    else:
        t, _ = norm(r["total"], normalizar=False)
        partes = [(sg, *norm(c)) for sg, c in catalogo.terminos(r["partes"])]
    suma = sum(sg * v for sg, v, _ in partes)
    candidatos = [abs(suma - t), abs(suma + t)]
    candidatos += [abs(suma - 2 * sg * v - t) for sg, v, libre in partes if libre]
    dif = (t - suma) if r["tipo"] == "cruce" else (suma - t)
    return dif, min(candidatos)
