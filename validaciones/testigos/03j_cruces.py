"""
03j: cruces de montos entre dos cuentas, de que lado esta el error
===================================================================

El emparejador (E7) asigna el codigo por la glosa. Un cruce es una cifra del PDF que NO es la de su cuenta
en el XML y SI la de otra cuenta del mismo estado y columna (unica, > MIN_MONTO): el PDF la rotula a, el XML
la tiene en b. Se busca por columna (el monto_de del emparejador exige todos los montos del renglon: un
cruce solo en el actual no lo veia). intercambio si b tiene ademas la cifra de a.
El cruce espejo del 04 compara conjuntos de cifras y no lo ve: las dos cifras estan en los dos documentos.

No son cruces: los montos corridos una linea (monto_desalineado, 03h), los de una linea contra un total
(una linea sola = su subtotal: lectura) y las cifras de 0 o chicas.

Cual de los dos cruzo las cuentas lo dicen:
  xml_vecino  el XML del anio vecino (comparativo de t+1 para la columna actual; cierre de t-1 para la
              anterior) trae para a la cifra que el PDF de t le pone: el XML de t es el unico distinto
              (saldo inicial y final cruzados; revision, confirmado)
  pdf_vecino  el PDF del anio vecino trae para a la cifra del XML de t: el PDF de t es el distinto
  identidad   las reglas del catalogo sobre el XML como esta y con las cuentas como las rotula el PDF
              (a <- cifra de b). Si con la lectura del PDF fallan MENOS, el XML cruzo las cuentas. Que
              fallen mas no dice nada en un cruce de un solo lado (quitar la cifra de b la descuadra
              siempre): solo vota por el PDF en un intercambio. Un cruce dentro de la misma suma no vota.

lado por celda (fondo, anio, estado, columna): XML (solo votos del XML), PDF (solo del PDF),
contradictorio; persistente si cada documento es igual a si mismo en el anio vecino (el XML de t+1 como
el de t, el PDF de t+1 como el de t): la glosa del PDF y la cuenta del XML difieren de forma estable, es
presentacion (un ingreso impreso bajo "pagados", confirmado; otros ingresos y gastos) o el
glosario; glosa_contradictoria si la glosa de la cuenta, en t o en el anio vecino que sirve de testigo, dice
cobro y pago a la vez (03h: "Otros ingresos de operacion pagados", la del modelo CMF): el cruce es efecto
de la glosa, no se puede decir que documento la cruzo; el resto, sin_testigo. Primero se MIDE; luego el 04c: XML -> error del XML (cuenta cruzada),
PDF y persistente -> presentacion (la glosa del PDF dice otra cuenta), el resto revisar.

Uso:
    python validaciones/testigos/03j_cruces.py                 todo
    python validaciones/testigos/03j_cruces.py RUT ANIO ...   ademas, el detalle de esos fondo-anio

Lee:      hechos del XML y del PDF (motor/hechos), renglones_pdf.csv (montos corridos), catalogo/fm
Escribe:  cruces.csv (una fila por cuenta cruzada y columna)
"""
import sys
from collections import defaultdict

import pandas as pd

from comun.emparejar import _catalogo, _totales
from config import CMF_HOME, casos_conocidos
from motor import hechos, reglas

P = CMF_HOME / "procesado"
TOL = 2
MIN_MONTO = 10
SISTEMATICO = 3
CTX = {"PeriodoActual": "actual", "PeriodoAnterior": "anterior"}
VECINO = {"actual": (1, "PeriodoAnterior"), "anterior": (-1, "PeriodoActual")}
COLS = ["rut", "anio", "estado", "columna", "codigo", "monto_de", "tipo", "pagina", "ocr", "pdf", "xml_a", "xml_b",
        "fallas_xml", "fallas_pdf", "xml_vecino", "pdf_vecino", "voto_identidad", "voto_xml_vecino",
        "voto_pdf_vecino", "persistente", "anios_mismo_cruce", "lado"]


def cerca(u, v):
    return u is not None and v is not None and not pd.isna(u) and not pd.isna(v) and abs(abs(u) - abs(v)) <= TOL


def valores_xml(x, canon):
    """{(rut, anio, contexto, estado, concepto): cifra} del XML (totales del fondo, sin series)."""
    x = x[x["serie"] == ""].copy()
    x["can"] = x["codigo"].map(lambda c: canon.get(c, c))
    x = x.drop_duplicates(["rut", "anio", "contexto", "estado", "can"])
    return x, x.set_index(["rut", "anio", "contexto", "estado", "can"])["valor"].to_dict()


def valores_pdf(p):
    """Cifras del PDF con codigo (la primera si el codigo se repite en el estado y columna)."""
    p = p[p["codigo"].notna() & (p["serie"].fillna("") == "") & p["valor"].notna()]
    if "codigo_repetido" in p:
        p = p[~p["codigo_repetido"].fillna(False).astype(bool)]
    return p.drop_duplicates(["rut", "anio", "contexto", "estado", "codigo"])


def cruzados(p, x, vx, corridos=frozenset(), totales=frozenset()):
    """Cifras del PDF cuya cuenta del XML tiene otra cifra y que son la cifra de UNA otra cuenta del XML."""
    idx = defaultdict(list)                     # (rut, anio, contexto, estado) -> [(|cifra|, concepto)]
    for k, v in vx.items():
        if v is not None and abs(v) > MIN_MONTO:
            idx[k[:4]].append((abs(v), k[4]))
    filas = []
    for r in p.itertuples():
        a, v = r.codigo, r.valor
        xa = vx.get((r.rut, r.anio, r.contexto, r.estado, a))
        if xa is None or abs(v) <= MIN_MONTO or cerca(v, xa) or (r.rut, r.anio, r.estado, a) in corridos:
            continue
        # una linea contra un total no es cruce (una linea sola = su subtotal: lectura)
        bs = {b for w, b in idx.get((r.rut, r.anio, r.contexto, r.estado), [])
              if b != a and abs(w - abs(v)) <= TOL and (a in totales) == (b in totales)}
        if len(bs) != 1:
            continue
        b = bs.pop()
        filas.append(dict(rut=r.rut, anio=r.anio, estado=r.estado, columna=CTX[r.contexto], codigo=a, monto_de=b,
                          pagina=getattr(r, "pagina", pd.NA), ocr=bool(getattr(r, "ocr", False)), pdf=v,
                          xml_a=xa, xml_b=vx[(r.rut, r.anio, r.contexto, r.estado, b)]))
    m = pd.DataFrame(filas, columns=["rut", "anio", "estado", "columna", "codigo", "monto_de", "pagina", "ocr", "pdf",
                                     "xml_a", "xml_b"])
    if m.empty:
        return m.assign(tipo=pd.Series(dtype=str), anios_mismo_cruce=pd.Series(dtype=int))
    par = set(zip(m["rut"], m["anio"], m["estado"], m["columna"], m["codigo"], m["monto_de"]))
    m["tipo"] = ["intercambio" if (r, y, e, c, b, a) in par else "monto_cruzado"
                 for r, y, e, c, a, b in zip(m["rut"], m["anio"], m["estado"], m["columna"], m["codigo"], m["monto_de"])]
    m["anios_mismo_cruce"] = m.groupby(["rut", "estado", "codigo", "monto_de"])["anio"].transform("nunique")
    return m


def fallas(h: pd.DataFrame) -> dict:
    """{(archivo, contexto): identidades del catalogo que no cuadran (|dif| > TOL)}."""
    if h.empty:
        return {}
    e = reglas.por_columna(h)
    if e.empty:
        return {}
    e = e.reset_index()
    e["falla"] = (e["total"] - e["suma_partes"]).abs() > TOL
    return e.groupby(["archivo", "contexto"])["falla"].sum().to_dict()


def votar(m, x, vx, vp):
    """Agrega a cada cruce los testigos y el lado de su celda (fondo, anio, estado, columna)."""
    if m.empty:
        return pd.DataFrame(columns=COLS)
    clave = set(zip(m["rut"], m["anio"]))
    hx = x[[(r, a) in clave for r, a in zip(x["rut"], x["anio"])]]
    base = fallas(hx)
    por = {k: g for k, g in hx.groupby(["rut", "anio"])}
    ctx_de = {v: k for k, v in CTX.items()}
    filas = []
    for (rut, anio, est, col), g in m.groupby(["rut", "anio", "estado", "columna"]):
        ctx = ctx_de[col]
        h = por.get((rut, anio))
        f0 = f1 = None
        if h is not None:
            h1 = h[h["contexto"] == ctx].copy()
            nuevo = dict(zip(g["codigo"], g["xml_b"]))
            sel = (h1["estado"] == est) & h1["can"].isin(nuevo)
            h1.loc[sel, "valor"] = h1.loc[sel, "can"].map(nuevo)
            arch = h1["archivo"].iloc[0] if len(h1) else None
            f0 = base.get((arch, ctx), 0)
            f1 = fallas(h1).get((arch, ctx), 0)
        inter = (g["tipo"] == "intercambio").all()
        v_id = ("XML" if f0 is not None and f1 < f0 else
                "PDF" if f0 is not None and f1 > f0 and inter else "")
        d, ctx_v = VECINO[col]
        for r in g.itertuples():
            xv = vx.get((rut, anio + d, ctx_v, est, r.codigo))
            pv = vp.get((rut, anio + d, ctx_v, est, r.codigo))
            filas.append(dict(r._asdict(), fallas_xml=f0, fallas_pdf=f1, xml_vecino=xv, pdf_vecino=pv,
                              voto_identidad=v_id, voto_xml_vecino=cerca(xv, r.pdf) and not cerca(xv, r.xml_a),
                              voto_pdf_vecino=cerca(pv, r.xml_a) and not cerca(pv, r.pdf),
                              persistente=cerca(xv, r.xml_a) and cerca(pv, r.pdf)))
    c = pd.DataFrame(filas).drop(columns="Index", errors="ignore")
    k = [c["rut"], c["anio"], c["estado"], c["columna"]]
    gx = ((c["voto_identidad"] == "XML") | c["voto_xml_vecino"]).groupby(k).transform("any")
    gp = ((c["voto_identidad"] == "PDF") | c["voto_pdf_vecino"]).groupby(k).transform("any")
    gs = c["persistente"].groupby(k).transform("any")
    c["lado"] = ["contradictorio" if a and b else "XML" if a else "PDF" if b else "persistente" if s else "sin_testigo"
                 for a, b, s in zip(gx, gp, gs)]
    return c[COLS]


def por_glosa(c, ruta=P / "formato.csv"):
    """lado glosa_contradictoria: la cuenta a o b con glosa contradictoria (03h) en t o en el anio vecino."""
    if c.empty or not ruta.exists():
        return c
    f = pd.read_csv(ruta, dtype={"rut": str, "codigo": str}, usecols=["rut", "anio", "estado", "codigo", "tipo"])
    g = set(map(tuple, f[f["tipo"] == "glosa_contradictoria"][["rut", "anio", "estado", "codigo"]].values))
    d = c["columna"].map(lambda x: VECINO[x][0])
    hit = [any(k in g for k in ((r, y, e, a), (r, y + dd, e, a), (r, y, e, b)))
           for r, y, e, a, b, dd in zip(c["rut"], c["anio"], c["estado"], c["codigo"], c["monto_de"], d)]
    k = [c["rut"], c["anio"], c["estado"], c["columna"]]
    hit = pd.Series(hit, index=c.index).groupby(k).transform("any")
    c.loc[hit, "lado"] = "glosa_contradictoria"
    return c


def main():
    _, canon = _catalogo()
    x, vx = valores_xml(hechos.xml(), canon)
    p = hechos.pdf()
    p["codigo"] = p["codigo"].map(lambda c: canon.get(c, c) if isinstance(c, str) else c)
    p = valores_pdf(p)
    vp = p.set_index(["rut", "anio", "contexto", "estado", "codigo"])["valor"].to_dict()
    r = pd.read_csv(P / "renglones_pdf.csv", dtype={"rut": str, "codigo": str}, low_memory=False,
                    usecols=lambda c: c in {"rut", "anio", "estado", "codigo", "monto_de_vecino"})
    corr = r[r.get("monto_de_vecino", pd.Series(False, index=r.index)).fillna(False).astype(bool)]
    corridos = set(zip(corr["rut"], corr["anio"], corr["estado"], corr["codigo"]))
    if (P / "formato.csv").exists():        # el monto desalineado en una columna (03h) tampoco es cruce
        f = pd.read_csv(P / "formato.csv", dtype={"rut": str, "codigo": str}, usecols=["rut", "anio", "estado",
                                                                                         "codigo", "tipo"])
        f = f[f["tipo"] == "monto_desalineado_columna"]
        corridos |= set(zip(f["rut"], f["anio"], f["estado"], f["codigo"]))
    corridos = frozenset(corridos)
    m = cruzados(p, x, vx, corridos, _totales())
    c = por_glosa(votar(m, x, vx, vp))
    c.to_csv(P / "cruces.csv", index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 230)
    print(f"cruces (cuenta x columna): {len(c)} en {c[['rut', 'anio']].drop_duplicates().shape[0]} fondo-anio "
          f"({c['tipo'].value_counts().to_dict()})")
    celdas = c.drop_duplicates(["rut", "anio", "estado", "columna"])
    print("\nlado por celda (fondo, anio, estado, columna):")
    print(pd.crosstab(celdas["lado"], celdas["anios_mismo_cruce"] >= SISTEMATICO,
                      margins=True).rename(columns={False: "puntual", True: "sistematico"}).to_string())
    print("\ntestigos (cuenta x columna): identidad x vecinos")
    print(pd.crosstab(c["voto_identidad"].replace("", "-"),
                      c["voto_xml_vecino"].map({True: "xml_vecino", False: "-"}) + " / "
                      + c["voto_pdf_vecino"].map({True: "pdf_vecino", False: "-"}), margins=True).to_string())
    print("\nestado x lado (celdas):")
    print(pd.crosstab(celdas["estado"], celdas["lado"], margins=True).to_string())
    corto = lambda s: str(s)[:34]
    ver = c.assign(codigo=c["codigo"].map(corto), monto_de=c["monto_de"].map(corto))
    cols = ["rut", "anio", "estado", "columna", "codigo", "monto_de", "pdf", "xml_a", "fallas_xml", "fallas_pdf",
            "xml_vecino", "pdf_vecino", "anios_mismo_cruce", "lado"]
    for lado in ("XML", "contradictorio"):
        x_ = ver[ver["lado"] == lado]
        print(f"\nlado {lado} (muestra, {x_[['rut', 'anio', 'estado', 'columna']].drop_duplicates().shape[0]} celdas):")
        print(x_.drop_duplicates(["rut", "anio", "estado", "columna"]).sample(min(15, len(x_.drop_duplicates(
            ["rut", "anio", "estado", "columna"]))), random_state=1).sort_values(["rut", "anio"])[cols]
              .to_string(index=False))
    args = sys.argv[1:]
    pedidos = list(zip(args[0::2], map(int, args[1::2]))) + [(a, b) for a, b, _ in casos_conocidos("03j")]
    if pedidos:
        print("\nfondo-anio pedidos:")
        for rut, anio in pedidos:
            x_ = ver[(ver["rut"] == rut) & (ver["anio"] == anio)]
            print(f"  {rut} {anio}:" + (" sin cruce" if x_.empty else ""))
            if len(x_):
                print(x_[cols[2:]].to_string(index=False))
    print(f"\nsalida: {P / 'cruces.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
