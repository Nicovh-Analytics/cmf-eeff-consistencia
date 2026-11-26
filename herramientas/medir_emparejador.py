"""
E7: ¿el emparejador puede asignar codigos sin el XML como arbitro?

Hoy (A) los codigos candidatos de cada renglon son los del XML del fondo, el monto que calza con el XML
suma 0,1 al puntaje de la glosa, lo que queda sin glosa se asigna por valor y los montos corridos se
corrigen con el XML. Variante (B): candidatos = codigos del catalogo del estado, la glosa decide, cada concepto a un solo
renglon (los sinonimos de las plantillas cuentan como uno), el XML solo desempata glosas de igual puntaje
y no asigna por valor; si el monto de un renglon es el de otra cuenta del XML, se marca (monto_de).
La correccion de montos corridos (lectura) se mantiene.

Solo mide (relee los PDF, como el 03b). Por renglon con montos compara el codigo de A y de B:
    igual | solo_A (B lo deja sin codigo) | solo_B | distinto
y, por regla de suma posicional del catalogo (clave_03b), si la suma por codigo cuadra con el total
impreso con A y con B. Si B cuadra casi lo mismo que A, la glosa basta y el XML queda como testigo.

Los codigos se comparan por CONCEPTO: el catalogo trae las dos plantillas del EFE (metodo directo e
indirecto) con codigos sinonimos ("RescateDe..." / "RescatesDe...", "...Utilizado..." / "...Originado...");
alternativo_de (conceptos.csv) los lleva al mismo concepto. Elegir uno u otro no es un desacuerdo.

Uso:
    PYTHONPATH=. python herramientas/medir_emparejador.py [--muestra N]
"""
import argparse
import copy
import sys
from collections import Counter

import pandas as pd

import catalogo
from comun import estructura
from comun.emparejar import _orden, emparejar, xml_estado
from comun.lector import leer_estados, paginas_de
from comun.lector_espacial import cargar_coords
from comun.secciones import asignar_secciones
from config import CMF_HOME

P = CMF_HOME / "procesado"
TOL = 2


def vocabulario():
    c = catalogo.conceptos()
    c = c[c["por_serie"] != "si"]
    return {e: list(g["codigo"]) for e, g in c.groupby("estado")}


def canonico():
    """codigo -> concepto (alternativo_de del catalogo, o el mismo codigo)."""
    c = catalogo.conceptos()
    return {k: (a or k) for k, a in zip(c["codigo"], c["alternativo_de"].fillna(""))}


CANON = canonico()
can = lambda c: CANON.get(c, c) if c else c


def reglas_estado():
    r = catalogo.reglas()
    r = r[r["clave_03b"].isin(estructura.POSICIONALES) & (r["activa"] == "si")]
    out = {}
    for clave, total, partes in zip(r["clave_03b"], r["total"], r["partes"]):
        est = total.split(":")[0]
        tot = {can(a.split(":", 1)[1]) for a in total.split("|")}
        pts = [(sg, {can(a.split(":", 1)[1]) for a in t.split("|")}) for sg, t in catalogo.terminos(partes)]
        out.setdefault(est, []).append((clave, tot, pts))
    return out


def suma_codigo(rs, reglas):
    """[(clave, columna, cuadra)] de la suma por codigo (signo impreso) contra el total impreso."""
    out = []
    for clave, tot, pts in reglas:
        for k, col in ((0, "actual"), (1, "anterior")):
            val = {}
            for r in rs:
                c = can(r.get("codigo"))
                v = (r["actual"], r["anterior"])[k]
                if c and v is not None and c not in val:
                    val[c] = v
            t = next((val[c] for c in tot if c in val), None)
            if t is None:
                continue
            s = sum(sg * next((val[c] for c in alts if c in val), 0) for sg, alts in pts)
            out.append((clave, col, abs(abs(s) - abs(t)) <= TOL))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestra", type=int, default=0, help="fondo-anio al azar (0 = todos)")
    a = ap.parse_args()
    res = pd.read_csv(P / "cruce_resumen.csv", dtype={"rut": str})
    enc = pd.read_csv(P / "encabezados.csv", dtype={"rut": str})
    enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "archivo"]]
    ok = (res[res["estado"].isin(["ok", "sin_texto", "sin_paginas_de_estados"]) & res["pdf"].notna()]
          .merge(enc, on=["rut", "anio"]))
    if a.muestra:
        ok = ok.sample(a.muestra, random_state=1)
    cta = pd.read_csv(P / "cuentas.csv", usecols=["archivo", "contexto", "codigo", "serie", "valor"], dtype={"serie": str})
    cta = cta[cta["archivo"].isin(ok["archivo"]) & cta["codigo"].notna() & cta["valor"].notna()]
    cta_de = dict(tuple(cta.groupby("archivo", sort=False)))
    voc, reg = vocabulario(), reglas_estado()

    cmp, pares, chk, n = Counter(), Counter(), [], 0
    ejemplos, testigo, ej_testigo = [], Counter(), []
    for r in ok.itertuples(index=False):
        coords, c = cargar_coords(r.rut, r.anio, r.pdf), cta_de.get(r.archivo)
        if coords is None or c is None:
            continue
        paginas, base = paginas_de(r.paginas_estados, coords)
        if not paginas:
            continue
        c = c.copy()
        c["estado_fin"] = asignar_secciones(c["codigo"].tolist())
        rs, _ = leer_estados(coords, paginas, base=base)
        n += 1
        for est in ("ESF", "ERI", "EFE"):
            sub = [x for x in rs if x["estado"] == est]
            xml = xml_estado(c[(c["estado_fin"] == est) & c["serie"].isna()])
            A = emparejar(copy.deepcopy(sub), xml, est)
            B = emparejar(copy.deepcopy(sub), xml, est, vocabulario=voc.get(est, []), canon=CANON,
                          orden=_orden().get(est, {}))
            for ra, rb in zip(A, B):
                if rb["metodo"] == "encabezado" or (rb["actual"] is None and rb["anterior"] is None):
                    continue
                ca, cb = ra.get("codigo"), rb.get("codigo")
                k = ("igual" if ca == cb else "solo_A" if cb is None else "solo_B" if ca is None else
                     "sinonimo" if can(ca) == can(cb) else "distinto")
                cmp[(est, k, ra.get("coincide") if ca else "-")] += 1
                if rb.get("monto_de"):
                    testigo[(est, can(rb["codigo"]), can(rb["monto_de"]))] += 1
                    if len(ej_testigo) < 30:
                        ej_testigo.append((r.rut, r.anio, est, rb["glosa"][:40], rb["codigo"], "<- monto de", rb["monto_de"]))
                if k not in ("igual", "sinonimo"):
                    pares[(est, k, ca, cb)] += 1
                    if k == "distinto" and len(ejemplos) < 30:
                        ejemplos.append((r.rut, r.anio, est, rb["glosa"][:45], ca, cb))
            for (clave, col, ok_a), (_, _, ok_b) in zip(suma_codigo(A, reg.get(est, [])), suma_codigo(B, reg.get(est, []))):
                chk.append((clave, col, ok_a, ok_b))

    pd.set_option("display.width", 220)
    print(f"fondo-anio leidos: {n}")
    t = pd.DataFrame([(e, k, co, v) for (e, k, co), v in cmp.items()], columns=["estado", "efecto", "coincide_A", "n"])
    print("\nrenglones con montos, codigo A (hoy) vs B (catalogo, XML solo desempata):")
    print(t.pivot_table(index="estado", columns="efecto", values="n", aggfunc="sum", fill_value=0, margins=True).to_string())
    print("\nsolo_A por como coincidia en A (valor = asignado solo por el monto del XML):")
    print(t[t["efecto"] == "solo_A"].pivot_table(index="estado", columns="coincide_A", values="n", aggfunc="sum",
                                                 fill_value=0, margins=True).to_string())
    k = pd.DataFrame(chk, columns=["subtotal", "columna", "cuadra_A", "cuadra_B"])
    print("\nsuma por codigo = total impreso (% de subtotal-columna con total):")
    print(k.groupby("subtotal")[["cuadra_A", "cuadra_B"]].mean().mul(100).round(2).to_string())
    print(f"  A cuadra y B no: {int((k.cuadra_A & ~k.cuadra_B).sum())}   B cuadra y A no: {int((~k.cuadra_A & k.cuadra_B).sum())}")
    print("\npares mas frecuentes (estado, efecto, codigo A -> codigo B):")
    for (e, ef, ca, cb), v in pares.most_common(25):
        print(f"  {v:>5}  {e} {ef:<8} {ca or '-'} -> {cb or '-'}")
    print(f"\nXML testigo: renglones cuyos montos son los de OTRA cuenta del XML (glosa_vs_monto): {sum(testigo.values())}")
    for (e, c, m), v in testigo.most_common(15):
        print(f"  {v:>4}  {e} glosa {c} <- monto de {m}")
    for x in ej_testigo:
        print("  ", *x)
    print("\nejemplos de codigo distinto:")
    for x in ejemplos:
        print("  ", *x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
