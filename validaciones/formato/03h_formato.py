"""
03h: formato de presentacion del PDF frente al modelo CMF (categoria propia, no son errores de cifra)
=====================================================================================================

Un hallazgo de formato no cambia ninguna cifra: dice como se presento. Se mide por fondo-anio y por AGF
y anio (evolucion), contra el modelo de la CMF (catalogo/fm/oficial: glosa y signo de cada cuenta);
IFRS (NIC 1 / NIC 7) queda como contraste posterior.

Hallazgos por renglon (formato.csv):
  parentesis          negativo con parentesis sin par o duplicados ("59.820.025)", "((31.340)")  [lector]
  miles               agrupacion de miles irregular ("26.767.9609")                              [lector]
  decimal             cifras en miles con decimales ("86.451,00")                                [lector]
  signo_modelo        una cuenta del ESF (todas (+) en el modelo) impresa negativa
  signo_mixto         en el mismo ERI o EFE, unas cuentas (-) del modelo impresas negativas y otras
                      positivas: la minoria. Si todas van positivas es la convencion de la AGF
                      ("sin_signo", formato_fondo.csv), no un hallazgo por renglon
  rotulo_otra_cuenta  la glosa es de otra cuenta y los montos y la posicion son de esta  [emparejador]
                      (la glosa casi igual a la oficial de esa otra cuenta, parecido >= 0,85)
  redaccion_ambigua   igual, pero la glosa solo se parece a la otra cuenta: redaccion propia de la AGF
  monto_desalineado   los montos de la cuenta del renglon de al lado, impresos una linea corridos
  intercambio         dos renglones con los montos del otro (glosas o montos cruzados entre si)
  monto_cruzado       la glosa dice una cuenta y TODOS sus montos son los de otra cuenta del XML: o el
                      PDF puso los montos en otra fila o el XML los cruzo (lo resuelve el error de origen)
  titulo_otro_estado  titulo de un estado impreso sobre otro                                  [lector]
  pagina_repetida     el mismo estado impreso dos veces (glosas y montos iguales)           [emparejador]
  glosa_desactualizada  el ECP fecha el bloque con otro anio que el que calza con el XML          [03d]
  glosa_contradictoria  en el EFE, la glosa dice una direccion con el sustantivo y la contraria con el
                      participio ("Otros ingresos de operacion pagados"): no deja ver si es cobro o pago
                      (NIC 7.18(a) pide cobros y pagos brutos por separado). El detalle dice si es la glosa
                      del modelo CMF (esa misma glosa esta en el modelo) o redaccion de la AGF

Por fondo-anio (formato_fondo.csv): ademas, la ADHERENCIA de la redaccion al modelo: parecido medio
(0-1) de cada glosa con la glosa oficial de su cuenta (la mejor entre sinonimos de las plantillas).
Por AGF y anio (formato_agf.csv): fondos, % con cada tipo de hallazgo y adherencia media.

No cambia el conteo de errores (04c): es la base para decidir que tipos pasan a ser casos de
presentacion y para el informe por AGF.

Lee:      renglones_pdf.csv (03b), ecp_bloques.csv (03d), encabezados.csv, catalogo/fm
Escribe:  formato.csv, formato_fondo.csv, formato_agf.csv
"""
import re
import sys
from difflib import SequenceMatcher

import pandas as pd

import catalogo
from comun.emparejar import _tokens
from config import CMF_HOME, nombres_agf

P = CMF_HOME / "procesado"
COLS = ["rut", "anio", "estado", "pagina", "codigo", "columna", "tipo", "detalle", "ocr"]
ROTULO = 0.85      # parecido de la glosa con la oficial de la otra cuenta para llamarlo rotulo
TIPOS = ["parentesis", "miles", "decimal", "signo_modelo", "signo_mixto", "rotulo_otra_cuenta", "redaccion_ambigua",
         "monto_desalineado", "intercambio", "monto_cruzado",
         "titulo_otro_estado", "pagina_repetida", "glosa_desactualizada", "glosa_contradictoria"]
# direccion del flujo en la glosa: sustantivo y participio (dividendos e intereses pueden ser cobros o pagos)
ENTRA_N, SALE_N = r"ingreso|venta|cobro|aporte|colocacion", r"gasto|egreso|compra|rescate|pago"
ENTRA_P, SALE_P = r"recibid|percibid|cobrad", r"pagad"


def oficial():
    """codigo -> (signo, glosa oficial sin el "(+)") del modelo CMF; sinonimos por concepto."""
    o = pd.read_csv(catalogo.DIR / "fm" / "oficial" / "codigos.csv", dtype=str).fillna("")
    o = o[o["por_serie"] != "si"]
    glosa = {c: re.sub(r"\s*\([+-]+\)\s*$", "", g).strip() for c, g in zip(o["codigo"], o["glosa"])}
    con = catalogo.conceptos()
    signo = {c: s for c, s in zip(con["codigo"], con["signo"].fillna(""))}
    canon = {c: (a or c) for c, a in zip(con["codigo"], con["alternativo_de"].fillna(""))}
    sinon = {}
    for c in glosa:
        sinon.setdefault(canon.get(c, c), []).append(c)
    return glosa, signo, sinon


def contradictoria(gl):
    """La glosa nombra una direccion y la contraria: sustantivo de entrada con participio de salida
    ("ingresos ... pagados") o al reves. "Otros ingresos (egresos)" (neto, sin participio) no lo es."""
    t = " ".join(_tokens(gl))
    en, sn = re.search(ENTRA_N, t), re.search(SALE_N, t)
    ep, sp = re.search(ENTRA_P, t), re.search(SALE_P, t)
    return bool((sp and en and not sn) or (ep and sn and not en))


def parecido(a, b):
    ta, tb = " ".join(_tokens(a)), " ".join(_tokens(b))
    return SequenceMatcher(None, ta, tb).ratio() if ta and tb else 0.0


def leer():
    r = pd.read_csv(P / "renglones_pdf.csv", dtype={"rut": str, "codigo": str}, low_memory=False)
    for c in ("formato", "glosa_de", "monto_de", "monto_de_vecino", "rotulo", "codigo_plantilla", "pagina_repetida"):
        if c not in r:
            r[c] = pd.NA
    r["ocr"] = r["ocr"].fillna(False).astype(bool) if "ocr" in r else False
    r = r[r["metodo"] != "encabezado"]
    return r


def convencion_signo(r, signo):
    """Por fondo-anio y estado (ERI, EFE), las cuentas que el modelo resta (-): cuantas se imprimieron
    negativas y cuantas positivas. convencion: "modelo" (todas negativas), "sin_signo" (todas positivas: la
    AGF presenta los gastos y salidas sin parentesis; es su convencion, no un hallazgo por renglon) o
    "mixta" (en el mismo estado unas si y otras no: las de la minoria son hallazgo signo_mixto)."""
    s = r[r["codigo"].notna() & r["estado"].isin(["ERI", "EFE"])].copy()
    s = s[s["codigo"].map(signo).fillna("") == "-"]
    v = s.melt(id_vars=["rut", "anio", "estado", "pagina", "codigo", "ocr"], value_vars=["actual", "anterior"],
               var_name="columna", value_name="valor")
    v["valor"] = pd.to_numeric(v["valor"], errors="coerce")
    v = v[v["valor"].notna() & (v["valor"] != 0)]
    v["pos"] = v["valor"] > 0
    c = v.groupby(["rut", "anio", "estado"])["pos"].agg(positivas="sum", lineas="size").reset_index()
    c["convencion"] = ["sin_signo" if p == n else "modelo" if p == 0 else "mixta"
                       for p, n in zip(c["positivas"], c["lineas"])]
    return v.merge(c, on=["rut", "anio", "estado"]), c


def distingue(gl, propia, otra, glosa, sinon):
    """La glosa dice una palabra que distingue a la OTRA cuenta de la propia en el modelo ("antes" frente a
    "despues" de distribucion, "financiamiento" frente a "operacion") y ninguna que distinga a la propia.
    Sin el modelo (glosa None) se acepta. Una glosa cortada que no dice ninguna no es un rotulo."""
    if glosa is None:
        return True
    tok = lambda c: set().union(*(set(_tokens(glosa[x])) for x in sinon.get(c, [c]) if x in glosa), set())
    tp, to, tg = tok(propia), tok(otra), set(_tokens(gl))
    return bool(tg & (to - tp)) and not (tg & (tp - to))


def hallazgos(r, signo, ecp=None, glosa=None, sinon=None):
    """ecp: ecp_bloques.csv del 03d (glosa desactualizada); None = sin el ECP. glosa/sinon (oficial()):
    para separar el rotulo de otra cuenta de una redaccion ambigua; None = todo glosa_de es rotulo."""
    out = []
    base = lambda d: d[["rut", "anio", "estado", "pagina", "codigo", "ocr"]].copy()
    rp = r[r.get("pagina_repetida", pd.Series(False, index=r.index)).fillna(False).astype(bool)]
    rp = rp.drop_duplicates(["rut", "anio", "pagina"])
    d = base(rp)
    d["codigo"], d["columna"], d["tipo"] = "", "", "pagina_repetida"
    d["detalle"] = "el " + rp["estado"].astype(str) + " repite una pagina anterior"
    out.append(d)
    r = r[r["codigo"].notna() | r["rotulo"].notna()]     # renglones del estado (los de notas no tienen cuenta)

    # formato del monto (lector): "parentesis:59.820.025)" -> tipo y token; columna por el valor
    f = r[r["formato"].notna() & r["codigo"].notna()]
    filas = [dict(rut=x.rut, anio=x.anio, estado=x.estado, pagina=x.pagina, codigo=x.codigo, columna="",
                  tipo=tok.split(":", 1)[0], detalle=tok.split(":", 1)[1], ocr=x.ocr)
             for x in f.itertuples(index=False) for tok in str(x.formato).split()]
    out.append(pd.DataFrame(filas, columns=COLS))

    # signo: en el ESF todas las cuentas son (+): una negativa es hallazgo. En ERI y EFE el signo (+) del
    # modelo dice como suma la cuenta, no que no pueda ser negativa (un flujo neto, intereses netos): solo
    # se mira la convencion de las cuentas (-) y, si es mixta en el estado, la minoria es hallazgo.
    s = r[r["codigo"].notna() & (r["estado"] == "ESF")].copy()
    s = s[s["codigo"].map(signo).fillna("") == "+"]
    for col in ("actual", "anterior"):
        v = pd.to_numeric(s[col], errors="coerce")
        mal = v.notna() & (v < 0)
        d = base(s[mal])
        d["columna"], d["tipo"] = col, "signo_modelo"
        d["detalle"] = [f"impreso {x:,.0f}; modelo (+)" for x in v[mal]]
        out.append(d)
    v, _ = convencion_signo(r, signo)
    v = v[v["convencion"] == "mixta"]
    minoria = v["pos"] == (v["positivas"] * 2 <= v["lineas"])    # las positivas si no son mas (empate: el modelo manda)
    v = v[minoria]
    out.append(pd.DataFrame({"rut": v["rut"], "anio": v["anio"], "estado": v["estado"], "pagina": v["pagina"],
                             "codigo": v["codigo"], "columna": v["columna"], "tipo": "signo_mixto",
                             "detalle": [f"impreso {x:,.0f}; {p} de {n} cuentas (-) del estado positivas"
                                         for x, p, n in zip(v["valor"], v["positivas"], v["lineas"])],
                             "ocr": v["ocr"]}))

    # rotulo de otra cuenta: solo si la glosa es casi la oficial de esa otra cuenta (>= ROTULO). Con un
    # parecido menor es una redaccion ambigua ("Cuentas y documentos por pagar por operaciones"), no un rotulo.
    # Ademas tiene que decir la palabra que distingue a la otra cuenta (distingue): una glosa cortada
    # "Aumento (disminucion) de activo neto ... originadas por act" sirve igual al antes y al despues de
    # distribucion; no es un rotulo equivocado sino una redaccion que no los distingue.
    g = r[r["glosa_de"].notna()].copy()
    sim = lambda gl, c: max((parecido(gl, glosa[x]) for x in sinon.get(c, [c]) if x in glosa), default=0)
    if glosa is not None and len(g):
        g["p"] = [sim(gl, c) for gl, c in zip(g["glosa"].astype(str), g["glosa_de"].astype(str))]
        g["p_propia"] = [sim(gl, c) for gl, c in zip(g["glosa"].astype(str), g["codigo"].astype(str))]
    else:
        g["p"], g["p_propia"] = 1.0, 0.0
    d = base(g)
    d["columna"] = ""
    d["tipo"] = ["rotulo_otra_cuenta" if p >= ROTULO and distingue(gl, c, o, glosa, sinon) else "redaccion_ambigua"
                 for p, gl, c, o in zip(g["p"], g["glosa"].astype(str), g["codigo"].astype(str), g["glosa_de"].astype(str))]
    d["detalle"] = ("glosa de " + g["glosa_de"].astype(str) + " (parecido " + g["p"].round(2).astype(str)
                    + " vs propia " + g["p_propia"].round(2).astype(str) + "): " + g["glosa"].astype(str).str[:80])
    out.append(d)

    # montos de otra cuenta, en tres formas:
    #   monto_desalineado  los montos de la cuenta del renglon de al lado (sin montos) quedaron en este:
    #                      impresos una linea corridos (presentacion; las cifras estan bien)
    #   intercambio        dos renglones con los montos del otro (glosas o montos cruzados entre si: PDF o XML)
    #   monto_cruzado      el resto (de que lado esta el error: error de origen)
    m = r[r["monto_de"].notna()].copy()
    vecino = m.get("monto_de_vecino", pd.Series(False, index=m.index)).fillna(False).astype(bool)
    par = set(zip(m["rut"], m["anio"], m["estado"], m["codigo"], m["monto_de"]))
    inter = [(a, b, e, y, x) in par for a, b, e, x, y in zip(m["rut"], m["anio"], m["estado"], m["codigo"], m["monto_de"])]
    d = base(m)
    d["columna"] = ""
    d["tipo"] = ["monto_desalineado" if v else "intercambio" if i else "monto_cruzado" for v, i in zip(vecino, inter)]
    d["detalle"] = "glosa " + m["codigo"].astype(str) + ", montos de " + m["monto_de"].astype(str)
    out.append(d)

    gc = r[r["codigo"].notna() & (r["estado"] == "EFE") & r["glosa"].notna()]
    gc = gc[[contradictoria(g) for g in gc["glosa"].astype(str)]]
    if len(gc):
        cache = {}

        def del_modelo(g, c):
            if glosa is None:
                return False
            k = (g, c)
            if k not in cache:
                cache[k] = any(contradictoria(glosa[x]) and parecido(g, glosa[x]) >= ROTULO
                               for x in sinon.get(c, [c]) if x in glosa)
            return cache[k]
        d = base(gc)
        d["columna"], d["tipo"] = "", "glosa_contradictoria"
        d["detalle"] = [("glosa del modelo CMF: " if del_modelo(g, c) else "redaccion de la AGF: ") + g[:80]
                        for g, c in zip(gc["glosa"].astype(str), gc["codigo"].astype(str))]
        out.append(d)

    t = r[r["rotulo"].notna()].drop_duplicates(["rut", "anio", "pagina"])
    d = base(t)
    d["codigo"], d["columna"], d["tipo"] = "", "", "titulo_otro_estado"
    d["detalle"] = "titulo " + t["rotulo"].astype(str) + " sobre el " + t["estado"].astype(str)
    out.append(d)

    if ecp is not None:
        b = ecp
        b = b[(b["fechado_por"] == "xml_corrige_texto")
              & ~((b["columna"] == "anterior") & (b["anio"] == b["anio_texto"]))]   # mismo filtro que el 03d
        out.append(pd.DataFrame({"rut": b["rut"], "anio": b["anio"], "estado": "ECP", "pagina": b["pagina"],
                                 "codigo": "", "columna": b["columna"], "tipo": "glosa_desactualizada",
                                 "detalle": "texto " + b["anio_texto"].astype("Int64").astype(str), "ocr": b["ocr"]}))
    return pd.concat([o.reindex(columns=COLS) for o in out if len(o)], ignore_index=True).reindex(columns=COLS)


def adherencia(r, glosa, sinon):
    """Parecido de cada glosa (con codigo) a la oficial de su cuenta (la mejor entre sinonimos)."""
    s = r[r["codigo"].notna() & r["glosa"].notna()][["rut", "anio", "codigo", "glosa"]].copy()
    cache = {}

    def sim(c, g):
        k = (c, g)
        if k not in cache:
            cache[k] = max((parecido(g, glosa[x]) for x in sinon.get(c, [c]) if x in glosa), default=None)
        return cache[k]
    s["parecido"] = [sim(c, g) for c, g in zip(s["codigo"], s["glosa"])]
    return s.dropna(subset=["parecido"])


def main():
    glosa, signo, sinon = oficial()
    r = leer()
    ruta = P / "ecp_bloques.csv"
    h = hallazgos(r, signo, pd.read_csv(ruta, dtype={"rut": str}) if ruta.exists() else None, glosa, sinon)
    h.to_csv(P / "formato.csv", index=False, encoding="utf-8-sig")

    enc = pd.read_csv(P / "encabezados.csv", dtype={"rut": str, "rut_agf": str})
    enc = enc[enc["es_ultimo_envio"]]
    # la AGF por su RUT: el nombre cambia entre anios ("ADM GRAL DE FONDOS ..." / "ADMINISTRADORA GENERAL ...");
    # se informa con el nombre de su envio mas reciente
    # (config.nombres_agf: el ultimo nombre valido; "CARTERA ADMINISTRADA" en algunos XML no es un nombre)
    if "rut_agf" in enc:
        enc = enc.assign(nombre_agf=enc["rut_agf"].astype(str).map(nombres_agf()).fillna(enc["nombre_agf"]))
    enc = enc[["rut", "anio", "nombre_agf"]].drop_duplicates(["rut", "anio"])
    fa = r[["rut", "anio"]].drop_duplicates()
    ad = adherencia(r, glosa, sinon)
    fondo = (fa.merge(ad.groupby(["rut", "anio"]).agg(lineas=("parecido", "size"), adherencia=("parecido", "mean"))
                      .reset_index(), how="left")
             .merge(h[~h["ocr"].fillna(False).astype(bool)].pivot_table(index=["rut", "anio"], columns="tipo",
                                                                        values="detalle", aggfunc="size")
                    .reset_index(), how="left")
             .merge(enc, how="left"))
    for t in TIPOS:
        fondo[t] = fondo[t].fillna(0).astype(int) if t in fondo else 0
    _, conv = convencion_signo(r, signo)
    conv = conv.pivot(index=["rut", "anio"], columns="estado", values="convencion").add_prefix("signo_").reset_index()
    fondo = fondo.merge(conv, how="left")
    fondo.to_csv(P / "formato_fondo.csv", index=False, encoding="utf-8-sig")

    agf = fondo.groupby(["nombre_agf", "anio"]).agg(
        fondos=("rut", "size"), adherencia=("adherencia", "mean"),
        **{f"{e}_sin_signo": (f"signo_{e}", lambda x: (x == "sin_signo").mean()) for e in ("ERI", "EFE") if f"signo_{e}" in fondo},
        **{t: (t, lambda x: (x > 0).mean()) for t in TIPOS}).reset_index()
    agf.to_csv(P / "formato_agf.csv", index=False, encoding="utf-8-sig")

    # --- Consola ---
    pd.set_option("display.width", 220)
    print(f"fondo-anio con renglones: {len(fa)}")
    hs = h[~h["ocr"].fillna(False).astype(bool)]
    print(f"\nhallazgos de formato (sin paginas OCR; con OCR: {int(h['ocr'].fillna(False).astype(bool).sum())}):")
    res = hs.groupby("tipo").agg(hallazgos=("detalle", "size"))
    res["fondo_anio"] = hs.drop_duplicates(["rut", "anio", "tipo"]).groupby("tipo").size()
    res["pct_fondo_anio"] = (res["fondo_anio"] / len(fa) * 100).round(2)
    print(res.reindex([t for t in TIPOS if t in res.index]).to_string())
    print("\n% de fondo-anio con cada tipo, por anio:")
    print((fondo.groupby("anio")[TIPOS].agg(lambda x: (x > 0).mean()) * 100).round(1).to_string())
    print("\nconvencion de signo de las cuentas (-) del modelo (% de fondo-anio):")
    for e in ("ERI", "EFE"):
        if f"signo_{e}" in fondo:
            print(f"  {e}: " + ", ".join(f"{k} {v:.1%}" for k, v in fondo[f"signo_{e}"].value_counts(normalize=True).items()))
    print("\nadherencia de la redaccion al modelo CMF (parecido medio 0-1), por anio:")
    print(fondo.groupby("anio")["adherencia"].describe()[["count", "mean", "25%", "50%", "75%"]].round(3).to_string())
    print("\npor AGF (20+ fondo-anio): % de fondo-anio con cada tipo y adherencia (las 12 con mas hallazgos):")
    clave = ["signo_mixto", "rotulo_otra_cuenta", "intercambio", "monto_cruzado", "monto_desalineado", "parentesis",
             "titulo_otro_estado",
             "glosa_desactualizada"]
    a = fondo.groupby("nombre_agf").agg(fondo_anio=("rut", "size"), adherencia=("adherencia", "mean"),
                                         **{t: (t, lambda x: (x > 0).mean() * 100) for t in clave})
    a = a[a["fondo_anio"] >= 20]
    a["total"] = a[clave].sum(axis=1)
    print(a.sort_values("total", ascending=False).head(12).round(2).to_string())
    print(f"  ({len(a)} AGF; mediana del total {a['total'].median():.1f}, maximo {a['total'].max():.1f})")
    # que cuenta concentra el hallazgo en cada AGF: si es siempre la misma, es una convencion de la AGF
    hx = hs.merge(enc, on=["rut", "anio"], how="left")
    top = a.sort_values("total", ascending=False).head(6).index
    for t, col in (("signo_mixto", "codigo"), ("monto_cruzado", "detalle")):
        print(f"\n{t}: cuenta mas frecuente en las AGF con mas hallazgos (fondo-anio)")
        for n in top:
            x = hx[(hx["tipo"] == t) & (hx["nombre_agf"] == n)].drop_duplicates(["rut", "anio", col])
            if len(x):
                v = x[col].astype(str).str.replace("glosa ", "").value_counts()
                print(f"  {n[:40]:<40} {v.index[0][:160]} ({v.iloc[0]} de {x[['rut', 'anio']].drop_duplicates().shape[0]})")
    print("\nejemplos por tipo:")
    for t in TIPOS:
        x = hs[hs["tipo"] == t].head(3)
        for e in x.itertuples():
            print(f"  {t:<20} {e.rut} {e.anio} {e.estado} p{e.pagina} {e.codigo or ''} {e.columna}: {e.detalle}")
    print(f"\nsalida: {P / 'formato.csv'}, formato_fondo.csv, formato_agf.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
