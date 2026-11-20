"""
04d: escalera de verificacion por fondo-anio y estado (cobertura de lo que se pudo verificar)
============================================================================================

El conteo de errores dice cuanto fallo, no cuanto se pudo revisar: una AGF con PDF escaneados o
plantillas dificiles parece mas limpia porque se lee menos. Aqui cada fondo-anio x estado (columna
actual del PDF de ese anio) tiene un estado por peldano: si / no / no_evaluable.

  documento      el PDF es del fondo y periodo, y trae estados (03f)
  entidades      se ubicaron los subtotales y lineas clave del estado (03b, 03c; ECP: bloque del 03d)
  suma           cada subtotal suma sus lineas en el PDF (03b; ECP: identidades del 03d)
  entre_estados  identidades con otros estados del mismo PDF (03c)
  file           el PDF dice lo mismo que el XML (03b; ECP: coincidencia del bloque con el XML)
  comparativo    la columna anterior del PDF t+1 repite lo del PDF t (03e; el ECP no esta en el 03e)
  continuidad    el comparativo del XML t+1 repite el XML t (07)
Un peldano no se corta por el anterior (un "no" en suma con "si" en file y comparativo apunta a
lectura), salvo que sin entidades o sin documento no hay nada que evaluar.

Lee:      estructura_efe.csv, lineas_03c.csv, ecp_bloques.csv, ecp_no_cuadra.csv, comparativos_pdf.csv,
          continuidad_resumen.csv, documento_periodo.csv, pdf_sin_estados.csv, casos_unicos.csv,
          casos_unicos_senales.csv, cruce_resumen.csv, encabezados.csv
Escribe:  data/procesado/perfil_estado.csv        1 fila por fondo-anio x estado
          data/procesado/perfil_agf.csv           cobertura y errores por AGF
"""
import math
import sys

import pandas as pd

from config import CMF_HOME, nombres_agf

P = CMF_HOME / "procesado"
ESTADOS = ["ESF", "ERI", "EFE", "ECP"]
LINEA_ESTADO = {
    "total_activo": "ESF", "total_pasivo": "ESF", "activo_neto": "ESF", "efectivo": "ESF",
    "total_ingresos": "ERI", "total_gastos": "ERI", "utilidad_operacion": "ERI", "resultado_eri": "ERI",
    "resultado_eri_despues": "ERI",
    "operacion": "EFE", "financiamiento": "EFE", "aumento_neto": "EFE", "evolucion_efectivo": "EFE",
    "saldo_final": "EFE",
}
DOC_MAL = {"xml_periodo_desfasado", "xml_no_corresponde", "pdf_no_corresponde"}
PELDANOS = ["documento", "entidades", "suma", "entre_estados", "file", "comparativo", "continuidad"]


def leer(f, **kw):
    kw["dtype"] = {"rut": str, **kw.get("dtype", {})}
    return pd.read_csv(P / f, **kw)


def si_no(serie_bool):
    """Todas verdaderas -> si; alguna falsa -> no; vacia -> no_evaluable."""
    s = serie_bool.dropna()
    return "no_evaluable" if s.empty else ("si" if s.all() else "no")


def wilson(k, n, z=1.96):
    if not n:
        return float("nan"), float("nan")
    p, d = k / n, 1 + z * z / n
    c, r = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - r), min(1.0, c + r)


def main():
    base = leer("cruce_resumen.csv", usecols=["rut", "anio", "pdf"])
    base = base[base["pdf"].notna()][["rut", "anio"]]
    filas = base.merge(pd.DataFrame({"estado": ESTADOS}), how="cross")
    K = ["rut", "anio", "estado"]

    # documento
    dp = leer("documento_periodo.csv")
    mal = set(map(tuple, dp[dp["tipo"].isin(DOC_MAL)][["rut", "anio"]].values))
    sin = set(map(tuple, leer("pdf_sin_estados.csv")[["rut", "anio"]].values))
    filas["documento"] = ["no" if (r, a) in mal or (r, a) in sin else "si"
                          for r, a in zip(filas["rut"], filas["anio"])]

    # 03b (subtotales) y 03c (lineas), columna actual
    e = leer("estructura_efe.csv", usecols=["rut", "anio", "subtotal", "columna", "ubicado", "pdf_suma", "igual_xml"])
    e = e[e["columna"] == "actual"].assign(estado=lambda d: d["subtotal"].map(LINEA_ESTADO))
    l3 = leer("lineas_03c.csv", usecols=["rut", "anio", "linea", "columna", "pdf", "xml"])
    l3 = l3[l3["columna"] == "actual"].assign(estado=lambda d: d["linea"].map(LINEA_ESTADO))
    ent = pd.concat([e[K + ["ubicado"]], l3.assign(ubicado=l3["pdf"].notna())[K + ["ubicado"]]])
    ent = ent.groupby(K)["ubicado"].apply(si_no).rename("entidades")
    suma = e.groupby(K)["pdf_suma"].apply(si_no).rename("suma")
    f3 = pd.concat([e[K].assign(ok=e["igual_xml"]),
                    l3[l3["pdf"].notna() & l3["xml"].notna()][K].assign(
                        ok=(l3["pdf"].abs() - l3["xml"].abs()).abs() <= 1)])
    fil = f3.groupby(K)["ok"].apply(si_no).rename("file")

    # ECP (03d): bloque de la columna actual
    b = leer("ecp_bloques.csv", usecols=["rut", "anio", "columna", "confiable", "coincide_xml"])
    b = b[b["columna"] == "actual"].groupby(["rut", "anio"]).agg(
        confiable=("confiable", "any"), coincide=("coincide_xml", "min")).reset_index().assign(estado="ECP")
    nc = leer("ecp_no_cuadra.csv", usecols=["rut", "anio", "columna", "clase"])
    err_ecp = set(map(tuple, nc[(nc["columna"] == "actual") & nc["clase"].str.startswith("probable_error")
                               & (nc["clase"] != "probable_error_xml")][["rut", "anio"]].values))
    b["entidades"] = b["confiable"].map({True: "si", False: "no"})
    b["suma"] = ["no_evaluable" if not c else ("no" if (r, a) in err_ecp else "si")
                 for r, a, c in zip(b["rut"], b["anio"], b["confiable"])]
    b["file"] = b["coincide"].map(lambda x: "no_evaluable" if pd.isna(x) else ("si" if x >= 1 else "no"))
    ecp = b.set_index(K)[["entidades", "suma", "file"]]

    t = filas.set_index(K)
    t = t.join(pd.concat([ent, suma, fil], axis=1))
    t.update(ecp)

    # entre_estados (03c): senales del 03c en la columna actual del documento de ese anio
    s = leer("casos_unicos_senales.csv", usecols=["fuente", "rut", "anio_doc", "columna", "estado", "clase"])
    s = s[(s["fuente"] == "03c") & (s["columna"] == "actual")].rename(columns={"anio_doc": "anio"})
    s3 = s.groupby(K)["clase"].apply(lambda c: "no" if (c == "error").any() else "no_evaluable")
    t["entre_estados"] = s3.reindex(t.index)
    t.loc[t["entre_estados"].isna() & (t["entidades"] == "si")
          & (t.index.get_level_values("estado") != "ECP"), "entre_estados"] = "si"

    # comparativo (03e): la cifra del PDF t contra la columna anterior del PDF t+1
    c = leer("comparativos_pdf.csv", usecols=["rut", "anio_t", "linea", "clase"]).rename(columns={"anio_t": "anio"})
    c["estado"] = c["linea"].map(LINEA_ESTADO)
    def comp(cl):
        cl = set(cl)
        if cl <= {"cuadra", "observacion_inmaterial"}:
            return "si"
        if cl - {"cuadra", "observacion_inmaterial", "lectura", "sin_xml"}:
            return "no"
        return "no_evaluable"
    t["comparativo"] = c.groupby(K)["clase"].apply(comp).reindex(t.index)

    # continuidad (07): el XML t contra el comparativo del XML t+1 (fila del anio t+1 en el 07)
    cr = leer("continuidad_resumen.csv", usecols=["rut", "anio", "clase", "estados_dif"])
    cr = cr.assign(anio=cr["anio"] - 1, estados_dif=cr["estados_dif"].fillna(""))
    idx = cr.set_index(["rut", "anio"])
    def cont(r, a, est):
        if (r, a) not in idx.index:
            return "no_evaluable"
        f = idx.loc[(r, a)]
        if f["clase"] in ("identico", "dif_menor"):
            return "si"
        return "no" if est in str(f["estados_dif"]).split(",") else "si"
    t["continuidad"] = [cont(r, a, est) for r, a, est in t.index]

    # sin documento o sin entidades: nada que evaluar en los peldanos del PDF
    t = t.fillna({p: "no_evaluable" for p in PELDANOS})
    sin_doc = t["documento"] == "no"
    t.loc[sin_doc, ["entidades", "suma", "entre_estados", "file", "comparativo"]] = "no_evaluable"
    t.loc[t["entidades"] == "no_evaluable", ["suma", "entre_estados"]] = "no_evaluable"

    # errores del 04c por documento-anio y estado raiz (cualquier columna)
    cu = leer("casos_unicos.csv", usecols=["rut", "anio_doc", "estado_raiz", "tipo"])
    cu = cu[cu["tipo"].astype(str).str.startswith("error")]
    n_err = cu.groupby(["rut", "anio_doc", "estado_raiz"]).size()
    n_err.index.names = K
    t["errores"] = n_err.reindex(t.index).fillna(0).astype(int)
    t["evaluable"] = (t[["suma", "file", "comparativo"]] != "no_evaluable").any(axis=1)
    # cobertura fina: fraccion de peldanos evaluados (sin documento; el ECP no tiene entre_estados ni
    # comparativo: se cuenta sobre los 4 que tiene)
    pel = [p for p in PELDANOS if p != "documento"]
    evalua = (t[pel] != "no_evaluable")
    posibles = pd.Series(len(pel), index=t.index).where(t.index.get_level_values("estado") != "ECP", len(pel) - 2)
    t["cobertura"] = (evalua.sum(axis=1) / posibles).clip(upper=1).round(3)
    # senales de lectura en la celda (cualquier etapa, columna actual del documento de ese anio)
    sa = leer("casos_unicos_senales.csv", usecols=["rut", "anio_doc", "columna", "estado", "clase"])
    sa = sa[(sa["clase"] == "lectura") & (sa["columna"] == "actual")].rename(columns={"anio_doc": "anio"})
    t["lectura"] = sa.groupby(K).size().reindex(t.index).fillna(0).astype(int)
    t["limpia"] = t["evaluable"] & (t["lectura"] == 0)
    t = t.reset_index()
    enc = leer("encabezados.csv", dtype={"rut": str, "rut_agf": str})
    enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "rut_agf"]]
    t = t.merge(enc, on=["rut", "anio"], how="left")
    t.to_csv(P / "perfil_estado.csv", index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 220)
    print(f"fondo-anio x estado: {len(t)}  ({len(base)} fondo-anio con PDF)\n")
    for est in ESTADOS:
        x = t[t["estado"] == est]
        tab = pd.DataFrame({p: x[p].value_counts(normalize=True).mul(100).round(1) for p in PELDANOS}).fillna(0)
        print(f"{est} (% de fondo-anio):\n{tab.reindex(['si', 'no', 'no_evaluable']).to_string()}\n")

    # por AGF: cobertura (evaluable) y errores por fondo-anio-estado evaluable
    g = t.groupby("rut_agf").agg(celdas=("estado", "size"), evaluables=("evaluable", "sum"),
                                 limpias=("limpia", "sum"), cobertura=("cobertura", "mean"),
                                 con_error=("errores", lambda s: int((s > 0).sum())))
    g["cobertura_pct"] = (100 * g["cobertura"]).round(1)
    g["limpia_pct"] = (100 * g["limpias"] / g["celdas"]).round(1)
    g["error_pct_evaluable"] = (100 * g["con_error"] / g["evaluables"].where(g["evaluables"] > 0)).round(1)
    ic = [wilson(k, n) for k, n in zip(g["con_error"], g["evaluables"])]
    g["ic95"] = [f"{100 * lo:.1f}-{100 * hi:.1f}" if n else "" for (lo, hi), n in zip(ic, g["evaluables"])]
    g = g.drop(columns="cobertura")
    g.insert(0, "agf", pd.Series(nombres_agf()).reindex(g.index).values)
    g = g.sort_values("celdas", ascending=False)
    g.to_csv(P / "perfil_agf.csv", encoding="utf-8-sig")
    print("por AGF (celdas = fondo-anio x estado; error sobre lo evaluable):")
    v = g[g["celdas"] >= 40]
    print(v.assign(agf=v["agf"].astype(str).str[:40]).to_string() if len(v) else "  (ninguna con 40+ celdas)")
    print(f"\nsalidas: {P / 'perfil_estado.csv'}, {P / 'perfil_agf.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
