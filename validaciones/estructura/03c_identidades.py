"""
03c: identidades entre lineas y entre estados del PDF
=====================================================

El 03b revisa que cada subtotal sea la suma de sus lineas. No ve un estado que
suma bien por dentro pero no calza con otro: un total de pasivo correcto con un
activo neto mal impreso, o un efectivo del ESF distinto del saldo final del EFE.

Identidades (por columna actual/anterior):
  activo_menos_pasivo    ESF: total activo - total pasivo = activo neto atribuible a participes
  ingresos_menos_gastos  ERI: total ingresos - total gastos = utilidad (perdida) de la operacion
  efectivo_esf_efe       ESF vs EFE: efectivo y efectivo equivalente = saldo final del EFE

Los totales se toman del 03b (estructura_efe.csv: misma ubicacion, mismas
clases). Las lineas nuevas son los renglones del lector unificado emparejados
con su codigo (comun.emparejar.leer_y_emparejar, como el 03b y la ficha):
metodo glosa_y_valor / solo_glosa (el valor impreso difiere del XML) / valor
(rotulo distinto). Antes cada linea tenia su regex, su lectura por pagina y
respaldos por posicion y por fila vecina; ahora eso lo resuelve el lector.

El XML es el tercer punto, como en el 03b:
  probable_error_pdf    el PDF no cuadra, el XML si, y UN solo termino del PDF difiere del XML
  probable_error_ambos  no cuadra ni el PDF ni el XML, y el PDF = XML termino a termino
                        (el error viene del documento de origen y quedo en los dos formatos)
  probable_error_xml    el PDF cuadra y el XML no
  probable_lectura      2+ terminos difieren del XML, o la linea se ubico solo por glosa
  probable_lectura_ocr  pagina OCR (como en el 03b: un no-cuadre ahi es lectura)
  observacion_inmaterial  diferencia bajo el umbral de materialidad

Chequeo de la definicion: si la identidad del XML no cuadra en muchos fondos,
la identidad esta mal planteada (no hay error en tantos fondos). Se imprime.

Lee:      data/procesado/estructura_efe.csv (03b), cruce_resumen.csv, encabezados.csv, cuentas.csv
Escribe:  data/procesado/identidades.csv            1 fila por fondo-anio-identidad-columna
          data/procesado/lineas_03c.csv            lineas ubicadas (activo neto, resultado del ERI...) para el 03d
          data/procesado/identidades_no_cuadra.csv  las que no cuadran, clasificadas
"""
import importlib
import re
import sys

import pandas as pd

from config import CMF_HOME, casos_conocidos, umbral_materialidad
from comun.emparejar import leer_y_emparejar
from comun.lector_espacial import cargar_coords
from comun.secciones import asignar_secciones

m03b = importlib.import_module("validaciones.estructura.03b_estructura")
norm, TOL, SUB03B = m03b.norm, m03b.TOL, m03b.SUBTOTALES
DIR_PROC = CMF_HOME / "procesado"

# Lineas que el 03b no ubica: estado y codigo XML. codigos: candidatos en orden de preferencia; si
# ninguno existe en cuentas.csv se busca por patron_codigo y se avisa cual se uso.
LINEAS = {
    "activo_neto": dict(estado="ESF", codigos=["ActivoNetoAtribuibleALosParticipes", "ActivoNetoAtribuibleAParticipes"],
                        patron_codigo=r"^(Total)?ActivoNetoAtribuible"),
    "utilidad_operacion": dict(estado="ERI",
                               codigos=["UtilidadPerdidaDeLaOperacion", "UtilidadPerdidaOperacional", "ResultadoDeLaOperacion"],
                               patron_codigo=r"^(Utilidad|Resultado).*Operacion"),
    "efectivo": dict(estado="ESF", codigos=["EfectivoYEfectivoEquivalente"],
                     patron_codigo=r"^EfectivoYEfectivoEquivalente$"),
    "saldo_final": dict(estado="EFE",
                        codigos=["SaldoFinalDeEfectivoYEfectivoEquivalente", "EfectivoYEfectivoEquivalenteAlFinalDelPeriodo"],
                        patron_codigo=r"SaldoFinal.*Efectivo|Efectivo.*AlFinal"),
    # Para el 03d (resultado del ERI = resultado del ECP; tramo antes -> distribucion -> despues)
    "resultado_eri": dict(estado="ERI", codigos=[
        "AumentoDisminucionDeActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionAntesDeDistribucionDeBeneficios"],
        patron_codigo=r"^AumentoDisminucionDeActivoNeto.*AntesDeDistribucion"),
    "resultado_eri_despues": dict(estado="ERI", codigos=[
        "AumentoDisminucionDeActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionDespuesDeDistribucionDeBeneficios"],
        patron_codigo=r"^AumentoDisminucionDeActivoNeto.*DespuesDeDistribucion"),
}
METODO = {"ambos": "glosa_y_valor", "glosa": "solo_glosa", "valor": "valor"}


def dudosa(l, xa, xb):
    """Linea ubicada solo por glosa con las DOS columnas distintas al XML: casi siempre es otro
    renglon de glosa parecida (utilidad antes de impuesto no impresa -> renglon en 0) o una lectura
    mala (digitos pegados o cortados), no un error. Un error real en una columna deja la otra
    calzando (coincide "ambos"). Con una sola columna en el XML (primer anio) se acepta.
    Revision migracion 03c: 58 de 68 identidades nuevas que no cuadraban venian de estas lineas."""
    if l["coincide"] != "glosa":
        return False
    pares = [(p or 0, x) for p, x in ((l["actual"], xa), (l["anterior"], xb)) if x is not None]
    return len(pares) == 2 and all(abs(abs(p) - abs(x)) > TOL for p, x in pares)

# dif estricta (convencion habitual de presentacion) y laxa (signo de presentacion
# distinto: perdida impresa sin parentesis). Solo la laxa decide si cuadra.
IDENTIDADES = {
    "activo_menos_pasivo": dict(
        terminos=["total_activo", "total_pasivo", "activo_neto"],
        dif=lambda a, p, n: abs(a) - abs(p) - n,
        laxa=lambda a, p, n: min(abs(abs(a) - abs(p) - n), abs(abs(a) - abs(p) + n))),
    "ingresos_menos_gastos": dict(
        terminos=["total_ingresos", "total_gastos", "utilidad_operacion"],
        dif=lambda i, g, u: i - abs(g) - u,
        laxa=lambda i, g, u: min(abs(i - abs(g) - u), abs(i - abs(g) + u), abs(-i - abs(g) - u))),
    "efectivo_esf_efe": dict(
        terminos=["efectivo", "saldo_final"],
        dif=lambda e, s: abs(e) - abs(s),
        laxa=lambda e, s: abs(abs(e) - abs(s))),
}


def resolver_codigos(todos):
    out = {}
    for k, cfg in LINEAS.items():
        cod = next((c for c in cfg["codigos"] if c in todos), None)
        if cod is None:
            cands = sorted((c for c in todos if re.search(cfg["patron_codigo"], c)), key=len)
            cod = cands[0] if cands else None
            if len(cands) > 1:
                print(f"AVISO {k}: {len(cands)} codigos posibles, se usa el mas corto '{cod}' "
                      f"(otros: {', '.join(cands[1:5])}) -> fijalo en LINEAS si no es el correcto")
        print(f"  {k:<20} codigo XML: {cod or '(ninguno: solo glosa, sin triangular)'}")
        out[k] = cod
    return out


def es_espaciada(coords, p):
    pal = coords["paginas"].get(str(p), {}).get("palabras", [])
    return bool(pal) and sum(len(w[0]) == 1 for w in pal) / len(pal) > 0.5


def clasificar(r, umbral):
    if r["cuadra_pdf"]:
        return "probable_error_xml" if r["cuadra_xml"] is False else "cuadra"
    dist = r["terminos_distintos_xml"].split(",") if r["terminos_distintos_xml"] else []
    if r["cuadra_xml"] is None:
        clase = "revisar_sin_xml"
    elif not dist:
        clase = "probable_error_ambos" if r["cuadra_xml"] is False else "revisar_signo"
    elif len(dist) == 1 and r["cuadra_xml"] and r[f"metodo_{dist[0]}"] != "solo_glosa":
        clase = "probable_error_pdf"
    else:
        clase = "probable_lectura"
    if clase.startswith("probable_error") or clase == "probable_lectura":
        if r["pagina_ocr"]:
            clase = "probable_lectura_ocr"
        elif r["pagina_espaciada"] and clase.startswith("probable_error"):
            clase = "probable_lectura"
    if clase != "probable_lectura_ocr" and abs(r["dif_pdf"]) <= umbral:
        clase = "observacion_inmaterial"
    return clase


def main():
    res = pd.read_csv(DIR_PROC / "cruce_resumen.csv", dtype={"rut": str})
    enc = pd.read_csv(DIR_PROC / "encabezados.csv", dtype={"rut": str})
    enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "archivo", "moneda"]]
    ok = (res[res["estado"].isin(["ok", "sin_texto", "sin_paginas_de_estados"]) & res["pdf"].notna()]
          .drop(columns=["moneda"], errors="ignore").merge(enc, on=["rut", "anio"]))

    est = pd.read_csv(DIR_PROC / "estructura_efe.csv", dtype={"rut": str})
    est = est[est["ubicado"] == True]
    tot = {k: {(f.subtotal, f.columna): f for f in g.itertuples(index=False)}
           for k, g in est.groupby(["rut", "anio"])}

    # Todas las cuentas del archivo: el emparejador necesita el estado completo
    cta = pd.read_csv(DIR_PROC / "cuentas.csv", usecols=["archivo", "contexto", "codigo", "serie", "valor"],
                      dtype={"serie": str})
    cta = cta[cta["archivo"].isin(ok["archivo"]) & cta["codigo"].notna() & cta["valor"].notna()]
    print("codigos XML de las lineas nuevas:")
    codigos = resolver_codigos(set(cta.loc[cta["serie"].isna(), "codigo"].unique()))
    cta_de = dict(tuple(cta.groupby("archivo", sort=False)))

    filas, ubic, lineas_out = [], {k: [0, 0] for k in LINEAS}, []
    dudosas = {k: 0 for k in LINEAS}
    for r in ok.itertuples(index=False):
        t = tot.get((r.rut, r.anio))
        if not t:
            continue
        coords = cargar_coords(r.rut, r.anio, r.pdf)
        c = cta_de.get(r.archivo)
        if coords is None or c is None:
            continue
        c = c.copy()
        c["estado_fin"] = asignar_secciones(c["codigo"].tolist())
        renglones, _ = leer_y_emparejar(coords, r.paginas_estados, c)
        sx = c[c["serie"].isna()]
        x = {(ctx, k): v for ctx, k, v in zip(sx["contexto"], sx["codigo"], sx["valor"])}
        nuevas = {}
        for k, cfg in LINEAS.items():
            cod, rs = codigos[k], renglones.get(cfg["estado"], [])
            if not cod or not rs:
                continue
            ubic[k][1] += 1
            l = next((q for q in rs if q["codigo"] == cod and q["metodo"] != "encabezado"
                      and (q["actual"] is not None or q["anterior"] is not None)), None)
            if l is None:
                continue
            xa, xb, q = x.get(("PeriodoActual", cod)), x.get(("PeriodoAnterior", cod)), l["pagina"]
            if dudosa(l, xa, xb):
                dudosas[k] += 1
                continue
            ubic[k][0] += 1
            nuevas[k] = dict(actual=l["actual"] if l["actual"] is not None else 0,
                             anterior=l["anterior"] if l["anterior"] is not None else (0 if xb is not None else None),
                             xml_actual=xa, xml_anterior=xb, pagina=q, metodo=METODO[l["coincide"]],
                             ocr=coords["paginas"].get(str(q), {}).get("origen") == "ocr",
                             esp=es_espaciada(coords, q))

        # Lineas ubicadas (las usa el 03d: activo neto del ESF, resultado del ERI)
        for k, n in nuevas.items():
            for col in ("actual", "anterior"):
                lineas_out.append(dict(rut=r.rut, anio=r.anio, linea=k, columna=col, pdf=n[col],
                                       xml=n[f"xml_{col}"], pagina=n["pagina"], metodo=n["metodo"], ocr=n["ocr"]))

        def termino(nombre, col):
            if nombre in SUB03B:
                f = t.get((nombre, col))
                if f is None:
                    return None
                return dict(pdf=f.subtotal_pdf, xml=f.subtotal_xml, pagina=int(f.pagina), metodo="03b",
                            ocr=f.pagina_ocr == True, esp=f.pagina_espaciada == True)
            n = nuevas.get(nombre)
            if n is None or (col == "anterior" and n["xml_anterior"] is None and not n["anterior"]):
                return None                      # primer anio: sin columna anterior
            return dict(pdf=n[col], xml=n[f"xml_{col}"], pagina=n["pagina"], metodo=n["metodo"],
                        ocr=n["ocr"], esp=n["esp"])

        for nombre, cfg in IDENTIDADES.items():
            for col in ("actual", "anterior"):
                ts = [termino(n, col) for n in cfg["terminos"]]
                # Fondo que nace en el anio: el ESF trae comparativo a la fecha de inicio
                # ("20-03-2012") y el EFE no tiene columna anterior (saldo final 0 en PDF y XML).
                # La identidad no aplica (revision 03c: 3 de 3 casos asi).
                if (nombre == "efectivo_esf_efe" and col == "anterior" and ts[1] is not None
                        and not ts[1]["pdf"] and not ts[1]["xml"]):
                    continue
                if any(v is None for v in ts):
                    continue
                pdf = [v["pdf"] for v in ts]
                xml = [v["xml"] for v in ts]
                xml_ok = all(v is not None for v in xml)
                fila = dict(rut=r.rut, anio=r.anio, nombre_agf=r.nombre_agf, moneda=r.moneda,
                            identidad=nombre, columna=col,
                            dif_pdf=cfg["dif"](*pdf), cuadra_pdf=cfg["laxa"](*pdf) <= TOL,
                            dif_xml=cfg["dif"](*xml) if xml_ok else None,
                            cuadra_xml=(cfg["laxa"](*xml) <= TOL) if xml_ok else None,
                            terminos_distintos_xml=",".join(
                                n for n, v in zip(cfg["terminos"], ts)
                                if v["xml"] is not None and abs(abs(v["pdf"]) - abs(v["xml"])) > TOL),
                            pagina_ocr=any(v["ocr"] for v in ts), pagina_espaciada=any(v["esp"] for v in ts),
                            paginas=",".join(str(p) for p in sorted({int(v["pagina"]) for v in ts})),
                            pdf=" | ".join(f"{n}={v['pdf']}" for n, v in zip(cfg["terminos"], ts)),
                            xml=" | ".join(f"{n}={v['xml']}" for n, v in zip(cfg["terminos"], ts)))
                for n, v in zip(cfg["terminos"], ts):
                    fila[f"metodo_{n}"] = v["metodo"]
                fila["clase"] = clasificar(fila, umbral_materialidad(r.moneda))
                # Si el termino distinto es un total del 03b, el 03b ya lo marco (igual_xml=False):
                # lo nuevo de esta pasada son las lineas nuevas y los errores "ambos".
                dist = fila["terminos_distintos_xml"].split(",") if fila["terminos_distintos_xml"] else []
                fila["ya_en_03b"] = bool(dist) and all(d in SUB03B for d in dist)
                filas.append(fila)

    df = pd.DataFrame(filas)
    if df.empty:
        print("sin identidades evaluables")
        return 0
    df.to_csv(DIR_PROC / "identidades.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(lineas_out).to_csv(DIR_PROC / "lineas_03c.csv", index=False, encoding="utf-8-sig")
    nc = df[df["clase"] != "cuadra"]
    nc.to_csv(DIR_PROC / "identidades_no_cuadra.csv", index=False, encoding="utf-8-sig")

    # --- Consola ---
    print("\nlineas nuevas ubicadas (de los fondo-anio con la pagina del estado):")
    for k, (u, n) in ubic.items():
        print(f"  {k:<20} {u:>5}/{n:<5} ({u / max(n, 1):.1%})  descartadas solo por glosa: {dudosas[k]}")
    print("\npor identidad (filas = fondo-anio-columna):")
    resumen = df.groupby("identidad").agg(
        n=("clase", "size"), cuadra_pdf=("cuadra_pdf", "mean"),
        cuadra_xml=("cuadra_xml", lambda s: s.dropna().astype(bool).mean()))
    print(resumen.assign(cuadra_pdf=lambda d: (d.cuadra_pdf * 100).round(1),
                         cuadra_xml=lambda d: (d.cuadra_xml * 100).round(1)).to_string())
    print("  (si cuadra_xml es bajo, la identidad esta mal planteada para esa plantilla: revisar antes de leer clases)")
    print("\nno cuadran, clasificados:")
    print(pd.crosstab(nc["clase"], nc["identidad"], margins=True).to_string())
    pe = nc[nc["clase"].str.startswith("probable_error")]
    print(f"\nprobable_error* ({len(pe)}; {int((~pe['ya_en_03b']).sum())} que el 03b no ve):")
    for f in pe.sort_values(["clase", "identidad", "rut", "anio"]).itertuples():
        print(f"  {f.rut} {f.anio} {f.identidad:<22} {f.columna:<8} {f.clase[15:]:<6} dif={(f.dif_xml if f.clase == 'probable_error_xml' else f.dif_pdf):>14,.0f} "
              f"distinto={f.terminos_distintos_xml or '-'}  pag {f.paginas}{'  (ya en 03b)' if f.ya_en_03b else ''}")
    print("\nvalidacion con casos conocidos:")
    for rut, anio, esperado in casos_conocidos("03c"):       # privado: verificacion/casos_conocidos.csv
        x = df[(df["rut"] == rut) & (df["anio"] == anio)]
        malos = x[x["clase"] != "cuadra"]
        if x.empty:
            print(f"  {rut} {anio}: sin analizar")
        elif malos.empty:
            print(f"  {rut} {anio}: todas las identidades cuadran ({len(x)} filas)")
        for f in malos.itertuples():
            print(f"  {rut} {anio} {f.identidad:<22} {f.columna:<8} {f.clase:<22} "
                  f"distinto={f.terminos_distintos_xml or '-'}")
        print(f"      esperado: {esperado}")
    print(f"\nsalida: {DIR_PROC / 'identidades.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())