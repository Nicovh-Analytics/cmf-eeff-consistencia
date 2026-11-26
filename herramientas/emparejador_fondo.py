"""
E7: renglones de un fondo-anio con el codigo del emparejador v1 (A: el XML arbitra) y v2 (B: catalogo,
XML testigo), para revisar los casos que cambian en el diff.

Imprime, por estado, los renglones con montos cuyo codigo cambia (por concepto) o que B marca con
monto_de / glosa_de. Con --todo, todos los renglones del estado.

Uso:
    PYTHONPATH=. python herramientas/emparejador_fondo.py 8106 2021 [8872 2011 ...] [--estado EFE] [--todo]
"""
import argparse
import copy
import sys

import pandas as pd

from comun.emparejar import MIN_GLOSA, _catalogo, _orden, emparejar, puntaje_glosa, xml_estado
from comun.lector import leer_estados, paginas_de
from comun.lector_espacial import cargar_coords
from comun.secciones import asignar_secciones
from config import CMF_HOME

P = CMF_HOME / "procesado"


def fmt(v):
    return "" if v is None else f"{v:,.0f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pares", nargs="+", help="rut anio [rut anio ...]")
    ap.add_argument("--estado", default="", help="ESF | ERI | EFE (por defecto los tres)")
    ap.add_argument("--todo", action="store_true", help="todos los renglones, no solo los que cambian")
    a = ap.parse_args()
    pares = [(a.pares[i], int(a.pares[i + 1])) for i in range(0, len(a.pares) - 1, 2)]
    res = pd.read_csv(P / "cruce_resumen.csv", dtype={"rut": str})
    enc = pd.read_csv(P / "encabezados.csv", dtype={"rut": str})
    enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "archivo"]]
    ok = res[res["pdf"].notna()].merge(enc, on=["rut", "anio"])
    ok = ok[[(r, n) in pares for r, n in zip(ok["rut"], ok["anio"])]]
    cta = pd.read_csv(P / "cuentas.csv", usecols=["archivo", "contexto", "codigo", "serie", "valor"], dtype={"serie": str})
    cta = cta[cta["archivo"].isin(ok["archivo"]) & cta["codigo"].notna() & cta["valor"].notna()]
    voc, canon = _catalogo()
    can = lambda c: canon.get(c, c) if c else c
    for r in ok.itertuples(index=False):
        coords = cargar_coords(r.rut, r.anio, r.pdf)
        paginas, base = paginas_de(r.paginas_estados, coords) if coords else ([], None)
        if not paginas:
            print(f"\n{r.rut} {r.anio}: sin paginas leibles")
            continue
        c = cta[cta["archivo"] == r.archivo].copy()
        c["estado_fin"] = asignar_secciones(c["codigo"].tolist())
        rs, _ = leer_estados(coords, paginas, base=base)
        for est in ("ESF", "ERI", "EFE"):
            if a.estado and est != a.estado:
                continue
            sub = [x for x in rs if x["estado"] == est]
            xml = xml_estado(c[(c["estado_fin"] == est) & c["serie"].isna()])
            A = emparejar(copy.deepcopy(sub), xml, est)
            B = emparejar(copy.deepcopy(sub), xml, est, vocabulario=voc.get(est, ()), canon=canon,
                          orden=_orden().get(est, {}))
            filas, diag = [], []
            usado = {can(x.get("codigo")): x["glosa"][:30] for x in B if x.get("codigo")}
            for ra, rb in zip(A, B):
                if rb["metodo"] == "encabezado" or (rb["actual"] is None and rb["anterior"] is None):
                    continue
                cambia = can(ra.get("codigo")) != can(rb.get("codigo")) or rb.get("monto_de") or rb.get("glosa_de")
                if cambia and not rb.get("codigo"):
                    # por que B no le dio codigo: sus 3 mejores candidatos y si otro renglon ya tenia el concepto
                    pt = sorted(((puntaje_glosa(rb, k, est), k) for k in voc.get(est, ())), reverse=True)[:3]
                    diag.append(f"  [{rb['glosa']}]  previa=[{rb.get('previa', '')}]")
                    for sc, k in pt:
                        u = usado.get(can(k))
                        diag.append(f"      {sc:.2f} {'OK ' if sc >= MIN_GLOSA else 'bajo'} {k}"
                                    + (f"  (ya asignado a: {u})" if u else ""))
                if a.todo or cambia:
                    filas.append(("*" if cambia else " ", rb["pagina"], rb["glosa"][:42], fmt(rb["actual"]), fmt(rb["anterior"]),
                                  f"{can(ra.get('codigo')) or '-'} ({ra.get('coincide') or '-'})",
                                  f"{can(rb.get('codigo')) or '-'} ({rb.get('coincide') or '-'})",
                                  can(rb.get("monto_de")) or "", can(rb.get("glosa_de")) or ""))
            if filas:
                print(f"\n{r.rut} {r.anio} {est}")
                print(pd.DataFrame(filas, columns=["", "pag", "glosa", "actual", "anterior", "A (v1)", "B (v2)",
                                                   "monto_de", "glosa_de"]).to_string(index=False))
                if diag:
                    print("  sin codigo en B, candidatos por glosa:")
                    print("\n".join(diag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
