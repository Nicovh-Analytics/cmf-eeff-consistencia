"""
Cifras de un fondo-anio y estado, XML y PDF lado a lado (hechos), por columna, con el codigo que asigno el
emparejador al renglon del PDF. Para revisar a mano un cruce o una diferencia.

Uso:
    PYTHONPATH=. python herramientas/ver_cifras.py 10369 2023 ESF [Total ActivoNeto ...]
    (los textos opcionales filtran codigos que los contengan)
"""
import sys

import pandas as pd

from comun.emparejar import _catalogo
from motor import hechos


def main():
    rut, anio, est, *filtro = sys.argv[1:]
    anio = int(anio)
    _, canon = _catalogo()
    x = hechos.xml()
    x = x[(x["rut"] == rut) & (x["anio"] == anio) & (x["estado"] == est) & (x["serie"] == "")].copy()
    x["concepto"] = x["codigo"].map(lambda c: canon.get(c, c))
    p = hechos.pdf()
    p = p[(p["rut"] == rut) & (p["anio"] == anio) & (p["estado"] == est)].copy()
    p["concepto"] = p["codigo"].map(lambda c: canon.get(c, c) if isinstance(c, str) else "(sin codigo)")
    xv = x.pivot_table(index="concepto", columns="contexto", values="valor", aggfunc="first")
    pv = p[p["concepto"] != "(sin codigo)"].pivot_table(index="concepto", columns="contexto", values="valor",
                                                       aggfunc="first")
    t = xv.add_prefix("xml_").join(pv.add_prefix("pdf_"), how="outer")
    if filtro:
        t = t[t.index.to_series().str.contains("|".join(filtro), case=False)]
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda v: f"{v:,.0f}")
    print(f"{rut} {anio} {est}: XML y PDF por concepto")
    print(t.to_string())
    s = p[p["concepto"] == "(sin codigo)"]
    if len(s):
        print("\nrenglones del PDF con montos sin codigo:")
        print(s[["pagina", "contexto", "glosa", "valor"]].head(20).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
