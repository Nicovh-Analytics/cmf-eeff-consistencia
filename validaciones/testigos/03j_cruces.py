"""
03j: cruces de montos entre dos cuentas, de que lado esta el error
===================================================================

El emparejador (E7) asigna el codigo por la glosa y deja al XML como testigo: si los montos de un renglon
son los de OTRA cuenta del XML lo marca (monto_de) y el 03h lo llama intercambio (dos renglones con los
montos del otro) o monto_cruzado (uno solo). El cruce espejo del 04 compara conjuntos de cifras y no lo
ve: las dos cifras estan en los dos documentos. Cual de los dos cruzo las cuentas lo dicen tres testigos:

  identidad   las reglas del catalogo (sumas y cruces entre estados) sobre el XML como esta y sobre el XML
              con las cuentas como las rotula el PDF (a <- monto de b). Si con la lectura del PDF fallan
              menos identidades, el XML cruzo las cuentas; si fallan mas, el PDF. Un cruce dentro de la
              misma suma (dos ingresos) no cambia ninguna identidad: no vota.
              (10369/10367 2023: el XML trae el total activo y el activo neto cruzados)
  xml_vecino  el XML del anio vecino (comparativo de t+1 para la columna actual; cierre de t-1 para la
              anterior): si trae para la cuenta a el monto que el PDF de t le pone, el XML de t la cruzo y
              el siguiente la corrigio
  pdf_vecino  el PDF del anio vecino: si trae para la cuenta a el monto que el XML de t le pone, el PDF de
              t la cruzo (el siguiente ya la rotula bien)

lado:  XML (solo votos del XML), PDF (solo del PDF), contradictorio o sin_testigo. El mismo cruce en
SISTEMATICO o mas anios del fondo es plantilla: del PDF o del glosario (BCI "percibidos": era nuestro),
y sin otro voto queda sin_testigo. Primero se MIDE; luego el 04c lo usara: XML -> error del XML (cuenta
cruzada); PDF -> presentacion (monto_otra_cuenta: el PDF imprime los montos de una cuenta con la glosa de
otra); el resto, revisar.

Uso:
    python validaciones/testigos/03j_cruces.py                 todo
    python validaciones/testigos/03j_cruces.py 8872 2011 ...   ademas, el detalle de esos fondo-anio

Lee:      renglones_pdf.csv (03b), hechos del XML y del PDF (motor/hechos), catalogo/fm
Escribe:  cruces.csv (una fila por cuenta cruzada y columna)
"""
import sys

import pandas as pd

from comun.emparejar import _catalogo
from config import CMF_HOME, casos_conocidos
from motor import hechos, reglas

P = CMF_HOME / "procesado"
TOL = 2
SISTEMATICO = 3
CTX = {"actual": "PeriodoActual", "anterior": "PeriodoAnterior"}
VECINO = {"actual": (1, "PeriodoAnterior"), "anterior": (-1, "PeriodoActual")}
COLS = ["rut", "anio", "estado", "columna", "codigo", "monto_de", "tipo", "pagina", "ocr", "xml_a", "xml_b",
        "fallas_xml", "fallas_pdf", "xml_vecino", "pdf_vecino", "voto_identidad", "voto_xml_vecino",
        "voto_pdf_vecino", "anios_mismo_cruce", "lado"]


def cerca(u, v):
    return u is not None and v is not None and not pd.isna(u) and not pd.isna(v) and abs(abs(u) - abs(v)) <= TOL


def cruzados(r: pd.DataFrame) -> pd.DataFrame:
    """Renglones del PDF con los montos de otra cuenta del XML (no corridos una linea: eso es
    monto_desalineado, presentacion). tipo: intercambio si la otra cuenta tiene los montos de esta."""
    vecino = r.get("monto_de_vecino", pd.Series(False, index=r.index)).fillna(False).astype(bool)
    m = r[r["monto_de"].notna() & r["codigo"].notna() & ~vecino & (r["codigo"] != r["monto_de"])].copy()
    m = m.drop_duplicates(["rut", "anio", "estado", "codigo"])
    par = set(zip(m["rut"], m["anio"], m["estado"], m["codigo"], m["monto_de"]))
    m["tipo"] = ["intercambio" if (a, b, e, y, x) in par else "monto_cruzado"
                 for a, b, e, x, y in zip(m["rut"], m["anio"], m["estado"], m["codigo"], m["monto_de"])]
    n = m.groupby(["rut", "estado", "codigo", "monto_de"])["anio"].transform("nunique")
    m["anios_mismo_cruce"] = n
    m["ocr"] = m["ocr"].fillna(False).astype(bool) if "ocr" in m else False
    return m[["rut", "anio", "estado", "codigo", "monto_de", "tipo", "pagina", "ocr", "anios_mismo_cruce"]]


def fallas(h: pd.DataFrame) -> dict:
    """{(archivo, contexto): identidades del catalogo que no cuadran (|dif| > TOL)}."""
    e = reglas.por_columna(h).reset_index()
    e["falla"] = (e["total"] - e["suma_partes"]).abs() > TOL
    return e.groupby(["archivo", "contexto"])["falla"].sum().to_dict()


def votar(m, x, p, canon):
    """Una fila por cuenta cruzada y columna, con los tres testigos y el lado."""
    x = x[x["serie"] == ""].copy()
    x["can"] = x["codigo"].map(lambda c: canon.get(c, c))
    vx = (x.drop_duplicates(["rut", "anio", "contexto", "estado", "can"])
          .set_index(["rut", "anio", "contexto", "estado", "can"])["valor"].to_dict())
    p = p[p["codigo"].notna() & (p["serie"].fillna("") == "")]
    if "codigo_repetido" in p:
        p = p[~p["codigo_repetido"].fillna(False).astype(bool)]
    vp = (p.drop_duplicates(["rut", "anio", "contexto", "estado", "codigo"])
          .set_index(["rut", "anio", "contexto", "estado", "codigo"])["valor"].to_dict())
    arch = x.drop_duplicates(["rut", "anio"]).set_index(["rut", "anio"])["archivo"].to_dict()
    clave = set(zip(m["rut"], m["anio"]))
    xa_ = x[[(r, a) in clave for r, a in zip(x["rut"], x["anio"])]]
    base = fallas(xa_) if len(xa_) else {}
    por_archivo = {k: g for k, g in xa_.groupby("archivo")}

    filas = []
    for (rut, anio, est), g in m.groupby(["rut", "anio", "estado"]):
        a_ = arch.get((rut, anio))
        hx = por_archivo.get(a_)
        for col, ctx in CTX.items():
            pares = []
            for r in g.itertuples():
                xa, xb = vx.get((rut, anio, ctx, est, r.codigo)), vx.get((rut, anio, ctx, est, r.monto_de))
                if xb is None or cerca(xa, xb):
                    continue                    # sin monto de la otra cuenta o iguales: no se distingue
                pares.append((r, xa, xb))
            if not pares:
                continue
            # identidad: el XML con las cuentas como las rotula el PDF (a <- monto de b, todas a la vez)
            f0 = f1 = None
            if hx is not None:
                h1 = hx.copy()
                nuevo = {r.codigo: xb for r, xa, xb in pares if xa is not None}
                sel = (h1["contexto"] == ctx) & (h1["estado"] == est) & (h1["serie"] == "") & h1["can"].isin(nuevo)
                h1.loc[sel, "valor"] = h1.loc[sel, "can"].map(nuevo)
                f0 = base.get((a_, ctx), 0)
                f1 = fallas(h1[h1["contexto"] == ctx]).get((a_, ctx), 0) if sel.any() else f0
            v_id = "XML" if f0 is not None and f1 < f0 else "PDF" if f0 is not None and f1 > f0 else ""
            d, ctx_v = VECINO[col]
            for r, xa, xb in pares:
                xv = vx.get((rut, anio + d, ctx_v, est, r.codigo))
                pv = vp.get((rut, anio + d, ctx_v, est, r.codigo))
                filas.append(dict(rut=rut, anio=anio, estado=est, columna=col, codigo=r.codigo, monto_de=r.monto_de,
                                  tipo=r.tipo, pagina=r.pagina, ocr=r.ocr, xml_a=xa, xml_b=xb, fallas_xml=f0,
                                  fallas_pdf=f1, xml_vecino=xv, pdf_vecino=pv, voto_identidad=v_id,
                                  voto_xml_vecino=cerca(xv, xb) and not cerca(xv, xa),
                                  voto_pdf_vecino=cerca(pv, xa) and not cerca(pv, xb),
                                  anios_mismo_cruce=r.anios_mismo_cruce))
    c = pd.DataFrame(filas, columns=COLS[:-1])
    if c.empty:
        return pd.DataFrame(columns=COLS)
    # el lado se decide por celda (fondo, anio, estado, columna): las cuentas cruzadas juntas
    k = ["rut", "anio", "estado", "columna"]
    vxml = (c["voto_identidad"] == "XML") | c["voto_xml_vecino"]
    vpdf = (c["voto_identidad"] == "PDF") | c["voto_pdf_vecino"]
    gx = vxml.groupby([c[x] for x in k]).transform("any")
    gp = vpdf.groupby([c[x] for x in k]).transform("any")
    c["lado"] = ["contradictorio" if a and b else "XML" if a else "PDF" if b else "sin_testigo" for a, b in zip(gx, gp)]
    return c


def main():
    r = pd.read_csv(P / "renglones_pdf.csv", dtype={"rut": str, "codigo": str, "monto_de": str}, low_memory=False,
                    usecols=lambda c: c in {"rut", "anio", "estado", "pagina", "codigo", "monto_de", "monto_de_vecino",
                                            "ocr"})
    _, canon = _catalogo()
    m = cruzados(r)
    c = votar(m, hechos.xml(), hechos.pdf(), canon)
    c.to_csv(P / "cruces.csv", index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 220)
    print(f"renglones cruzados: {len(m)} en {m[['rut', 'anio']].drop_duplicates().shape[0]} fondo-anio "
          f"({m['tipo'].value_counts().to_dict()}); con montos distinguibles, cuenta x columna: {len(c)}")
    celdas = c.drop_duplicates(["rut", "anio", "estado", "columna"])
    print("\nlado por celda (fondo, anio, estado, columna):")
    print(pd.crosstab(celdas["lado"], celdas["anios_mismo_cruce"] >= SISTEMATICO,
                      margins=True).rename(columns={False: "puntual", True: "sistematico"}).to_string())
    print("\ntestigos que votan (cuenta x columna):")
    print(pd.crosstab(c["voto_identidad"].replace("", "-"),
                      c["voto_xml_vecino"].map({True: "xml_vecino", False: "-"}) + " / "
                      + c["voto_pdf_vecino"].map({True: "pdf_vecino", False: "-"}), margins=True).to_string())
    print("\nestado x lado (celdas):")
    print(pd.crosstab(celdas["estado"], celdas["lado"], margins=True).to_string())
    corto = lambda s: str(s)[:38]
    ver = c.assign(codigo=c["codigo"].map(corto), monto_de=c["monto_de"].map(corto))
    cols = ["rut", "anio", "estado", "columna", "codigo", "monto_de", "xml_a", "xml_b", "fallas_xml", "fallas_pdf",
            "xml_vecino", "pdf_vecino", "anios_mismo_cruce", "lado"]
    print("\nlado XML (muestra):")
    print(ver[ver["lado"] == "XML"][cols].head(25).to_string(index=False))
    args = sys.argv[1:]
    pedidos = list(zip(args[0::2], map(int, args[1::2]))) + [(a, b) for a, b, _ in casos_conocidos("03j")]
    if pedidos:
        print("\nfondo-anio pedidos:")
        for rut, anio in pedidos:
            x = ver[(ver["rut"] == rut) & (ver["anio"] == anio)]
            print(f"  {rut} {anio}:" + (" sin cruce" if x.empty else ""))
            if len(x):
                print(x[cols[2:]].to_string(index=False))
    print(f"\nsalida: {P / 'cruces.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
