"""
04c - Conteo unico de casos: cada error (o inconsistencia de presentacion) cuenta una vez,
aunque lo marquen varias etapas y varias lineas. Diseno: verificacion/diseno_casos_unicos.md.

Unidad: la CELDA donde esta impresa la cifra: rut, anio_doc (anio del documento), documento
(PDF / XML), columna (actual / anterior). La columna "anterior" del PDF de t+1 y el comparativo
que mira el 03e para t son la misma celda.

Senales (esquema comun: fuente, rut, anio_doc, documento, columna, estado, linea, dif, clase):
  03b   estructura_efe_no_suma.csv   subtotal que no suma sus lineas (PDF)
  03b   estructura_efe.csv           subtotal que suma pero difiere del XML: documento sin resolver
  03c   identidades_no_cuadra.csv    identidad rota; el termino distinto del XML es la linea
  03d   ecp_no_cuadra.csv            celdas del ECP; rotulo incorrecto = un caso por fondo-anio
  03d   ecp_bloques.csv              glosa con el anio desactualizado (presentacion)
  04b   casos_senales.csv            las 12 lineas con sus cuatro versiones (patron -> celda)
  07    identidades_xml.csv          identidad rota dentro del XML (falla_grande)
  03f   documento_periodo.csv        el XML (o el PDF) no es el documento de ese fondo-anio: un caso
                                     por fondo-anio que absorbe las senales que comparan PDF con XML
Clase: error / presentacion forman casos; lectura, inmaterial y revisar quedan como contexto.

Caso: senales del mismo rut, anio_doc, documento y columna con la misma |dif| (+-2). Senales sin
documento resuelto (03b distinto del XML) se pegan a un caso de la misma celda y |dif|; si no
hay, quedan como caso "revisar" fuera del conteo de errores.

Contexto (no forma casos; se reporta): candidatos del 04 (fondo-anio) y comparativos del XML
modificados del 07 sin pareja en el 04b.

Lee:      las salidas de 03b, 03c, 03d, 03f, 04, 04b y 07 en data/procesado
Escribe:  data/procesado/casos_unicos.csv, casos_unicos_senales.csv
"""
import sys

import pandas as pd

from config import CMF_HOME, casos_conocidos, umbral_materialidad

P = CMF_HOME / "procesado"
TOL = 2
ESTADO = {"total_activo": "ESF", "total_pasivo": "ESF", "activo_neto": "ESF", "efectivo": "ESF",
          "total_ingresos": "ERI", "total_gastos": "ERI", "utilidad_operacion": "ERI",
          "resultado_eri": "ERI", "resultado_eri_despues": "ERI",
          "operacion": "EFE", "financiamiento": "EFE", "saldo_final": "EFE",
          "aumento_neto": "EFE", "evolucion_efectivo": "EFE"}       # identidades del EFE (03b)
TOTAL = {"activo_neto", "resultado_eri", "resultado_eri_despues", "saldo_final", "total_activo", "total_pasivo",
         "evolucion_efectivo"}
NIVEL = {"documento": -1, "linea": 0, "subtotal": 1, "total": 2, "identidad": 3}
# 03f: tipo -> (documento, clase). Revision: los 6 confirmados a mano (fechas del XML, encabezado del PDF).
DOCUMENTO = {"xml_periodo_desfasado": ("XML", "error"), "xml_no_corresponde": ("XML", "error"),
             "pdf_no_corresponde": ("PDF", "error")}
COLS = ["fuente", "rut", "anio_doc", "documento", "columna", "estado", "linea", "nivel", "dif", "clase",
        "forma", "detalle", "pagina"]


def estado_identidad(nombre):
    """Estado de una identidad del 07 por su nombre ("ECP inicio total...", "total activo - ...")."""
    n = str(nombre).lower()
    for e, rx in (("ECP", r"^ecp|serie"), ("EFE", r"^efe|flujo|saldo final|efectivo"),
                  ("ERI", r"^eri|ingreso|gasto|utilidad|resultado"), ("ESF", r"^esf|activo|pasivo")):
        if pd.notna(nombre) and __import__("re").search(rx, n):
            return e
    return "?"


def dif_xml(texto, defecto):
    """'inicio=16052 | cierre_ant=12605' -> |16052| - |12605|; si no hay dos terminos, defecto."""
    vals = []
    for t in str(texto).split("|"):
        if "=" in t:
            try:
                vals.append(float(t.rsplit("=", 1)[1]))
            except ValueError:
                pass
    return abs(vals[0]) - abs(vals[1]) if len(vals) == 2 else defecto


def nivel(linea):
    if linea in TOTAL:
        return "total"
    if linea in ESTADO:
        return "subtotal"
    return "linea"


def clase_de(c):
    c = str(c)
    if c.startswith("probable_error_rotulo"):
        return "presentacion"
    if c.startswith("probable_error"):
        return "error"
    if "inmaterial" in c:
        return "inmaterial"
    if "lectura" in c:
        return "lectura"
    return "revisar"


def doc_de(c):
    c = str(c)
    return "XML" if c.endswith("_xml") else "PDF+XML" if c.endswith("_ambos") else "PDF"


def senales_04():
    """04 cruce espejo, al detalle: en cada candidato material, cada cifra del XML no encontrada en
    el PDF con un monto huerfano del PDF a <= 1% (y >= 1.000, las reglas de par del 04) es una
    senal PDF/XML: se sabe que difieren, no cual esta mal. Redistribucion entre series: un caso
    por fondo-anio (la diferencia neta es cero)."""
    import importlib
    m04 = importlib.import_module("consolidacion.04_candidatos")
    from comun.secciones import SECCION_DE   # el estado_financiero del 04 es por palabras clave: 13 codigos mal (p.ej. OtrosIngresosDeOperacion -> ERI)
    can = pd.read_csv(P / "candidatos.csv", dtype={"rut": str})
    can = can[can["revision"] != "observacion_inmaterial"][["rut", "anio", "tipo", "subtipo_probable",
                                                             "delta_principal", "moneda"]]
    det = pd.read_csv(P / "cruce_detalle.csv", dtype={"rut": str, "serie": str})
    f = det[det["estado"] == "no_encontrado"].merge(can, on=["rut", "anio"])
    hue = pd.read_csv(P / "cruce_huerfanos.csv", dtype={"rut": str})
    H = {k: sorted(set(g["monto_pdf"].abs())) for k, g in hue.groupby(["rut", "anio"])}
    filas = []
    for r in f.itertuples():
        v, hs = abs(r.valor_xml), H.get((r.rut, r.anio), [])
        if not hs or pd.isna(v) or v < m04.MIN_MONTO_PAR:
            continue
        h = min(hs, key=lambda x: abs(x - v))
        if abs(h - v) > m04.MAX_DIF_RELATIVA_PAR * v:
            continue
        # Solo el par que explica la discrepancia que el 04 ya eligio (delta_principal): los demas
        # pares a <= 1% son coincidencias de montos parecidos (1a corrida: 821 senales, 363 casos solo 04)
        redis = r.tipo == "redistribucion"
        if not redis and abs(abs(h - v) - abs(r.delta_principal)) > TOL:
            continue
        sub = str(r.subtipo_probable)
        clase = ("inmaterial" if abs(h - v) <= umbral_materialidad(r.moneda) or sub == "dif_menor" else
                 "presentacion" if sub in ("agregacion_xml", "rotulo_incorrecto") else "error")
        linea = r.codigo + (f"/{r.serie}" if pd.notna(r.serie) else "")
        filas.append(dict(fuente="04", rut=r.rut, anio_doc=r.anio, documento="PDF/XML",
                          columna={"PeriodoActual": "actual", "PeriodoAnterior": "anterior"}.get(r.contexto, "actual"),
                          estado=SECCION_DE.get(r.codigo) or m04.estado_financiero(r.codigo), linea=linea, nivel="linea", dif=h - v,
                          clase=clase, forma=f"espejo/{r.tipo}/{sub}", detalle=f"xml={r.valor_xml} pdf~{h}",
                          pagina=str(r.paginas).split(",")[0] if pd.notna(r.paginas) else pd.NA))
    out = pd.DataFrame(filas, columns=COLS)
    subtotales = importlib.import_module("validaciones.estructura.03b_estructura").SUBTOTALES
    cods = {c for cfg in subtotales.values() for c in [cfg["codigo"], *cfg["partes"]]}
    cods |= {c + x for c in ECP_COD.values() for x in ("", "PorSerie")}
    arch, v = xml_valores(out, cods)
    return ecp_documento(compensa_subtotal(out, subtotales, arch, v), arch, v)


# Codigos del ECP (total; por serie con sufijo PorSerie)
ECP_COD = dict(
    inicio="ActivoNetoAtribuibleALosParticipesAl01DeEnero", aportes="AportesDeCuotas",
    rescates="RescateDeCuotas", neto="AumentoNetoOriginadoPorTransaccionesDeCuotas",
    despues="AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacion"
            "DespuesDeDistribucionDeBeneficios",
    cierre="ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuota")


def xml_valores(s, cods):
    """XML completo (ultimo envio, como el 03b) de los fondo-anio de s, desde cuentas.csv: el
    cruce_detalle no trae subtotales ni todas las partes. (archivo, columna, codigo, serie|'') -> valor."""
    enc = pd.read_csv(P / "encabezados.csv", dtype={"rut": str})
    enc = enc[enc["es_ultimo_envio"]]
    enc = enc[enc.set_index(["rut", "anio"]).index.isin(list(zip(s["rut"], s["anio_doc"])))]
    arch = dict(zip(zip(enc["rut"], enc["anio"]), enc["archivo"]))
    cta = pd.read_csv(P / "cuentas.csv", usecols=["archivo", "contexto", "codigo", "serie", "valor"],
                      dtype={"serie": str})
    cta = cta[cta["codigo"].isin(cods) & cta["archivo"].isin(set(arch.values()))]
    col = cta["contexto"].map({"PeriodoActual": "actual", "PeriodoAnterior": "anterior"})
    v = dict(zip(zip(cta["archivo"], col, cta["codigo"], cta["serie"].fillna("")), cta["valor"].fillna(0)))
    return arch, v


def nums(texto):
    """'aportes=14457 | rescates=-4857 | neto=9600' -> {'aportes': 14457.0, ...}"""
    out = {}
    for t in str(texto).split("|"):
        if "=" in t:
            k, x = t.rsplit("=", 1)
            try:
                out[k.strip()] = float(x)
            except ValueError:
                pass
    return out


def ecp_documento(s, arch, v):
    """Revision 04c (solo 04, 2a muestra): 9 de 10 eran ECP por serie con PDF != XML, sin saber cual
    esta mal. Se resuelve con las identidades de cada documento en esa serie y columna:
      transacciones: aportes + rescates = neto     evolucion: inicio + neto + resultado despues = cierre
    XML: desde cuentas.csv. PDF: la columna del 03d (ecp_chequeos) cuyo detalle contiene el monto
    huerfano del PDF (el 03d nombra las columnas serie_1, serie_2..., no por la serie del XML).
      XML no cuadra, PDF si -> error XML       XML cuadra, PDF no -> error PDF
      ambos cuadran y el neto del PDF = el del XML -> desglose (aportes/rescates compensados)
      resto -> sigue PDF/XML"""
    ch = pd.read_csv(P / "ecp_chequeos.csv", dtype={"rut": str})
    cont = ch[ch["chequeo"] == "continuidad"]
    cont_de = {k: g for k, g in cont.groupby(["rut", "anio", "columna"])}
    ch = ch[ch["chequeo"].isin(["transacciones", "evolucion"])]
    ch_de = {k: g for k, g in ch.groupby(["rut", "anio", "columna"])}

    def xml_cuadra(a, c, serie):
        x = {k: v.get((a, c, cod + ("PorSerie" if serie else ""), serie)) for k, cod in ECP_COD.items()}
        if any(x[k] is None for k in ("aportes", "rescates", "neto")):
            return None, None, None, None
        ok = abs(abs(x["aportes"]) - abs(x["rescates"]) - x["neto"]) <= TOL   # rescates con o sin signo
        if all(x[k] is not None for k in ("inicio", "despues", "cierre")):
            ok = ok and abs(x["inicio"] + x["neto"] + x["despues"] - x["cierre"]) <= TOL
        return ok, x["neto"], x["cierre"], x["inicio"]

    def pdf_cuadra(rut, anio, c, h):
        g = ch_de.get((rut, anio, c))
        if g is None:
            return None, None, None, None, None
        cols = [k for k, gg in g.groupby("col") if any(abs(abs(n) - h) <= TOL
                for t in gg["pdf"] for n in nums(t).values())]
        if len(cols) != 1:
            return None, None, None, None, None
        gg = g[g["col"] == cols[0]]
        uno = lambda chq, k: next((nums(t).get(k) for t in gg.loc[gg["chequeo"] == chq, "pdf"]), None)
        cg = cont_de.get((rut, anio, c))
        cont_ok = None
        # Continuidad de la serie si el 03d la tiene; si no, la del total (revision: el 03d solo la
        # mide en el total, la marco probable_lectura, pero el inicio del PDF no es el cierre anterior
        # y el XML si: todas las series del PDF arrastran el error)
        for cc in (cols[0], "total"):
            if cg is not None and (cg["col"] == cc).any():
                cont_ok = bool(cg.loc[cg["col"] == cc, "cuadra"].astype(bool).all())
                break
        # Si lo unico que no cuadra es un rotulo (la fila "transacciones" trae el inicio sumado;
        # 3a muestra) el PDF no tiene una cifra mala: es la plantilla -> "rotulo"
        malas = gg.loc[~gg["cuadra"].astype(bool), "clase"].astype(str)
        if len(malas) and malas.str.startswith("probable_error_rotulo").all():
            return "rotulo", None, None, None, cont_ok
        return (bool(gg["cuadra"].astype(bool).all()), uno("transacciones", "neto"),
                uno("evolucion", "cierre"), uno("evolucion", "inicio"), cont_ok)

    m = (s["fuente"] == "04") & (s["clase"] == "error") & (s["estado"] == "ECP")
    res = {}
    for i in s.index[m]:
        r = s.loc[i]
        serie = r["linea"].split("/", 1)[1] if "/" in r["linea"] else ""
        h = nums(str(r["detalle"]).replace("~", "=").replace(" ", " | ")).get("pdf")
        a = arch.get((r["rut"], r["anio_doc"]))
        xo, xn, xc, xi = xml_cuadra(a, r["columna"], serie) if a else (None, None, None, None)
        po, pn, pc, pi, pcont = (pdf_cuadra(r["rut"], r["anio_doc"], r["columna"], abs(h)) if h is not None
                                 else (None, None, None, None, None))
        igual = lambda p, x: p is not None and x is not None and abs(abs(p) - abs(x)) <= TOL
        if po == "rotulo":
            res[i] = ("PDF", "presentacion", "rotulo/ecp")
        elif xo is False and po is not False:
            res[i] = ("XML", "error", "ecp_xml_no_cuadra")
        elif xo and po is False:
            res[i] = ("PDF", "error", "ecp_pdf_no_cuadra")
        elif xo and po and (igual(pn, xn) or (igual(pc, xc) and (pi is None or xi is None or igual(pi, xi)))):
            # 2a muestra: aportes/rescates o neto/resultado compensados: cierre igual.
            # Si el cierre es igual pero el inicio no, la diferencia se compenso contra el inicio:
            # eso es continuidad rota, no desglose -> rama siguiente
            res[i] = ("PDF/XML", "presentacion", "desglose/ecp")
        elif xo and po and pcont is False:
            # cada uno cuadra en el anio, pero el inicio del PDF no es el cierre anterior
            res[i] = ("PDF", "error", "ecp_pdf_continuidad")
        else:
            res[i] = ("PDF/XML", "error", "ecp_" + {None: "sin_lectura", True: "ambos_cuadran", False: "ninguno"}[po])
    for i, (doc, clase, forma) in res.items():
        s.at[i, "documento"], s.at[i, "clase"] = doc, clase
        s.at[i, "forma"] = "espejo/" + forma
    print("04 ECP: documento por las identidades de cada uno ->",
          pd.Series([f for _, _, f in res.values()]).value_counts().to_dict())
    return s


def compensa_subtotal(s, subtotales, arch, v):
    """Revision 04c (solo 04, 10 casos): 1 error confirmado; la mayoria eran el PDF y el XML
    desglosando distinto las mismas lineas (montos recibidos metidos en venta/cobro, dif. de cambio
    junto al valor razonable, compra e intereses compensados) con el subtotal igual. Si la linea es
    parte de un subtotal que en el PDF suma, es igual al XML y en el XML suma sus partes, la
    diferencia se compensa dentro del subtotal: presentacion (desglose), no error."""
    sub_de = {c: n for n, cfg in subtotales.items() for c in cfg["partes"]}
    e = pd.read_csv(P / "estructura_efe.csv", dtype={"rut": str})
    e = e[(e["ubicado"] == True) & (e["pdf_suma"] == True) & (e["igual_xml"] == True)]
    ok_pdf = set(zip(e["rut"], e["anio"], e["subtotal"], e["columna"]))
    def xml_suma(rut, anio, n, c):
        cfg, a = subtotales[n], arch.get((rut, anio))
        tot = v.get((a, c, cfg["codigo"], ""))
        if tot is None:
            return False
        suma = sum(v.get((a, c, k, ""), 0) for k in cfg["partes"])
        return abs(abs(suma) - abs(tot)) <= TOL      # signo: mismo criterio que el igual_xml del 03b
    base = s["linea"].str.split("/").str[0]
    n = base.map(sub_de)
    pdf_ok = pd.Series([pd.notna(ni) and f == "error" and (r, a, ni, c) in ok_pdf
                        for r, a, ni, c, f in zip(s["rut"], s["anio_doc"], n, s["columna"], s["clase"])], index=s.index)
    comp = pdf_ok & pd.Series([ok and xml_suma(r, a, ni, c) for ok, r, a, ni, c
                               in zip(pdf_ok, s["rut"], s["anio_doc"], n, s["columna"])], index=s.index)
    print(f"04: {int(pdf_ok.sum())} senales de error en un subtotal que cuadra en el PDF e igual al XML; "
          f"{int((pdf_ok & ~comp).sum())} quedan como error porque el XML no suma sus partes")
    s.loc[comp, "clase"] = "presentacion"
    s.loc[comp, "forma"] = "espejo/desglose/" + n[comp] + "/" + s.loc[comp, "forma"].str.split("/").str[-1]
    print(f"04: {int(comp.sum())} senales de error se compensan dentro de un subtotal que cuadra en ambos -> desglose")
    return s


def senales():
    s = []
    # 03b: subtotal que no suma (PDF)
    b = pd.read_csv(P / "estructura_efe_no_suma.csv", dtype={"rut": str})
    pag = pd.read_csv(P / "estructura_efe.csv", dtype={"rut": str}, usecols=["rut", "anio", "subtotal", "columna", "pagina"])
    b = b.merge(pag.drop_duplicates(["rut", "anio", "subtotal", "columna"]), how="left")
    # Revision 04c: 2 de 4 casos que solo veia el 03b tenian el subtotal igual en PDF y XML (una
    # linea mal leida por nosotros). Sin otra fuente que lo confirme, eso queda en "revisar";
    # linea_distinta / no_sumada / tipeo son errores de una linea con el total correcto: siguen.
    linea = b["clase"].astype(str).str.contains("linea_distinta|linea_no_sumada|tipeo")
    clase_03b = b["clase"].map(clase_de)
    clase_03b = clase_03b.where(~((clase_03b == "error") & (b["igual_xml"] == True) & ~linea), "revisar")
    s.append(pd.DataFrame({"fuente": "03b", "rut": b["rut"], "anio_doc": b["anio"], "documento": "PDF",
                           "columna": b["columna"], "estado": b["subtotal"].map(ESTADO), "linea": b["subtotal"],
                           "nivel": "subtotal", "dif": b["dif"], "clase": clase_03b,
                           "forma": b["clase"], "detalle": b["patron"].astype(str), "pagina": b["pagina"]}))
    # 03b: suma bien pero difiere del XML -> documento sin resolver
    e = pd.read_csv(P / "estructura_efe.csv", dtype={"rut": str})
    e = e[(e["ubicado"] == True) & (e["pdf_suma"] == True) & (e["igual_xml"] == False)
          & ~e["pagina_ocr"].fillna(False).astype(bool)]
    s.append(pd.DataFrame({"fuente": "03b_xml", "rut": e["rut"], "anio_doc": e["anio"], "documento": "?",
                           "columna": e["columna"], "estado": e["subtotal"].map(ESTADO), "linea": e["subtotal"],
                           "nivel": "subtotal", "dif": e["subtotal_pdf"].abs() - e["subtotal_xml"].abs(),
                           "clase": "revisar", "forma": "distinto_xml", "detalle": "", "pagina": e["pagina"]}))
    # 03c: identidad rota; la linea es el termino distinto
    c = pd.read_csv(P / "identidades_no_cuadra.csv", dtype={"rut": str})
    lin = c["terminos_distintos_xml"].fillna("").str.split(",").str[0].replace("", "identidad")
    s.append(pd.DataFrame({"fuente": "03c", "rut": c["rut"], "anio_doc": c["anio"],
                           "documento": c["clase"].map(doc_de), "columna": c["columna"],
                           "estado": lin.map(ESTADO).fillna(c["identidad"].map(
                               {"activo_menos_pasivo": "ESF", "ingresos_menos_gastos": "ERI",
                                "efectivo_esf_efe": "ESF"})),
                           "linea": lin, "nivel": lin.map(lambda x: "identidad" if x == "identidad" else nivel(x)),
                           "dif": c["dif_pdf"].where(~c["clase"].str.endswith("_xml"), c["dif_xml"]),
                           "clase": c["clase"].map(clase_de), "forma": c["clase"], "detalle": c["identidad"],
                           "pagina": c["paginas"].astype(str).str.split(",").str[0]}))
    # 03d: celdas del ECP
    d = pd.read_csv(P / "ecp_no_cuadra.csv", dtype={"rut": str})
    # Cruces con otro estado: si el lado distinto del XML es el otro estado, la celda es la de ese
    # estado (resultado del ERI, activo neto del ESF), no la del ECP
    fuera = {"resultado_eri": ("ERI", "resultado_eri"), "activo_neto_esf": ("ESF", "activo_neto")}
    lado = d["distintos"].map(lambda v: fuera.get(str(v)))
    est_d = [l[0] if isinstance(l, tuple) else "ECP" for l in lado]
    lin_d = [l[1] if isinstance(l, tuple) else f"{ch}/{co}" for l, ch, co in zip(lado, d["chequeo"], d["col"])]
    s.append(pd.DataFrame({"fuente": "03d", "rut": d["rut"], "anio_doc": d["anio"],
                           "documento": d["clase"].map(doc_de),
                           # continuidad (inicio actual vs cierre anterior): el lado que suele fallar es el
                           # comparativo, como en el 07 -> se junta con las omisiones del comparativo
                           "columna": d["columna"].where(d["chequeo"] != "continuidad", "anterior"),
                           "estado": est_d,
                           "linea": lin_d, "nivel": [nivel(x) if x in ESTADO else "linea" for x in lin_d],
                           "dif": [dif_xml(x, v) if str(c).endswith("_xml") else v
                                   for x, v, c in zip(d["xml"], d["dif"], d["clase"])],
                           "clase": d["clase"].map(clase_de), "forma": d["clase"],
                           "detalle": d["distintos"].astype(str), "pagina": d["pagina"]}))
    # 03d: glosa desactualizada (sin el comparativo con desfase 0: lectura, H-ECP3)
    g = pd.read_csv(P / "ecp_bloques.csv", dtype={"rut": str})
    g = g[g["anio_texto"].notna()]
    desf = g["anio"] - g["anio_texto"] - (g["columna"] == "anterior").astype(int)
    g = g[(desf > 0) | ((g["columna"] == "actual") & (desf >= 1))]
    s.append(pd.DataFrame({"fuente": "03d_glosa", "rut": g["rut"], "anio_doc": g["anio"], "documento": "PDF",
                           "columna": g["columna"], "estado": "ECP", "linea": "glosa_anio", "nivel": "linea",
                           "dif": 0.0, "clase": "presentacion", "forma": "glosa_desactualizada",
                           "detalle": "anio_texto=" + g["anio_texto"].astype(int).astype(str),
                           "pagina": g["pagina"]}))
    # 04b: patron -> celda
    x = pd.read_csv(P / "casos_senales.csv", dtype={"rut": str})
    cas = pd.read_csv(P / "casos.csv", dtype={"rut": str})[["caso_id", "tipo", "subtipo"]]
    x = x.drop(columns=[k for k in ("tipo", "subtipo") if k in x]).merge(cas, on="caso_id", how="left")
    celda = {"solo_pdf_t": ("PDF", 0, "actual"), "solo_pdf_t1": ("PDF", 1, "anterior"),
             "solo_xml_t": ("XML", 0, "actual"), "solo_xml_t1": ("XML", 1, "anterior"),
             "reexpresion": ("PDF+XML", 1, "anterior"), "criterio": ("PDFvsXML", 0, "actual"),
             "otro": ("?", 0, "actual")}
    m = x["patron"].map(celda)
    def clase_04b(r):
        if r.motivo_no_caso == "lectura":
            return "lectura"
        if r.motivo_no_caso == "inmaterial":
            return "inmaterial"
        if r.tipo in ("reexpresion", "criterio") or str(r.subtipo).startswith("reclasificacion"):
            return "presentacion"
        if r.tipo == "otro" or r.subtipo == "sin_ancla":
            return "revisar"
        return "error"
    s.append(pd.DataFrame({"fuente": "04b", "rut": x["rut"], "anio_doc": x["anio_t"] + m.str[1],
                           "documento": m.str[0], "columna": m.str[2], "estado": x["estado"], "linea": x["linea"],
                           "nivel": x["linea"].map(nivel), "dif": x["dif_patron"],
                           "clase": [clase_04b(r) for r in x.itertuples()],
                           "forma": x["tipo"].fillna("") + "/" + x["subtipo"].fillna(""),
                           "detalle": x["patron"],
                           "pagina": x["pagina_t1"].where(m.str[1] == 1, x["pagina_t"]),
                           "grupo": ("04b:" + x["caso_id"].astype("Int64").astype(str)).where(x["caso_id"].notna())}))
    # 07: identidad rota dentro del XML
    ruta = P / "identidades_xml.csv"
    if ruta.exists():
        ix = pd.read_csv(ruta, dtype={"rut": str})
        ix = ix[ix["falla_grande"] == True]
        s.append(pd.DataFrame({"fuente": "07", "rut": ix["rut"], "anio_doc": ix["anio"], "documento": "XML",
                               # identidades entre columnas ("inicio (act) = cierre (ant)"): el lado
                               # que suele fallar es el comparativo (H5), y asi se junta con el 04b
                               "columna": ix["contexto"].map({"PeriodoActual": "actual",
                                                             "PeriodoAnterior": "anterior"}).fillna("actual")
                                          .where(~ix["identidad"].str.contains(r"\(act\).*\(ant\)"), "anterior"),
                               "estado": ix["identidad"].map(estado_identidad),
                               "linea": ix["identidad"], "nivel": "identidad", "dif": ix["dif"],
                               "clase": ix["identidad"].map(lambda n: "revisar" if "por serie" in str(n) else "error"),
                               "forma": "identidad_xml", "detalle": "", "pagina": pd.NA}))
    # 03f: documento que no corresponde al fondo-anio
    ruta = P / "documento_periodo.csv"
    if ruta.exists():
        dp = pd.read_csv(ruta, dtype={"rut": str})
        dp = dp[dp["tipo"].isin(DOCUMENTO)]
        s.append(pd.DataFrame({"fuente": "03f", "rut": dp["rut"], "anio_doc": dp["anio"],
                               "documento": dp["tipo"].map(lambda x: DOCUMENTO[x][0]), "columna": "actual",
                               "estado": "todos", "linea": dp["tipo"], "nivel": "documento", "dif": 0.0,
                               "clase": dp["tipo"].map(lambda x: DOCUMENTO[x][1]), "forma": "documento/" + dp["tipo"],
                               "detalle": [f"pdf_actual_en_xml={a:.2f} xml_repite_t-1={b if pd.isna(b) else round(b, 2)}"
                                           for a, b in zip(dp["normal"], dp["xml_repite"])],
                               "pagina": pd.NA}))
    s.append(senales_04())
    t = pd.concat(s, ignore_index=True)
    t = t.reindex(columns=COLS + ["grupo"])
    t["anio_doc"] = t["anio_doc"].astype(int)
    t["adif"] = t["dif"].abs().fillna(0)
    return t


def agrupar(t):
    """caso_id a las senales error/presentacion; las de documento '?' se pegan despues."""
    forma_caso = t["clase"].isin(["error", "presentacion"]) & ~t["documento"].isin(["?", "PDF/XML"])
    t["caso_id"] = pd.NA
    t["clave"] = t["rut"] + "|" + t["anio_doc"].astype(str) + "|" + t["documento"] + "|" + t["columna"]
    # rotulo y glosa: un caso por fondo-anio (es la plantilla)
    plantilla = t["forma"].astype(str).str.contains("rotulo|glosa_desactualizada")
    t.loc[plantilla, "clave"] = (t["rut"] + "|" + t["anio_doc"].astype(str) + "|"
                                 + t["forma"].astype(str).str.contains("rotulo").map({True: "rotulo", False: "glosa"}))
    # el rotulo que ve el 04 (subtipo rotulo_incorrecto) va al caso de rotulo del 03d del mismo fondo-anio
    forma_caso = forma_caso | (plantilla & (t["fuente"] == "04"))
    # 03f: si el XML (o el PDF) no es el documento del fondo-anio, toda senal que compara el PDF
    # con el XML en ese fondo-anio es sintoma del mismo problema: un caso. Se quedan fuera las del
    # PDF consigo mismo (documento PDF: subtotal que no suma, rotulo, glosa) salvo las del 03c,
    # que clasifican con el XML. Sin esto un XML con las cifras del anio anterior sumaba 3 casos.
    doc = t[(t["fuente"] == "03f") & (t["clase"] == "error")]
    malo = set(zip(doc["rut"], doc["anio_doc"]))
    absorbe = (pd.Series([(r, a) in malo for r, a in zip(t["rut"], t["anio_doc"])], index=t.index)
               & t["clase"].isin(["error", "presentacion", "revisar"])
               & ((t["documento"] != "PDF") | (t["fuente"] == "03c")))
    t.loc[absorbe, "clave"] = t["rut"] + "|" + t["anio_doc"].astype(str) + "|documento"
    t.loc[absorbe, "grupo"] = pd.NA                     # no se une a casos del 04b de otro anio
    plantilla = plantilla | absorbe
    forma_caso = forma_caso | absorbe
    if absorbe.any():
        print(f"03f: {len(malo)} fondo-anio con un documento que no corresponde; "
              f"{int(absorbe.sum()) - len(doc)} senales absorbidas en su caso")
    n = 0
    for _, g in t[forma_caso].sort_values(["clave", "adif"]).groupby("clave", sort=False):
        prev = None
        for i, r in g.iterrows():
            if prev is None or (not plantilla[i] and r.adif - prev > TOL):
                n += 1
            t.at[i, "caso_id"] = n
            prev = r.adif
    # Lo que el 04b ya junto (misma dif en varias lineas, comparativo omitido en 0) sigue junto:
    # se unen los casos que comparten un caso del 04b
    padre = {}
    def raiz(a):
        while padre.get(a, a) != a:
            a = padre[a]
        return a
    for _, g in t[t["caso_id"].notna() & t["grupo"].notna()].groupby("grupo"):
        ids = sorted(set(g["caso_id"]))
        for o in ids[1:]:
            padre[raiz(o)] = raiz(ids[0])
    if padre:
        t["caso_id"] = t["caso_id"].map(lambda c: raiz(c) if pd.notna(c) else c)
    # 07 solo: los casos hechos solo de identidades del XML se juntan por celda (rut, anio, columna):
    # una cuenta mal en el XML rompe varias identidades, cada una con su dif
    solo07 = t[t["caso_id"].notna()].groupby("caso_id")["fuente"].agg(lambda f: set(f) == {"07"})
    ids07 = set(solo07[solo07].index)
    m07 = t["caso_id"].isin(ids07)
    if m07.any():
        prim = t[m07].groupby(["rut", "anio_doc", "columna"])["caso_id"].transform("min")
        t.loc[m07, "caso_id"] = prim
    # senales sin documento resuelto o "revisar": se pegan a un caso de la misma celda y |dif|
    casos = t[t["caso_id"].notna()]
    idx = {}
    for r in casos.itertuples():
        idx.setdefault((r.rut, r.anio_doc, r.columna), []).append((r.adif, r.caso_id))
    def pegar():
        for i, r in t[t["caso_id"].isna() & (t["documento"].isin(["?", "PDF/XML"]) | (t["clase"] == "revisar"))
                      ].iterrows():
            hit = next((cid for a, cid in idx.get((r.rut, r.anio_doc, r.columna), []) if abs(a - r.adif) <= TOL),
                       None)
            if hit is not None:
                t.at[i, "caso_id"] = hit
    pegar()
    # 04 sin pareja: casos propios PDF/XML (misma celda y |dif|; redistribucion = uno por fondo-anio)
    resto = t[t["caso_id"].isna() & (t["documento"] == "PDF/XML") & t["clase"].isin(["error", "presentacion"])].copy()
    redis = resto["forma"].str.contains("redistribucion")
    resto.loc[redis, "clave"] = resto["rut"] + "|" + resto["anio_doc"].astype(str) + "|redistribucion"
    n = int(pd.to_numeric(t["caso_id"]).max()) if t["caso_id"].notna().any() else 0
    for _, g in resto.sort_values(["clave", "adif"]).groupby("clave", sort=False):
        prev = None
        for i, r in g.iterrows():
            if prev is None or (not redis[i] and r.adif - prev > TOL):
                n += 1
                idx.setdefault((r.rut, r.anio_doc, r.columna), []).append((r.adif, n))
            t.at[i, "caso_id"] = n
            prev = r.adif
    pegar()            # los 03b distintos del XML sin pareja pueden caer en un caso del 04
    return t.drop(columns="clave")


def tipificar(t):
    out = []
    for cid, g in t[t["caso_id"].notna()].groupby("caso_id"):
        otras = (g["fuente"] != "04").any()
        e = g[(g["clase"] == "error") & ~((g["fuente"] == "04") & otras)]
        base = e if len(e) else g[g["clase"] == "presentacion"]
        if base.empty:
            base = g
        raiz = base.assign(_o=base["nivel"].map(NIVEL) + 10 * (base["fuente"] == "04")).sort_values("_o").iloc[0]
        d3f = g[(g["fuente"] == "03f") & (g["clase"] == "error")]
        if len(d3f):
            tipo = "error_" + d3f["documento"].iloc[0]    # el documento entero; la linea raiz dice cual
        elif len(e):
            docs = sorted(set(e["documento"]) - {"?"})
            if len(docs) > 1 and "PDF/XML" in docs:      # el 04 solo dice que difieren: manda el resto
                docs.remove("PDF/XML")
            tipo = "error_" + ("+".join(docs) if docs else "?")
            if set(g["fuente"]) == {"07"}:
                tipo = "error_continuidad"      # identidad del XML; el PDF sin contrastar (revision: 4/8 igual)
        else:
            f = str(raiz["forma"])
            tipo = ("desglose" if "desglose" in f else "rotulo" if "rotulo" in f else "glosa" if "glosa" in f else
                    "agregacion_xml" if "agregacion" in f else
                    "reexpresion" if "reexpresion" in f else "criterio" if "criterio" in f else "reclasificacion")
        out.append(dict(caso_id=cid, rut=raiz["rut"], anio_doc=raiz["anio_doc"], columna=raiz["columna"],
                        tipo=tipo, estado_raiz=raiz["estado"], linea_raiz=raiz["linea"], nivel=raiz["nivel"],
                        dif=g["adif"].max(), fuentes=",".join(sorted(set(g["fuente"]))),
                        n_senales=len(g), estados=",".join(sorted(set(g["estado"].dropna()))),
                        lineas=",".join(sorted(set(g["linea"])))[:200],
                        pagina=next((p for p in base.sort_values("nivel", key=lambda s: s.map(NIVEL))["pagina"]
                                     if pd.notna(p) and str(p) not in ("", "nan")), pd.NA)))
    return pd.DataFrame(out)


def main():
    t = agrupar(senales())
    c = tipificar(t)
    enc = pd.read_csv(P / "encabezados.csv", dtype={"rut": str})
    enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "nombre_agf"]].rename(columns={"anio": "anio_doc"})
    c = c.merge(enc, on=["rut", "anio_doc"], how="left")
    c.to_csv(P / "casos_unicos.csv", index=False, encoding="utf-8-sig")
    t.to_csv(P / "casos_unicos_senales.csv", index=False, encoding="utf-8-sig")

    print("senales por fuente y clase:")
    print(pd.crosstab(t["fuente"], t["clase"], margins=True).to_string())
    err = c[c["tipo"].str.startswith("error")]
    print(f"\ncasos unicos: {len(c)} en {c[['rut', 'anio_doc']].drop_duplicates().shape[0]} fondo-anio"
          f"  (errores: {len(err)} en {err[['rut', 'anio_doc']].drop_duplicates().shape[0]} fondo-anio)")
    print("\ntipo x numero de fuentes:")
    c["n_fuentes"] = c["fuentes"].str.count(",") + 1
    print(pd.crosstab(c["tipo"], c["n_fuentes"], margins=True).to_string())
    print("\nerrores: combinaciones de fuentes mas frecuentes:")
    print(err["fuentes"].value_counts().head(12).to_string())
    print("\nerrores por anio del documento x estado raiz:")
    print(pd.crosstab(err["anio_doc"], err["estado_raiz"], margins=True).to_string())
    sin = t[t["caso_id"].isna() & (t["documento"] == "?") & (t["clase"] == "revisar")]
    lect = t[t["clase"] == "lectura"]
    print(f"\nsin resolver (03b distinto del XML sin pareja): {len(sin)} senales en "
          f"{sin[['rut', 'anio_doc']].drop_duplicates().shape[0]} fondo-anio")
    print(f"cota superior: senales de lectura {len(lect)} en {lect[['rut', 'anio_doc']].drop_duplicates().shape[0]} "
          f"fondo-anio (si todas fueran error)")
    can = pd.read_csv(P / "candidatos.csv", dtype={"rut": str})
    can = can[can["revision"] != "observacion_inmaterial"]
    con = set(zip(c["rut"], c["anio_doc"]))
    solo04 = can[[(r, a) not in con for r, a in zip(can["rut"], can["anio"])]]
    print(f"contexto 04: {len(can)} candidatos materiales; {len(solo04)} sin ningun caso de otra etapa "
          f"(gravedad_auto: {(solo04['revision'] == 'gravedad_auto').sum()})")

    print("\nvalidacion con casos conocidos:")
    for rut, anio, esperado in casos_conocidos("04c"):
        x = c[(c["rut"] == rut) & (c["anio_doc"] == anio)]
        print(f"  {rut} {anio}: " + ("; ".join(f"{r.tipo} {r.estado_raiz}/{r.linea_raiz} [{r.fuentes}] "
                                             f"dif {r.dif:,.0f}" for r in x.itertuples()) or "sin caso"))
        print(f"      esperado: {esperado}")
    print(f"\nsalida: {P / 'casos_unicos.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())