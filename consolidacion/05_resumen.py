"""
05 - Cifras de portada de la v1 (fondos mutuos): universo, cobertura, errores, precision y AGF.

No identifica fondos ni AGF: las AGF se agrupan por su tasa de error contra la tasa global
(intervalo de Wilson): bajo / indistinguible / alto, y aparte las que tienen pocas celdas evaluables.

Lee:      encabezados.csv, cruce_resumen.csv, pdf_sin_estados.csv (03f), casos_unicos.csv (04c),
          perfil_estado.csv y perfil_agf.csv (04d); precision.csv si existe (muestras de precision)
Escribe:  data/procesado/resumen_v1.csv (indicador, valor, detalle)
"""
import math
import sys

import pandas as pd

from config import CMF_HOME

P = CMF_HOME / "procesado"
MIN_EVALUABLES_AGF = 200        # bajo esto la tasa de una AGF no se distingue de la global


def wilson(k, n, z=1.96):
    if not n:
        return float("nan"), float("nan")
    p, d = k / n, 1 + z * z / n
    c, r = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - r), min(1.0, c + r)


def verdad(s):
    return s.astype(str).str.strip().str.lower().isin(["true", "si", "1", "1.0"])


def main():
    filas = []
    out = lambda ind, val, det="": filas.append(dict(indicador=ind, valor=val, detalle=det))

    # universo
    enc = pd.read_csv(P / "encabezados.csv", dtype={"rut": str, "rut_agf": str})
    enc = enc[enc["es_ultimo_envio"]]
    fa = enc[["rut", "anio"]].drop_duplicates()
    out("fondo-anio con XML", len(fa), f"{enc['rut'].nunique()} fondos, {enc['rut_agf'].nunique()} AGF, "
                                       f"{int(enc['anio'].min())}-{int(enc['anio'].max())}")
    res = pd.read_csv(P / "cruce_resumen.csv", dtype={"rut": str}, usecols=["rut", "anio", "pdf"])
    con_pdf = res[res["pdf"].notna()][["rut", "anio"]].drop_duplicates()
    out("fondo-anio con XML y PDF", len(con_pdf), f"{len(con_pdf) / len(fa):.1%} del universo")
    sp = P / "pdf_sin_estados.csv"
    if sp.exists():
        out("PDF sin estados legibles", len(pd.read_csv(sp)), "0 paginas, solo opinion del auditor o escaneado sin OCR")

    # cobertura (escalera del 04d)
    pe = pd.read_csv(P / "perfil_estado.csv", dtype={"rut": str})
    ev = verdad(pe["evaluable"]) if "evaluable" in pe else pd.Series(True, index=pe.index)
    out("celdas fondo-anio x estado", len(pe), f"evaluables {ev.mean():.1%}; cobertura media {pe['cobertura'].mean():.1%}")
    if "limpia" in pe:
        out("celdas evaluables limpias", f"{verdad(pe.loc[ev, 'limpia']).mean():.1%}", "sin error en ningun peldano")

    # errores
    cu = pd.read_csv(P / "casos_unicos.csv", dtype={"rut": str})
    err = cu[cu["tipo"].astype(str).str.startswith("error")]
    fa_err = err[["rut", "anio_doc"]].drop_duplicates()
    out("errores (casos unicos)", len(err), " | ".join(f"{t} {n}" for t, n in err["tipo"].value_counts().items()))
    out("fondo-anio con al menos un error", len(fa_err), f"{len(fa_err) / len(con_pdf):.1%} de los que tienen XML y PDF")
    out("errores por estado", "", " | ".join(f"{e} {n}" for e, n in err["estado_raiz"].value_counts().items()))
    out("otros hallazgos (no error)", len(cu) - len(err),
        " | ".join(f"{t} {n}" for t, n in cu.loc[~cu.index.isin(err.index), "tipo"].value_counts().head(6).items()))
    if "localizacion" in err:
        out("errores con la cifra localizada (03g)", int(err["localizacion"].notna().sum()),
            f"misma cifra en t y t+1: {int(verdad(err['repite_t1'].fillna(False)).sum())}")

    # precision (de las muestras revisadas a mano; el detalle de los veredictos es privado)
    pr = P / "precision.csv"
    if pr.exists():
        for r in pd.read_csv(pr).itertuples():
            out(f"precision {r.tipo}", r.precision, f"IC 95% {r.ic95}; {r.revisados} revisados")
    else:
        out("precision", "-", "sin precision.csv (verificacion/precision_combinada.py)")

    # AGF por grupos (sin nombres)
    pa = pd.read_csv(P / "perfil_agf.csv", dtype={"rut_agf": str})
    k_tot, n_tot = pa["con_error"].sum(), pa["evaluables"].sum()
    g = k_tot / n_tot
    def grupo(k, n):
        if n < MIN_EVALUABLES_AGF:
            return "pocas celdas"
        lo, hi = wilson(k, n)
        return "bajo" if hi < g else "alto" if lo > g else "indistinguible"
    pa["grupo"] = [grupo(k, n) for k, n in zip(pa["con_error"], pa["evaluables"])]
    out("tasa global de celdas con error", f"{g:.2%}", f"{int(k_tot)} de {int(n_tot)} celdas evaluables")
    for gr, h in pa.groupby("grupo"):
        tasas = h["con_error"] / h["evaluables"].where(h["evaluables"] > 0)
        out(f"AGF grupo {gr}", len(h), f"tasa {tasas.min():.2%}-{tasas.max():.2%}; celdas {int(h['evaluables'].sum())}")

    r = pd.DataFrame(filas)
    r.to_csv(P / "resumen_v1.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 120)
    print(r.to_string(index=False))
    print(f"\n-> {P / 'resumen_v1.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
