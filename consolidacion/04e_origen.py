"""
04e - Error de origen: que casos de error son el mismo error propagado, y cual es su origen
==========================================================================================

Un error impreso una vez reaparece en otras celdas con la misma diferencia: el subtotal que lo arrastra,
el estado que toma esa cifra, el XML que la copio del PDF, el comparativo del anio siguiente y la
continuidad. El 04c ya junta lo que cae en la misma celda (fondo, anio, documento, columna); aqui se
unen los casos de celdas DISTINTAS con la misma |dif| (+-2):

  PDF -> XML     mismo anio y columna, un caso del PDF y otro del XML (el XML copio la cifra)
  t -> t+1       caso de t (columna actual) y caso de t+1 en la columna anterior (el comparativo) o de
                 continuidad (apertura de t+1 contra cierre de t)
  dentro del documento   mismo anio, columna y documento, otro estado o linea que el 04c dejo aparte: la
                 cadena de subtotales arrastra el error y a veces suma un redondeo o una diferencia de
                 cambio; aqui la |dif| puede diferir hasta el 0,5%
  entre documentos       mismo anio y columna, documentos distintos (PDF y PDF+XML, por ejemplo)

Cada grupo conexo es UN error de origen. El origen es el caso mas temprano (anio, columna anterior
antes que actual en el mismo anio, PDF antes que XML, la linea antes que el subtotal y el total); los
demas son sus efectos, en ese orden: "fue en la celda X -> afecta a Y -> afecta tambien a Z".

Solo se unen diferencias de mas de MIN_DIF: con montos chicos coincidir en +-2 puede ser casualidad.

Uso:
    python consolidacion/04e_origen.py                  todo
    python consolidacion/04e_origen.py 8723 2021 ...    ademas, las cadenas de esos fondo-anio

Lee:      casos_unicos.csv (04c)
Escribe:  origen.csv (un error de origen por fila, con su cadena) y casos_origen.csv (caso -> origen)
"""
import sys

import pandas as pd

from config import CMF_HOME, casos_conocidos

P = CMF_HOME / "procesado"
TOL = 2
MIN_DIF = 10
REL = 0.005           # misma columna y documento: |dif| iguales al 0,5% (9625 2021: aumento neto 2.914, saldo final 2.923)
NIVEL = {"documento": -1, "linea": 0, "subtotal": 1, "total": 2, "identidad": 3}
# dentro de un estado, el componente antes que el agregado que lo arrastra (financiamiento -> aumento neto)
JERARQUIA = {"operacion": 0, "financiamiento": 0, "total_ingresos": 0, "total_gastos": 0, "total_activo": 0,
             "total_pasivo": 0, "efectivo": 0, "aumento_neto": 1, "utilidad_operacion": 1, "activo_neto": 1,
             "evolucion_efectivo": 2, "saldo_final": 2, "resultado_eri": 2, "resultado_eri_despues": 3}
DOC = {"error_PDF": 0, "error_PDF+XML": 1, "error_XML": 2, "error_continuidad": 3}


def orden(c):
    """Dentro del anio: comparativo (anterior) antes que actual, PDF antes que XML, linea antes que total y,
    entre subtotales, el componente antes que el agregado."""
    return list(zip((c["columna"] == "actual").astype(int), c["tipo"].map(DOC).fillna(9),
                    c["nivel"].map(NIVEL).fillna(9), c["linea_raiz"].map(JERARQUIA).fillna(1)))


def doc(tipo):
    t = str(tipo)
    return ("continuidad" if t == "error_continuidad" else "PDF+XML" if "PDF" in t and "XML" in t else
            "PDF" if "PDF" in t else "XML" if "XML" in t else "?")


def enlaces(c):
    """Pares (a, b) de casos del mismo fondo con la misma |dif| (+-TOL) unidos por una de las vias."""
    out = []
    for _, g in c.groupby("rut"):
        r = list(g.itertuples())
        for i, a in enumerate(r):
            for b in r[i + 1:]:
                if min(a.dif, b.dif) <= MIN_DIF:
                    continue
                (x, y) = (a, b) if (a.anio_doc, a.orden) <= (b.anio_doc, b.orden) else (b, a)
                misma_celda = x.anio_doc == y.anio_doc and x.columna == y.columna
                # en la misma columna del mismo anio el error se arrastra por la cadena de subtotales y puede
                # sumarse con una diferencia chica (redondeo, diferencia de cambio): tolerancia relativa;
                # entre anios o documentos tiene que ser la misma cifra
                tol = max(TOL, REL * max(a.dif, b.dif)) if misma_celda and x.doc == y.doc else TOL
                if abs(a.dif - b.dif) > tol:
                    continue
                via = None
                if misma_celda and x.doc == y.doc:
                    via = "dentro_del_documento"
                elif misma_celda and x.doc != y.doc:
                    via = "PDF->XML" if x.doc.startswith("PDF") and "XML" in y.doc else "entre_documentos"
                elif y.anio_doc == x.anio_doc + 1 and x.columna == "actual" and (
                        y.columna == "anterior" or y.doc == "continuidad"):
                    via = "t->t+1"
                elif y.anio_doc == x.anio_doc and x.columna == "anterior" and y.doc == "continuidad":
                    via = "comparativo->continuidad"
                if via:
                    out.append((x.caso_id, y.caso_id, via))
    return out


def grupos(ids, pares):
    padre = {i: i for i in ids}

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i
    for a, b, _ in pares:
        padre[raiz(a)] = raiz(b)
    return {i: raiz(i) for i in ids}


def main():
    cu = pd.read_csv(P / "casos_unicos.csv", dtype={"rut": str})
    c = cu[cu["tipo"].astype(str).str.startswith("error")].copy()
    c["doc"] = c["tipo"].map(doc)
    c["dif"] = c["dif"].abs()
    # orden dentro del anio: el comparativo (anterior) antes que el actual; PDF antes que XML; linea antes que total
    c["orden"] = orden(c)
    pares = enlaces(c)
    g = grupos(list(c["caso_id"]), pares)
    c["origen_id"] = c["caso_id"].map(g)
    via = {}
    for a, b, v in pares:
        via.setdefault(b, v)

    filas, mapa = [], []
    for oid, x in c.groupby("origen_id"):
        x = x.sort_values(["anio_doc", "orden"])
        o = x.iloc[0]
        paso = lambda r: (f"{r.anio_doc} {r.doc} {r.estado_raiz}/{r.linea_raiz} ({r.columna})"
                          + (f" [{via[r.caso_id]}]" if r.caso_id in via and r.caso_id != o.caso_id else ""))
        cadena = " -> ".join(paso(r) for r in x.itertuples())
        filas.append(dict(origen_id=int(oid), rut=o.rut, anio_origen=o.anio_doc, documento_origen=o.doc,
                          estado_origen=o.estado_raiz, linea_origen=o.linea_raiz, columna_origen=o.columna,
                          dif=o.dif, tipo_origen=o.tipo, casos=len(x), anios=x["anio_doc"].nunique(),
                          documentos="+".join(sorted(set(x["doc"]))), cadena=cadena))
        for r in x.itertuples():
            mapa.append(dict(caso_id=r.caso_id, origen_id=int(oid), rol="origen" if r.caso_id == o.caso_id else "efecto",
                             via=via.get(r.caso_id, "")))
    o = pd.DataFrame(filas)
    o.to_csv(P / "origen.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(mapa).to_csv(P / "casos_origen.csv", index=False, encoding="utf-8-sig")

    # --- Consola ---
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 200)
    print(f"casos de error: {len(c)}; errores de origen: {len(o)} "
          f"({int((o['casos'] > 1).sum())} con efectos, que suman {int(o.loc[o['casos'] > 1, 'casos'].sum())} casos)")
    print("vias de los enlaces:", pd.Series([v for _, _, v in pares]).value_counts().to_dict())
    print("\ncasos por error de origen:", o["casos"].value_counts().sort_index().to_dict())
    print("\ndocumento del origen x documentos alcanzados (errores con efectos):")
    m = o[o["casos"] > 1]
    print(pd.crosstab(m["documento_origen"], m["documentos"], margins=True).to_string())
    print("\nlos de mas efectos:")
    print(o.sort_values(["casos", "dif"], ascending=False)[["rut", "anio_origen", "dif", "casos", "cadena"]]
          .head(12).to_string(index=False))
    args = sys.argv[1:]
    if args:
        print("\nfondo-anio pedidos:")
        for rut, anio in zip(args[0::2], args[1::2]):
            x = o[(o["rut"] == rut) & o["cadena"].str.contains(rf"(?:^| ){anio} ")]
            print(f"  {rut} {anio}:")
            for r in x.itertuples():
                print(f"     [{r.casos} casos, dif {r.dif:,.0f}] {r.cadena}")
            if x.empty:
                print("     sin error")
    print("\nvalidacion con casos conocidos:")
    for rut, anio, esperado in casos_conocidos("04e"):
        x = o[(o["rut"] == rut) & (o["anio_origen"] <= anio) & o["cadena"].str.contains(str(anio))]
        print(f"  {rut} {anio}: " + (" || ".join(f"[{r.casos}] {r.cadena}" for r in x.itertuples()) or "sin error"))
        print(f"      esperado: {esperado}")
    print(f"\nsalida: {P / 'origen.csv'}, casos_origen.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
