"""
E1 (lector con estructura): ¿la estructura armada desde renglones_pdf.csv reproduce las sumas del 03b?

Reconstruye, sin volver a leer los PDF, los bloques por posicion (comun/estructura) de los 6 subtotales
del 03b y compara la suma de sus lineas con suma_lineas_pdf de estructura_efe.csv. Debe calzar en el
100%: si no, renglones_pdf.csv no guarda todo lo que el 03b usa y la estructura no puede reemplazarlo.

Variante: cortes tomados del catalogo (los totales de las reglas de suma del estado) en vez de la lista
del 03b. Informa en cuantos subtotales cambia la suma; si en ninguno, los cortes salen del catalogo.

E2: los hechos del PDF (motor/hechos.pdf) traen la estructura. Se verifica que (a) la suma por codigo
del motor da lo mismo que con los hechos anteriores (solo renglones con codigo) y (b) la suma por posicion
(rol = linea, por bloque) reproduce suma_lineas_pdf del 03b.

Uso:
    PYTHONPATH=. python herramientas/verificar_estructura.py
"""
import importlib
import sys

import pandas as pd

import catalogo
from comun import estructura
from config import CMF_HOME

P = CMF_HOME / "procesado"
TOL = 0.5


def cortes_catalogo():
    r = catalogo.reglas()
    r = r[(r["tipo"] == "suma") & (r["activa"] == "si")]
    out = {}
    for t in r["total"]:
        for alt in t.split("|"):
            e, c = alt.split(":", 1)
            out.setdefault(e, set()).add(c)
    return out


def main():
    m03b = importlib.import_module("validaciones.estructura.03b_estructura")
    sub, cortes_03b, cortes_cat = m03b.SUBTOTALES, m03b.CORTES, cortes_catalogo()
    rg = pd.read_csv(P / "renglones_pdf.csv", dtype={"rut": str, "codigo": str}, low_memory=False)
    rg["glosa"] = rg["glosa"].fillna("")          # el lector deja "" y el CSV lo vuelve vacio
    rg = rg.astype(object).where(rg.notna(), None)
    e = pd.read_csv(P / "estructura_efe.csv", dtype={"rut": str}, low_memory=False,
                    usecols=["rut", "anio", "subtotal", "columna", "ubicado", "subtotal_pdf", "suma_lineas_pdf"])
    e = e[(e["ubicado"] == True) & e["subtotal"].isin(sub)]
    ref = {(r, a, s, c): (t, v) for r, a, s, c, t, v in
           zip(e["rut"], e["anio"], e["subtotal"], e["columna"], e["subtotal_pdf"], e["suma_lineas_pdf"])}

    filas = []
    for (rut, anio, est), g in rg.groupby(["rut", "anio", "estado"], sort=False):
        subs = {k: v for k, v in sub.items() if v["estado"] == est}
        if not subs:
            continue
        L = estructura.lineas(g.to_dict("records"))
        fechas = {anio, anio - 1, anio + 1, 28, 29, 30, 31}
        for clave, cfg in subs.items():
            i = estructura.ubicar(L, cfg["codigo"])
            if i is None:
                continue
            for variante, cortes in (("03b", cortes_03b[est]), ("catalogo", cortes_cat.get(est, set()))):
                idx = estructura.miembros(L, i, cortes - {cfg["codigo"]}, fechas, set(cfg["partes"]))
                for col, k in (("actual", 1), ("anterior", 2)):
                    if L[i][k] is None:
                        continue
                    s = sum(L[j][k] for j in idx if L[j][k] is not None)
                    filas.append(dict(rut=rut, anio=anio, subtotal=clave, columna=col, variante=variante,
                                      total=L[i][k], suma=s, n=len(idx)))
    m = pd.DataFrame(filas)
    m["ref"] = [ref.get((r, a, s, c), (None, None)) for r, a, s, c in zip(m["rut"], m["anio"], m["subtotal"], m["columna"])]
    m["total_03b"], m["suma_03b"] = m["ref"].str[0], m["ref"].str[1]
    m = m[m["suma_03b"].notna()].drop(columns="ref")
    m["total_igual"] = (m["total"] - m["total_03b"]).abs() <= TOL
    m["suma_igual"] = (m["suma"] - m["suma_03b"]).abs() <= TOL

    pd.set_option("display.width", 200)
    a = m[m["variante"] == "03b"]
    print(f"subtotal-columna comparados: {len(a):,} (de {len(ref):,} ubicados por el 03b)")
    print(f"  mismo subtotal impreso: {a['total_igual'].mean():.4%}   misma suma de lineas: {a['suma_igual'].mean():.4%}")
    print(a.groupby("subtotal")[["total_igual", "suma_igual"]].mean().round(4).to_string(), "\n")
    if (~a["suma_igual"]).any():
        print("distintos (muestra):")
        print(a[~a["suma_igual"]].head(15).to_string(index=False), "\n")
    b = m[m["variante"] == "catalogo"].set_index(["rut", "anio", "subtotal", "columna"])
    c = a.set_index(["rut", "anio", "subtotal", "columna"])
    dif = (b["suma"] - c["suma"]).abs() > TOL
    print(f"cortes del catalogo en vez de los del 03b: cambia la suma en {int(dif.sum())} de {len(dif):,}")
    if dif.any():
        x = b.loc[dif, ["total", "suma", "n"]].join(c[["suma", "n"]], rsuffix="_cortes_03b").reset_index()
        print(x.groupby("subtotal").size().to_string())
        print(x.head(10).to_string(index=False))
    print("\ncortes 03b :", {k: sorted(v) for k, v in cortes_03b.items()})
    print("cortes cat.:", {k: sorted(v) for k, v in cortes_cat.items() if k in cortes_03b})
    e2(rg, ref)
    return 0


def e2(rg, ref):
    from motor import hechos, reglas
    h = hechos.pdf(reconstruir=True)
    print(f"\n== E2: hechos del PDF con estructura: {len(h):,} cifras; rol {h['rol'].value_counts().to_dict()}")

    # (a) suma por codigo: hechos anteriores (solo renglones con codigo, primer codigo por columna)
    v = rg[rg["codigo"].notna() & (rg["metodo"] != "encabezado")]
    v = v.melt(id_vars=["rut", "anio", "estado", "codigo"], value_vars=["actual", "anterior"], var_name="c", value_name="valor")
    v = v[v["valor"].notna()].assign(contexto=lambda d: d["c"].map({"actual": "PeriodoActual", "anterior": "PeriodoAnterior"}),
                                     archivo=lambda d: d["rut"] + "_" + d["anio"].astype(str), serie="")
    v["valor"] = v["valor"].astype(float)
    v = v.drop_duplicates(["archivo", "contexto", "estado", "codigo"])
    r = catalogo.reglas()
    r = r[r["activa"] == "si"]
    ident = {n: (t, catalogo.terminos(p)) for n, t, p in zip(r["nombre"], r["total"], r["partes"])}
    a = reglas.por_columna(v, identidades=ident).reset_index().sort_values(["archivo", "contexto", "identidad"])
    b = reglas.por_columna(h, identidades=ident).reset_index().sort_values(["archivo", "contexto", "identidad"])
    igual = (len(a) == len(b) and (a[["archivo", "contexto", "identidad"]].values == b[["archivo", "contexto", "identidad"]].values).all()
             and ((a["total"].values - b["total"].values) == 0).all()
             and ((a["suma_partes"].values - b["suma_partes"].values) == 0).all())
    print(f"(a) suma por codigo igual a la de los hechos anteriores: {igual} ({len(a):,} regla-columna)")

    # (b) suma por posicion desde los hechos
    li = h[h["rol"] == "linea"].assign(bloque=lambda d: d["bloque"].str.split("|")).explode("bloque")
    pos = li.groupby(["rut", "anio", "bloque", "contexto"])["valor"].sum()
    print(f"    lineas en dos bloques (el corte del 03b fallo): {int(h['bloque'].str.contains('|', regex=False).sum()):,}")
    col = {"PeriodoActual": "actual", "PeriodoAnterior": "anterior"}
    ok = n = 0
    for (rut, anio, sub, c), (_, suma) in ref.items():
        if suma is None or pd.isna(suma):
            continue
        ctx = "PeriodoActual" if c == "actual" else "PeriodoAnterior"
        n += 1
        ok += abs(pos.get((rut, anio, sub, ctx), 0.0) - suma) <= TOL
    print(f"(b) suma por posicion (hechos, rol linea) = suma del 03b: {ok:,} de {n:,} ({ok / max(n, 1):.4%})")


if __name__ == "__main__":
    sys.exit(main())
