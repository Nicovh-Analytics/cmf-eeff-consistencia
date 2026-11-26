"""
E3: ¿cortar cada bloque tambien en los codigos de los OTROS subtotales posicionales del estado?

Hoy un bloque corta en el total de cada subtotal posicional y en los terminos de las identidades no
posicionales (comun/estructura.cortes). Si el corte falla (pagina sin el renglon "Total activos" leido,
p. ej.) el bloque del pasivo sube hasta los activos y los suma. Variante amplia: ademas corta en
cualquier codigo que sea parte de otro subtotal posicional del mismo estado (activos para el pasivo,
financiamiento para la operacion, gastos para los ingresos), salvo las partes propias.

Solo mide; no cambia el pipeline. Por subtotal-columna ubicado compara la suma por posicion actual y la
amplia contra el subtotal impreso:
    gana    no cuadraba y con el corte amplio cuadra
    pierde  cuadraba y deja de cuadrar
    cambia  cambia la suma y sigue sin cuadrar
y cruza las que cambian con la clase del 03b (estructura_efe_no_suma.csv).

Uso:
    PYTHONPATH=. python herramientas/medir_corte_amplio.py
"""
import sys

import pandas as pd

import catalogo
from comun import estructura
from config import CMF_HOME

P = CMF_HOME / "procesado"
TOL = 2


def codigos(termino):
    """'ESF:A|ESF:B' -> {'A', 'B'}"""
    return {a.split(":", 1)[1] for a in termino.split("|")}


def cortes_amplios(entidad="fm"):
    """{(estado, clave): codigos que cortan el bloque de esa clave con la variante amplia}."""
    base, subs = estructura.cortes(entidad), estructura.subtotales(entidad)
    r = catalogo.reglas(entidad)
    r = r[r["clave_03b"].isin(estructura.POSICIONALES) & (r["activa"] == "si")]
    partes = {c: set().union(*(codigos(t) for _, t in catalogo.terminos(p))) for c, p in zip(r["clave_03b"], r["partes"])}
    out = {}
    for clave, cfg in subs.items():
        est = cfg["estado"]
        otras = set().union(*(partes[k] for k, v in subs.items() if v["estado"] == est and k != clave), set())
        out[(est, clave)] = (base.get(est, set()) | otras) - partes[clave]
    return out


def main():
    subs, base, amp = estructura.subtotales(), estructura.cortes(), cortes_amplios()
    rg = pd.read_csv(P / "renglones_pdf.csv", dtype={"rut": str, "codigo": str}, low_memory=False)
    rg["glosa"] = rg["glosa"].fillna("")
    rg = rg.astype(object).where(rg.notna(), None)
    filas = []
    for (rut, anio, est), g in rg.groupby(["rut", "anio", "estado"], sort=False):
        L = estructura.lineas(g.to_dict("records"))
        fechas = {anio, anio - 1, anio + 1, 28, 29, 30, 31}
        for clave, cfg in subs.items():
            if cfg["estado"] != est:
                continue
            i = estructura.ubicar(L, cfg["codigo"])
            if i is None:
                continue
            a = estructura.miembros(L, i, base.get(est, set()) - {cfg["codigo"]}, fechas, set(cfg["partes"]))
            b = estructura.miembros(L, i, amp[(est, clave)] - {cfg["codigo"]}, fechas, set(cfg["partes"]))
            if a == b:
                continue
            for col, k in (("actual", 1), ("anterior", 2)):
                t = L[i][k]
                if t is None:
                    continue
                sa = sum(L[j][k] for j in a if L[j][k] is not None)
                sb = sum(L[j][k] for j in b if L[j][k] is not None)
                quitadas = [f"{L[j][0][:30]}={L[j][k]:,.0f}" for j in a if j not in b and L[j][k]]
                filas.append(dict(rut=rut, anio=anio, subtotal=clave, columna=col, total=t, suma_hoy=sa,
                                  suma_amplia=sb, n_hoy=len(a), n_amplia=len(b), quitadas="; ".join(quitadas)))
    m = pd.DataFrame(filas)
    print("cortes que agrega la variante amplia:")
    for (est, clave), c in amp.items():
        print(f"  {est} {clave:<15} +{len(c - base.get(est, set()))} codigos")
    if m.empty:
        print("\nninguna suma cambia con el corte amplio")
        return 0
    cuadra = lambda s: (m["total"].abs() - s.abs()).abs() <= TOL
    m["hoy"], m["amplia"] = cuadra(m["suma_hoy"]), cuadra(m["suma_amplia"])
    m = m[(m["suma_hoy"] - m["suma_amplia"]).abs() > 0.5]
    m["efecto"] = "cambia"
    m.loc[~m["hoy"] & m["amplia"], "efecto"] = "gana"
    m.loc[m["hoy"] & ~m["amplia"], "efecto"] = "pierde"
    ns = pd.read_csv(P / "estructura_efe_no_suma.csv", dtype={"rut": str}, usecols=["rut", "anio", "subtotal", "columna", "clase"])
    m = m.merge(ns, how="left").fillna({"clase": "(cuadra en el 03b)"})

    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 90)
    print(f"\nsubtotal-columna cuya suma cambia: {len(m)}")
    print(pd.crosstab(m["subtotal"], m["efecto"], margins=True).to_string(), "\n")
    print(pd.crosstab(m["clase"], m["efecto"], margins=True).to_string(), "\n")
    for ef in ("gana", "pierde", "cambia"):
        x = m[m["efecto"] == ef]
        if len(x):
            print(f"{ef} ({len(x)}):")
            print(x[["rut", "anio", "subtotal", "columna", "total", "suma_hoy", "suma_amplia", "clase", "quitadas"]]
                  .head(40).to_string(index=False), "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
