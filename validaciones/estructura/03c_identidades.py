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
clases). Solo se ubican las lineas nuevas, en la pagina del estado (o la
siguiente), con la misma regla del 03b: glosa + al menos una columna igual al
XML; si no, glosa en UNA sola linea ("solo_glosa").

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
          data/procesado/identidades_no_cuadra.csv  las que no cuadran, clasificadas
"""
import importlib
import re
import sys

import pandas as pd

from config import CMF_HOME, umbral_materialidad
from comun.lector_espacial import cargar_coords, filas_espaciales

m03b = importlib.import_module("validaciones.estructura.03b_estructura")
norm, TOL, SUB03B = m03b.norm, m03b.TOL, m03b.SUBTOTALES
DIR_PROC = CMF_HOME / "procesado"

# Lineas que el 03b no ubica. glosa: regex sobre texto sin espacios (norm).
# codigos: candidatos en orden de preferencia; si ninguno existe en cuentas.csv
# se busca por patron_codigo y se avisa cual se uso.
LINEAS = {
    "activo_neto": dict(
        estado="ESF",
        # "Total pasivo (excluido el activo neto atribuible...)" tambien lo contiene
        glosa=re.compile(r"^(?!.*excluid)(total)?activos?netos?atribuible"),
        codigos=["ActivoNetoAtribuibleALosParticipes", "ActivoNetoAtribuibleAParticipes"],
        patron_codigo=r"^(Total)?ActivoNetoAtribuible"),
    "utilidad_operacion": dict(
        estado="ERI",
        # "Total ingresos/(perdidas) netos de la operacion" tambien calza sin el (?!total)
        glosa=re.compile(r"^(?!total)\(?(utilidad|p[eé]rdida|resultado).*operaci"),
        codigos=["UtilidadPerdidaDeLaOperacion", "UtilidadPerdidaOperacional", "ResultadoDeLaOperacion"],
        patron_codigo=r"^(Utilidad|Resultado).*Operacion"),
    "efectivo": dict(
        estado="ESF",
        glosa=re.compile(r"^efectivoy(efectivo)?equivalentes?(al(efectivo)?)?[^a-z]*$"),   # "(+)" al final
        codigos=["EfectivoYEfectivoEquivalente"],
        patron_codigo=r"^EfectivoYEfectivoEquivalente$"),
    "saldo_final": dict(
        estado="EFE",
        glosa=re.compile(r"saldofinal|alfinaldel(per[ií]odo|ejercicio)|efectivo.*alcierre"),
        codigos=["SaldoFinalDeEfectivoYEfectivoEquivalente", "EfectivoYEfectivoEquivalenteAlFinalDelPeriodo"],
        patron_codigo=r"SaldoFinal.*Efectivo|Efectivo.*AlFinal"),
}
# Pagina de cada estado = la de sus subtotales del 03b
PAGINA_DE = {"ESF": ["total_activo", "total_pasivo"], "ERI": ["total_gastos", "total_ingresos"],
             "EFE": ["financiamiento", "operacion"]}

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


def lineas_pagina(coords, p, cache):
    """[(glosa+previas, glosa, act, ant, pagina)] de las lineas con montos. Las previas son
    hasta 2 lineas sin montos inmediatamente anteriores (rotulo partido en 2 o 3 lineas:
    "Utilidad (perdida) de la" / "operacion antes de" / "impuesto  (15.751)")."""
    if p not in cache:
        pg = coords["paginas"].get(str(p))
        out, previa = [], ""
        for g, a, b, _ in (filas_espaciales(pg)[0] if pg else []):
            if a is None:
                previa = (previa.split("\x00")[-1] + "\x00" + g) if previa else g   # ultimas 2
                continue
            out.append((norm(previa.replace("\x00", " ") + " " + g), norm(g), a, b, p))
            previa = ""
        cache[p] = out
    return cache[p]


def ubicar(lineas, rx, x_act, x_ant):
    cand = [l for l in lineas if rx.search(l[1]) or rx.search(l[0])]
    for l in cand:
        if (x_act and abs(abs(l[2]) - abs(x_act)) <= TOL) or (x_ant and abs(abs(l[3]) - abs(x_ant)) <= TOL):
            return l, "glosa_y_valor"
    return (cand[0], "solo_glosa") if len(cand) == 1 else (None, None)


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
    ok = (res[res["estado"].isin(["ok", "sin_texto"])].drop(columns=["moneda"], errors="ignore")
          .merge(enc, on=["rut", "anio"]))

    est = pd.read_csv(DIR_PROC / "estructura_efe.csv", dtype={"rut": str})
    est = est[est["ubicado"] == True]
    tot = {k: {(f.subtotal, f.columna): f for f in g.itertuples(index=False)}
           for k, g in est.groupby(["rut", "anio"])}

    cta = pd.read_csv(DIR_PROC / "cuentas.csv", usecols=["archivo", "contexto", "codigo", "serie", "valor"],
                      dtype={"serie": str})
    cta = cta[cta["serie"].isna()]
    print("codigos XML de las lineas nuevas:")
    codigos = resolver_codigos(set(cta["codigo"].unique()))
    necesarios = {c for c in codigos.values() if c} | {cfg["codigo"] for cfg in SUB03B.values()}
    cta = cta[cta["codigo"].isin(necesarios) & cta["archivo"].isin(ok["archivo"])]
    xml_de = {a: {(c, k): v for c, k, v in zip(g["contexto"], g["codigo"], g["valor"].fillna(0))}
              for a, g in cta.groupby("archivo")}

    filas, ubic = [], {k: [0, 0] for k in LINEAS}
    for r in ok.itertuples(index=False):
        t = tot.get((r.rut, r.anio))
        if not t:
            continue
        coords = cargar_coords(r.rut, r.anio, r.pdf)
        if coords is None:
            continue
        x = xml_de.get(r.archivo, {})
        pag = {e: next((int(f.pagina) for (s, _), f in t.items() if s in subs), None)
               for e, subs in PAGINA_DE.items()}
        cache, nuevas = {}, {}
        for k, cfg in LINEAS.items():
            p = pag[cfg["estado"]]
            if p is None:
                continue
            ubic[k][1] += 1
            cod = codigos[k]
            xa = x.get(("PeriodoActual", cod)) if cod else None
            xb = x.get(("PeriodoAnterior", cod)) if cod else None
            lin = lineas_pagina(coords, p, cache) + lineas_pagina(coords, p + 1, cache)
            l, metodo = ubicar(lin, cfg["glosa"], xa, xb)
            if l is None:
                continue
            ubic[k][0] += 1
            q = l[4]
            nuevas[k] = dict(actual=l[2], anterior=l[3], xml_actual=xa, xml_anterior=xb, pagina=q, metodo=metodo,
                             ocr=coords["paginas"].get(str(q), {}).get("origen") == "ocr",
                             esp=es_espaciada(coords, q))

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
                            paginas=",".join(sorted({str(v["pagina"]) for v in ts})),
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
    df.to_csv(DIR_PROC / "identidades.csv", index=False, encoding="utf-8-sig")
    nc = df[df["clase"] != "cuadra"]
    nc.to_csv(DIR_PROC / "identidades_no_cuadra.csv", index=False, encoding="utf-8-sig")

    # --- Consola ---
    print("\nlineas nuevas ubicadas (de los fondo-anio con la pagina del estado):")
    for k, (u, n) in ubic.items():
        print(f"  {k:<20} {u:>5}/{n:<5} ({u / max(n, 1):.1%})")
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
    print(f"\nsalida: {DIR_PROC / 'identidades.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())