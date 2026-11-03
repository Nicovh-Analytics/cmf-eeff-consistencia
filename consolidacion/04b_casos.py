"""
04b - Casos: agrupa las senales de un mismo error en un caso.

Paso 1 del esquema de revision: solo las 12 lineas del 03e, donde cada monto tiene 4 versiones
(PDF t, XML t, comparativo PDF t+1, comparativo XML t+1). El 03e deja en cada linea el patron
(cual version no calza) y su diferencia. Aqui:

  1. Senal = linea con patron distinto de cuadra/incompleto, material y no de lectura.
  2. Caso = senales del mismo fondo-anio y patron con la misma diferencia (|dif| +- TOL_CASO):
     un tipeo en el resultado del ERI aparece en utilidad, resultado antes y despues de
     distribucion, ingresos... y es UN error.
  3. Tipo del caso, de lo agregado a lo fino:
       error_total            la linea ancla del estado (activo neto, resultado del ERI,
                              saldo final de efectivo) esta en el caso
       error_suma             el subtotal del documento con la diferencia no suma sus lineas (03b)
       reclasificacion        2+ lineas del mismo estado se mueven el mismo monto y el ancla
                              calza (operacion <-> financiamiento, activo <-> pasivo...)
       reclasificacion_dc     EFE: una sola linea (operacion o financiamiento) cambia, el saldo
                              final calza y el subtotal suma: el monto fue a/desde "efecto de
                              diferencias de cambio", que no esta entre las 12 lineas
       error_linea            una linea cambia y el ancla calza (fuera del caso anterior)
       sin_ancla              el ancla no tiene sus 4 versiones o es dudosa: no se puede decidir
       omision                todas las lineas del caso vienen en 0 en el documento distinto
                              (comparativo omitido): un caso, aunque cada linea tenga otra dif
     Ese tipo por niveles queda como `subtipo`; `tipo` es la familia segun el patron:
       pdf (solo_pdf_t / solo_pdf_t1; el subtipo separa error de reclasificacion), error_xml (solo_xml_t / solo_xml_t1: los dos PDF
       coinciden; revision por lotes 10/10), reexpresion (los dos documentos de t+1 cambiaron
       la cifra de t: buscar nota), criterio (PDF y XML distintos igual en ambos anios), otro.

Tambien: cobertura por estado (el ancla tiene sus 4 versiones limpias?) y de que estan hechas
las senales de lectura (OCR, solo glosa, huella de digito/cero).

Lado XML y criterio: clase del 07 para el mismo par de anios (ya visto ahi?) y concentracion
por AGF (pocas AGF = un patron de plantilla, no N hallazgos).

Lee:      data/procesado/comparativos_pdf.csv (03e), estructura_efe.csv (03b, pdf_suma)
          continuidad_resumen.csv (07)
          verificacion/revision_03e.xlsx (si existe: veredictos contra tipos)
Escribe:  data/procesado/casos.csv           un caso por fila
          data/procesado/casos_senales.csv   todas las senales, con su caso (o por que no tiene)
"""
import sys

import pandas as pd

from config import CMF_HOME, RAIZ, casos_conocidos, umbral_materialidad

DIR_PROC = CMF_HOME / "procesado"
TOL_CASO = 2            # misma diferencia entre lineas de un caso (redondeo de cada linea)

ESTADO = {"total_activo": "ESF", "total_pasivo": "ESF", "activo_neto": "ESF", "efectivo": "ESF",
          "total_ingresos": "ERI", "total_gastos": "ERI", "utilidad_operacion": "ERI",
          "resultado_eri": "ERI", "resultado_eri_despues": "ERI",
          "operacion": "EFE", "financiamiento": "EFE", "saldo_final": "EFE"}
ANCLA = {"ESF": "activo_neto", "ERI": "resultado_eri", "EFE": "saldo_final"}
DOCUMENTO = {"solo_pdf_t": "PDF t", "solo_pdf_t1": "PDF t+1 (comparativo)", "solo_xml_t": "XML t",
             "solo_xml_t1": "XML t+1 (comparativo)", "reexpresion": "PDF y XML t+1",
             "criterio": "PDF vs XML (ambos anios)", "otro": "?"}


def leer():
    c = pd.read_csv(DIR_PROC / "comparativos_pdf.csv", dtype={"rut": str})
    if "patron" not in c:
        sys.exit("comparativos_pdf.csv sin columna patron: corre antes el 03e")
    c["estado"] = c["linea"].map(ESTADO)
    for k in ("motivo_t", "motivo_t1"):
        c[k] = c[k].fillna("")
    # 03b: el subtotal del documento con la diferencia suma sus lineas?
    est = pd.read_csv(DIR_PROC / "estructura_efe.csv", dtype={"rut": str})
    if "pdf_suma" in est:
        suma = {(r.rut, r.anio, r.subtotal, r.columna): bool(r.pdf_suma)
                for r in est[["rut", "anio", "subtotal", "columna", "pdf_suma"]].dropna().itertuples()}
    else:
        print("AVISO: estructura_efe.csv sin pdf_suma; no se distingue error_suma")
        suma = {}

    def no_suma(r):
        if r.patron == "solo_pdf_t":
            k = (r.rut, r.anio_t, r.linea, "actual")
        elif r.patron == "solo_pdf_t1":
            k = (r.rut, r.anio_t + 1, r.linea, "anterior")
        else:
            return False
        return suma.get(k) is False
    c["no_suma"] = [no_suma(r) for r in c.itertuples()]
    return c


def senales(c):
    s = c[~c["patron"].isin(["cuadra", "incompleto"])].copy()
    s["motivo_no_caso"] = ""
    s.loc[s["dif_patron"].abs() <= s["moneda"].map(umbral_materialidad), "motivo_no_caso"] = "inmaterial"
    s.loc[s["clase"] == "lectura", "motivo_no_caso"] = "lectura"
    # Version distinta en 0 (omitida): no comparte diferencia con las otras lineas omitidas
    col = s["patron"].str.replace("solo_", "", regex=False)
    val = [getattr(r, k) if k in ("pdf_t", "pdf_t1", "xml_t", "xml_t1") else float("nan")
           for r, k in zip(s.itertuples(), col)]
    s["en_cero"] = pd.Series(val, index=s.index).abs() <= 1
    return s


def agrupar(s):
    """caso_id por (fondo, anio, patron) y misma |dif|. Las lineas omitidas (version distinta en 0)
    del mismo fondo, anio y patron son UN caso: un comparativo en 0 tiene una dif distinta por linea."""
    s = s.sort_values(["rut", "anio_t", "patron", "en_cero", "dif_patron"],
                      key=lambda x: x.abs() if x.name == "dif_patron" else x)
    ids, n, prev = [], 0, None
    for r in s.itertuples():
        if r.motivo_no_caso:
            ids.append(pd.NA)
            continue
        clave = (r.rut, r.anio_t, r.patron, r.en_cero)
        if prev is None or prev[0] != clave or (not r.en_cero and abs(abs(r.dif_patron) - prev[1]) > TOL_CASO):
            n += 1
        ids.append(n)
        prev = (clave, abs(r.dif_patron))
    s["caso_id"] = pd.array(ids, dtype="Int64")
    return s


def tipificar(s, c):
    pat = {(r.rut, r.anio_t, r.linea): (r.patron, r.clase) for r in c.itertuples()}

    def ancla_ok(rut, anio, estado):
        p = pat.get((rut, anio, ANCLA[estado]))
        if p is None or p[0] == "incompleto" or p[1] == "lectura":
            return None                          # no se puede decidir
        return p[0] == "cuadra"

    casos = []
    for cid, g in s[s["caso_id"].notna()].groupby("caso_id"):
        r0 = g.iloc[0]
        lineas, estados = list(g["linea"]), sorted(set(g["estado"]))
        if any(ANCLA[e] in lineas for e in estados):
            tipo = "error_total"
        elif g["no_suma"].any():
            tipo = "error_suma"
        else:
            ok = [ancla_ok(r0.rut, r0.anio_t, e) for e in estados]
            por_estado = g.groupby("estado").size()
            esf_par = {"total_activo", "total_pasivo"} <= set(lineas)
            if None in ok:
                tipo = "sin_ancla"
            elif not all(ok):
                tipo = "error_linea"            # el ancla tiene su propia diferencia (otro caso)
            elif (por_estado >= 2).any() and ("ESF" not in estados or esf_par):
                tipo = "reclasificacion"
            elif estados == ["EFE"] and len(lineas) == 1:
                tipo = "reclasificacion_dc"
            else:
                tipo = "error_linea"
        if g["en_cero"].all():
            tipo = "omision"        # el documento distinto trae estas lineas en 0
        # Familia del caso; el tipo por niveles queda como subtipo
        subtipo = tipo
        if r0.patron == "reexpresion":
            tipo = "reexpresion"
        elif r0.patron in ("solo_pdf_t", "solo_pdf_t1"):
            tipo = "pdf"            # error de cifra o reclasificacion segun el subtipo (revision 03e)
        elif r0.patron in ("solo_xml_t", "solo_xml_t1"):
            tipo = "error_xml"      # los dos PDF coinciden: revision por lotes 10/10 error del XML
        elif r0.patron == "criterio":
            tipo = "criterio"       # PDF y XML distintos igual en ambos anios: taxonomia de la AGF
        elif r0.patron == "otro":
            tipo = subtipo = "otro"
        casos.append(dict(caso_id=cid, rut=r0.rut, anio_t=r0.anio_t, nombre_agf=r0.nombre_agf, moneda=r0.moneda,
                          patron=r0.patron, documento=DOCUMENTO.get(r0.patron, "?"), tipo=tipo, subtipo=subtipo,
                          estados=",".join(estados), lineas=",".join(lineas), n_senales=len(g),
                          dif=g["dif_patron"].abs().max()))
    return pd.DataFrame(casos)


def cobertura(c):
    """Por estado: el ancla tiene sus 4 versiones y lectura limpia (base: fondo-anio con par t / t+1)."""
    base = c[["rut", "anio_t"]].drop_duplicates()
    filas = []
    for e, a in ANCLA.items():
        x = base.merge(c[c["linea"] == a][["rut", "anio_t", "patron", "clase"]], how="left")
        est = pd.Series("limpia", index=x.index)
        est[x["clase"] == "lectura"] = "dudosa"
        est[x["patron"] == "incompleto"] = "sin_xml"
        est[x["patron"].isna()] = "sin_par_pdf"
        filas.append(est.value_counts().rename(f"{e} ({a})"))
    t = pd.concat(filas, axis=1).fillna(0).astype(int).T
    print(f"\ncobertura del ancla por estado ({len(base)} fondo-anio con PDF t y t+1):")
    print(t.assign(pct_limpia=(100 * t.get("limpia", 0) / len(base)).round(1)).to_string())


def lectura_por_motivo(s):
    x = s[s["motivo_no_caso"] == "lectura"]
    m = (x["motivo_t"].where(x["motivo_t"] != "", "-") + " / " + x["motivo_t1"].where(x["motivo_t1"] != "", "-"))
    m[m == "- / -"] = "huella (cero o digito)"
    print(f"\nsenales de lectura ({len(x)}) por motivo (PDF t / PDF t+1):")
    print(m.value_counts().to_string())


LADO_XML = ["solo_xml_t", "solo_xml_t1", "reexpresion"]     # el XML de t+1 cambio la cifra de t


def con_07(casos):
    """Clase del 07 (XML t+1 comparativo vs XML t, cifra por cifra) para el par del caso."""
    ruta = DIR_PROC / "continuidad_resumen.csv"
    if not ruta.exists():
        print("AVISO: sin continuidad_resumen.csv (corre el 07)")
        casos["clase_07"] = pd.NA
        return casos
    r = pd.read_csv(ruta, dtype={"rut": str}, usecols=["rut", "anio", "clase"])
    r = r.rename(columns={"anio": "anio_t1", "clase": "clase_07"})
    casos = casos.assign(anio_t1=casos["anio_t"] + 1).merge(r, on=["rut", "anio_t1"], how="left")
    casos["clase_07"] = casos["clase_07"].fillna("sin_07")
    x = casos[casos["patron"].isin(LADO_XML + ["criterio"])]
    print("\nlado XML y criterio contra el 07 (clase del fondo-anio t+1):")
    print(pd.crosstab(x["patron"], x["clase_07"], margins=True).to_string())
    return casos.drop(columns="anio_t1")


def concentracion(casos):
    """Criterio y lado XML: muchos casos o pocas AGF con una plantilla?
    Agrupa por rut_agf (la misma AGF aparece con nombres distintos segun el anio)."""
    enc = pd.read_csv(DIR_PROC / "encabezados.csv", dtype={"rut": str, "rut_agf": str})
    if "rut_agf" in enc:
        enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "rut_agf", "nombre_agf"]].rename(
            columns={"anio": "anio_t", "nombre_agf": "nombre_ult"})
        casos = casos.merge(enc, on=["rut", "anio_t"], how="left")
        casos["rut_agf"] = casos["rut_agf"].fillna(casos["nombre_agf"])
        ultimo = casos.sort_values("anio_t").groupby("rut_agf")["nombre_ult"].last()
        casos["nombre_agf"] = casos["rut_agf"].map(ultimo).fillna(casos["nombre_agf"])
    for nombre, pats in (("criterio (PDF vs XML en ambos anios)", ["criterio"]),
                         ("lado XML (solo_xml_t, solo_xml_t1)", ["solo_xml_t", "solo_xml_t1"])):
        x = casos[casos["patron"].isin(pats)]
        if not len(x):
            continue
        g = (x.groupby("nombre_agf").agg(casos=("caso_id", "size"), fondos=("rut", "nunique"),
                                         anios=("anio_t", lambda a: f"{a.min()}-{a.max()}"),
                                         tipos=("subtipo", lambda t: ",".join(f"{k}:{v}" for k, v in
                                                                         t.value_counts().items())))
               .sort_values("casos", ascending=False))
        top3 = g["casos"].head(3).sum() / len(x)
        print(f"\n{nombre}: {len(x)} casos, {len(g)} AGF; las 3 primeras concentran {top3:.0%}")
        print(g.head(8).to_string())


def validar(s, casos):
    ruta = RAIZ / "verificacion" / "revision_03e.xlsx"
    if not ruta.exists():
        return
    v = pd.read_excel(ruta, dtype={"rut": str})
    v = v[v["veredicto"].notna()].rename(columns={"anio": "anio_t", "identidad": "linea"})
    t = s[["rut", "anio_t", "linea", "caso_id", "motivo_no_caso"]].merge(
        v[["rut", "anio_t", "linea", "veredicto"]], on=["rut", "anio_t", "linea"], how="right")
    t = t.merge(casos[["caso_id", "tipo", "subtipo"]], on="caso_id", how="left")
    t["tipo"] = (t["tipo"] + "/" + t["subtipo"]).fillna(t["motivo_no_caso"].replace("", pd.NA)).fillna("sin_senal")
    print(f"\nvalidacion contra la revision del 03e ({len(t)} casos con veredicto):")
    print(pd.crosstab(t["tipo"], t["veredicto"], margins=True).to_string())


def main():
    c = leer()
    s = agrupar(senales(c))
    casos = con_07(tipificar(s, c))
    s = s.merge(casos[["caso_id", "tipo", "subtipo"]], on="caso_id", how="left")
    casos.to_csv(DIR_PROC / "casos.csv", index=False, encoding="utf-8-sig")
    s.to_csv(DIR_PROC / "casos_senales.csv", index=False, encoding="utf-8-sig")

    print(f"senales: {len(s)}  (lectura {int((s['motivo_no_caso'] == 'lectura').sum())}, "
          f"inmaterial {int((s['motivo_no_caso'] == 'inmaterial').sum())})")
    print(f"casos: {len(casos)} en {casos[['rut', 'anio_t']].drop_duplicates().shape[0]} fondo-anio  "
          f"(senales por caso: {casos['n_senales'].mean():.2f})")
    print("\ntipo x documento:")
    print(pd.crosstab(casos["tipo"], casos["documento"], margins=True).to_string())
    print("\nsubtipo (nivel) x tipo:")
    print(pd.crosstab(casos["subtipo"], casos["tipo"], margins=True).to_string())
    multi = casos[casos["n_senales"] > 1].sort_values("n_senales", ascending=False).head(10)
    print("\ncasos con mas senales:")
    for r in multi.itertuples():
        print(f"  {r.rut:>6} {r.anio_t}  {r.tipo + "/" + r.subtipo:<30} {r.documento:<22} dif={r.dif:>14,.0f}  {r.lineas}")
    concentracion(casos)
    cobertura(c)
    lectura_por_motivo(s)
    validar(s, casos)
    print("\nvalidacion con casos conocidos:")
    for rut, anio, esperado in casos_conocidos("04b"):
        x = casos[(casos["rut"] == rut) & (casos["anio_t"] == anio)]
        print(f"  {rut} {anio}->{anio + 1}: " + ("; ".join(
            f"{r.tipo}/{r.subtipo} {r.documento} ({r.n_senales} senales, dif {r.dif:,.0f})" for r in x.itertuples())
            or "sin caso"))
        print(f"      esperado: {esperado}")
    print(f"\nsalida: {DIR_PROC / 'casos.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())