"""
03d: estado de cambios en el activo neto (ECP) leido desde el PDF
=================================================================

El ECP tiene una columna por serie mas una de total, y cada periodo en su propio
bloque (a veces en paginas distintas, a veces con series distintas entre anios).
Se lee con comun/lector_multicolumna (posicion, sin XML) y se verifica:

  dentro de cada bloque, POR COLUMNA (cada serie y el total), sin XML:
    transacciones   aportes - rescates = aumento neto por transacciones de cuotas
    evolucion       inicio + aumento neto + resultado - distribucion = cierre
  por fila:
    suma_series     suma de las series = columna Total
  entre bloques y estados (columna Total):
    cierre_esf      cierre del ECP = activo neto atribuible del ESF (de la salida del 03c)
    continuidad     inicio del bloque actual = cierre del bloque anterior (mismo PDF)

El XML solo entra como tercer punto, en la columna Total (las series del PDF no
se emparejan con las del XML). Clases de lo que no cuadra:
  probable_error_pdf    total: un solo termino distinto del XML y el XML cuadra;
                        serie: la serie no cuadra y todas las filas suman al total
                        (los montos estan bien leidos: la serie no cuadra en el PDF)
  probable_error_ambos  el PDF = XML termino a termino y ninguno cuadra
  probable_error_xml    el PDF cuadra y el XML no
  probable_lectura      2+ terminos distintos del XML, o filas que no suman al total
  probable_lectura_ocr  pagina OCR
  revisar_sin_xml       total sin cifras XML para comparar
  observacion_inmaterial  diferencia bajo el umbral de materialidad

Lee:      cruce_resumen.csv, encabezados.csv, cuentas.csv, identidades.csv (03c), coords_pdf/
Escribe:  data/procesado/ecp_bloques.csv     1 fila por fondo-anio-bloque (que se leyo)
          data/procesado/ecp_chequeos.csv    1 fila por chequeo
          data/procesado/ecp_no_cuadra.csv   los que no cuadran, clasificados
"""
import re
import sys
from collections import Counter

import pandas as pd

from comun.lector_espacial import cargar_coords
from comun.lector_multicolumna import columna_total, filas_multicolumna
from config import CMF_HOME, casos_conocidos, umbral_materialidad

DIR_PROC = CMF_HOME / "procesado"
TOL = 2


def norm(s):
    return re.sub(r"\s+", "", str(s)).lower()


RE_TITULO = re.compile(r"cambios?en(el|los)activos?netos?")
# Primera regla que calza, sobre la glosa sin espacios
FILAS = [
    ("neto", re.compile(r"transacci|netoorigina.*cuota")),
    ("res_antes", re.compile(r"antesde(la)?distribu|antes.*benefi")),
    ("res_despues", re.compile(r"despu[eé]sde(la)?distribu|despu[eé]s.*benefi")),
    # sin anclar: hay plantillas con la primera letra cruzada a la linea vecina ("AR porte", "e scate")
    ("aportes", re.compile(r"^aportes?|portes?decuota")),
    ("rescates", re.compile(r"^rescates?|escates?decuota")),
    ("dist_parte", re.compile(r"^en(efectivo|cuotas)")),
    ("dist", re.compile(r"^(total)?(distribuci|reparto)")),
    # resultado con la glosa cortada o sin "antes/despues": el primero es antes, el segundo despues
    ("res_generico", re.compile(r"^\(?(aumento|disminuci).*activos?neto")),
    ("activo_neto", re.compile(r"^.?activos?netos?atribuible")),
]
RE_CIERRE = re.compile(r"diciembre|31-12|31/12|cierre|final")
RE_INICIO = re.compile(r"enero|01-01|01/01|inicio")
RE_ANIO = re.compile(r"(?:19|20)\d\d")

XML = {  # codigos del total del fondo (sin serie)
    "inicio": "ActivoNetoAtribuibleALosParticipesAl01DeEnero",
    "aportes": "AportesDeCuotas", "rescates": "RescateDeCuotas",
    "neto": "AumentoNetoOriginadoPorTransaccionesDeCuotas",
    "res_antes": "AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionAntesDeDistribucionDeBeneficios",
    "res_despues": "AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionDespuesDeDistribucionDeBeneficios",
    "cierre": "ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuota",
}


# --------------------------------------------------------------------------- lectura
def leer_bloques(coords, paginas):
    """Bloques del ECP (inicio ... cierre) de las paginas con el titulo del estado."""
    bloques = []
    for p in paginas:
        pg = coords["paginas"].get(str(p))
        if not pg or not RE_TITULO.search(norm(" ".join(w[0] for w in pg["palabras"]))):
            continue
        renglones, franjas = filas_multicolumna(pg)
        if not franjas:
            continue
        hay_total = columna_total(pg, franjas)
        b, encabezado, pendiente = None, [], None
        for r in renglones:
            g = norm(r["glosa"])
            clave = next((k for k, rx in FILAS if rx.search(g)), None)
            # Fila reconocida sin montos ("Activo neto ... al 31 de diciembre") seguida de una
            # sin nombre con montos ("Valor Cuota  25.506.525 ..."): los montos son de la primera.
            if clave is None and r["vals"] and pendiente:
                clave, r = pendiente[0], {**r, "glosa": pendiente[1] + " " + r["glosa"]}
                g = norm(r["glosa"])
            pendiente = (clave, r["glosa"]) if clave and not r["vals"] else None
            if not r["vals"] or clave is None:
                if b is None:
                    encabezado.append(r["glosa"])
                continue
            if clave == "activo_neto":
                cierre, inicio = bool(RE_CIERRE.search(g)), bool(RE_INICIO.search(g))
                if b is None and not cierre:
                    b = dict(pagina=p, n_cols=len(franjas), hay_total=hay_total, encabezado=encabezado,
                             glosa_inicio=r["glosa"], glosa_cierre="", ocr=pg.get("origen") == "ocr",
                             filas={"inicio": dict(r["vals"])}, irr={("inicio", k) for k in r["irr"]})
                elif b is not None and (cierre or not inicio):
                    b["filas"]["cierre"] = dict(r["vals"])
                    b["irr"] |= {("cierre", k) for k in r["irr"]}
                    b["glosa_cierre"] = r["glosa"]
                    bloques.append(b)
                    b, encabezado = None, []
                continue
            if b is None:
                continue
            if clave == "res_generico":
                clave = "res_antes" if "res_antes" not in b["filas"] else "res_despues"
            if clave == "dist_parte":
                acc = b["filas"].setdefault("dist_partes", {})
                for k, v in r["vals"].items():
                    acc[k] = acc.get(k, 0) + v
            else:
                b["filas"].setdefault(clave, dict(r["vals"]))
                b["irr"] |= {(clave, k) for k in r["irr"]}
    return bloques


def anio_bloque(b):
    """Anio del bloque: el de la glosa del cierre o del inicio; si no, el mas repetido
    en el encabezado del bloque (titulo de pagina, "a) Al 31-12-2020", fecha de columnas)."""
    for t in (b["glosa_cierre"], b["glosa_inicio"]):
        ys = set(RE_ANIO.findall(t))
        if len(ys) == 1:
            return int(ys.pop())
    c = Counter(RE_ANIO.findall(" ".join(b["encabezado"]))).most_common(2)
    if c and (len(c) == 1 or c[0][1] > c[1][1]):
        return int(c[0][0])
    return None


def indice_total(b):
    """Columna Total: la ultima si tiene rotulo "Total", o si en el inicio la suma
    de las demas da la ultima. Con una sola columna, esa es el total del fondo."""
    n = b["n_cols"]
    if n == 1:
        return 0
    ini = b["filas"].get("inicio", {})
    suma = sum(v for k, v in ini.items() if k != n - 1)
    if b["hay_total"] or (n - 1 in ini and abs(suma - ini[n - 1]) <= TOL * n):
        return n - 1
    return None


# --------------------------------------------------------------------------- chequeos
def terminos_evolucion(F, k):
    """(dict de terminos, dif) de inicio + neto + resultado - distribucion - cierre, o None."""
    v = lambda c: F.get(c, {}).get(k)
    ini, cie, ap, rs, ne = v("inicio"), v("cierre"), v("aportes"), v("rescates"), v("neto")
    if ne is None and ap is not None and rs is not None:
        ne = ap - abs(rs)
    dist = v("dist") if v("dist") else v("dist_partes")
    if v("res_despues") is not None:
        res, t = v("res_despues"), {"res_despues": v("res_despues")}
    elif v("res_antes") is not None:
        res, t = v("res_antes") - abs(dist or 0), {"res_antes": v("res_antes")}
    else:
        return None
    if None in (ini, cie, ne):
        return None
    return {"inicio": ini, "neto": ne, **t, "cierre": cie}, ini + ne + res - cie


def chequear(b):
    """Chequeos internos de un bloque: [(chequeo, columna, terminos, dif)]."""
    F, out = b["filas"], []
    cols = sorted(set(F.get("inicio", {})) | set(F.get("cierre", {})))
    for k in cols:
        ap, rs, ne = (F.get(c, {}).get(k) for c in ("aportes", "rescates", "neto"))
        if None not in (ap, rs, ne):
            out.append(("transacciones", k, {"aportes": ap, "rescates": rs, "neto": ne}, ap - abs(rs) - ne))
        ev = terminos_evolucion(F, k)
        if ev:
            out.append(("evolucion", k, ev[0], ev[1]))
    t = b["total"]
    if t is not None and b["n_cols"] > 1:
        for fila, vals in F.items():
            if t in vals and fila != "dist_partes":
                s = sum(v for k, v in vals.items() if k != t)
                out.append(("suma_series", t, {fila: vals[t], "suma_series": s}, s - vals[t]))
    return out


def dif_xml(chequeo, xml_t):
    """Mismo chequeo con las cifras XML (columna Total), o None si faltan."""
    x = lambda c: xml_t.get(XML[c])
    if chequeo == "transacciones" and None not in (x("aportes"), x("rescates"), x("neto")):
        return x("aportes") - abs(x("rescates")) - x("neto")
    if chequeo == "evolucion" and None not in (x("inicio"), x("neto"), x("cierre")):
        res = x("res_despues") if x("res_despues") is not None else x("res_antes")
        if res is not None:
            return x("inicio") + x("neto") + res - x("cierre")
    return None


def es_tipeo(v, x):
    """v y x con el mismo numero de digitos, distintos en 1 digito o en 2 contiguos permutados
    (mismo criterio que el 03b). Una lectura que pierde o pega digitos cambia el largo."""
    a, b = str(abs(int(v))), str(abs(int(x)))
    if len(a) != len(b) or a == b or len(a) < 3:      # con 1-2 digitos cualquier cambio "es un digito"
        return False
    d = [i for i in range(len(a)) if a[i] != b[i]]
    return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])


def celdas_tipeo(b, chk):
    """Un monto mal impreso en una serie rompe su columna Y la suma de su fila con la misma
    diferencia. Devuelve {(chequeo, columna): detalle} y {fila: detalle} de esas celdas."""
    t, F = b["total"], b["filas"]
    filas_mal = {next(iter(terms)): d for c, _, terms, d in chk if c == "suma_series" and abs(d) > TOL}
    cols, filas = {}, {}
    for c, k, _, d in chk:
        if c == "suma_series" or k == t or abs(d) <= TOL:
            continue
        for f, s in filas_mal.items():
            v = F.get(f, {}).get(k)
            if v is not None and abs(abs(s) - abs(d)) <= TOL and es_tipeo(v, v - s):
                det = f"celda {f}/serie_{k + 1}: impreso {v:,.0f}, cuadraria con {v - s:,.0f}"
                cols[(c, k)] = det
                filas[f] = det
    return cols, filas


def rotulo_saldo(F, k):
    """El "aumento neto por transacciones" impreso es en realidad inicio + aportes - rescates
    (saldo acumulado con el rotulo del aumento neto; mismo caso que rotulo_incorrecto del 04)."""
    ini, ap, rs, ne = (F.get(c, {}).get(k) for c in ("inicio", "aportes", "rescates", "neto"))
    return (None not in (ini, ap, rs, ne) and abs(ini) > TOL
            and abs(ne - (ini + ap - abs(rs))) <= TOL and abs(ne - (ap - abs(rs))) > TOL)


def clasificar(r, suma_ok, umbral):
    if r["cuadra"]:
        return "probable_error_xml" if r["cuadra_xml"] is False else "cuadra"
    if r["ocr"]:
        return "probable_lectura_ocr"
    if r["es_total"]:
        dist = [d for d in r["distintos"].split(",") if d]
        if r["cuadra_xml"] is None:
            clase = "revisar_sin_xml"
        elif not dist:
            clase = "probable_error_ambos" if r["cuadra_xml"] is False else "probable_lectura"
        elif len(dist) == 1 and r["cuadra_xml"]:
            # 2+ digitos de diferencia con el XML: montos pegados o cortados en la lectura
            clase = "probable_lectura" if r.get("salto_digitos") else "probable_error_pdf"
        else:
            clase = "probable_lectura"
    else:
        # Series y suma de series: sin XML por serie. Que varias series o varias filas fallen
        # a la vez es lectura (columna que falta o sobra, monto en la columna vecina). Un error
        # real de una serie deja la huella de tipeo de celda, que se marca aparte (celdas_tipeo).
        clase = "probable_lectura"
    return "observacion_inmaterial" if abs(r["dif"]) <= umbral else clase


# --------------------------------------------------------------------------- principal
def esf_activo_neto():
    """(rut, anio, columna) -> (pdf, xml) del activo neto del ESF, de la salida del 03c."""
    ruta = DIR_PROC / "identidades.csv"
    if not ruta.exists():
        return {}
    i = pd.read_csv(ruta, dtype={"rut": str})
    i = i[i["identidad"] == "activo_menos_pasivo"]
    num = lambda s: (lambda m: float(m.group(1)) if m else None)(re.search(r"activo_neto=(-?[\d.]+)", str(s)))
    return {(r.rut, r.anio, r.columna): (num(r.pdf), num(r.xml)) for r in i.itertuples()}


def main():
    res = pd.read_csv(DIR_PROC / "cruce_resumen.csv", dtype={"rut": str, "paginas_estados": str})
    enc = pd.read_csv(DIR_PROC / "encabezados.csv", dtype={"rut": str})
    enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "archivo", "moneda"]]
    ok = (res[res["estado"].isin(["ok", "sin_texto"])].drop(columns=["moneda"], errors="ignore")
          .merge(enc, on=["rut", "anio"]))
    cta = pd.read_csv(DIR_PROC / "cuentas.csv", usecols=["archivo", "contexto", "codigo", "serie", "valor"],
                      dtype={"serie": str})
    cta = cta[cta["serie"].isna() & cta["codigo"].isin(XML.values()) & cta["archivo"].isin(ok["archivo"])]
    xml_de = {a: {(c, k): v for c, k, v in zip(g["contexto"], g["codigo"], g["valor"].fillna(0))}
              for a, g in cta.groupby("archivo")}
    esf = esf_activo_neto()
    ruta_nc = DIR_PROC / "identidades_no_cuadra.csv"
    err_03c = set()
    if ruta_nc.exists():
        n3 = pd.read_csv(ruta_nc, dtype={"rut": str})
        n3 = n3[(n3["identidad"] == "activo_menos_pasivo") & n3["clase"].str.startswith("probable_error")]
        err_03c = set(zip(n3["rut"], n3["anio"], n3["columna"]))

    filas_b, filas_c = [], []
    for r in ok.itertuples(index=False):
        coords = cargar_coords(r.rut, r.anio, r.pdf)
        if coords is None:
            continue
        paginas = [int(p) for p in str(r.paginas_estados).split(",") if p.strip().isdigit()]
        paginas = sorted(set(paginas) | {int(p) for p, v in coords["paginas"].items() if v.get("origen") == "ocr"})
        x = xml_de.get(r.archivo, {})
        base = dict(rut=r.rut, anio=r.anio, nombre_agf=r.nombre_agf, moneda=r.moneda)
        umbral = umbral_materialidad(r.moneda)
        por_col = {}
        bloques = leer_bloques(coords, paginas)
        for b in bloques:
            b["total"] = indice_total(b)
            a = anio_bloque(b)
            if a is None:
                # Sin fecha legible (texto espaciado, encabezado "2022 y 2021"): se fecha por el
                # cierre del Total contra el XML; si no calza, por orden (el primero es el actual).
                t = b["total"]
                cie = b["filas"].get("cierre", {}).get(t) if t is not None else None
                for c_, an in (("PeriodoActual", r.anio), ("PeriodoAnterior", r.anio - 1)):
                    xc = x.get((c_, XML["cierre"]))
                    if cie is not None and xc is not None and abs(abs(cie) - abs(xc)) <= TOL:
                        a = an
                        break
                else:
                    a = r.anio if "actual" not in por_col else r.anio - 1
                b["fechado_por"] = "xml_u_orden"
            col = {r.anio: "actual", r.anio - 1: "anterior"}.get(a)
            if col is None or col in por_col:
                continue                                  # bloque de otro anio o repetido
            por_col[col] = b
            filas_b.append({**base, "columna": col, "pagina": b["pagina"], "n_cols": b["n_cols"],
                            "total": b["total"], "filas": ",".join(sorted(b["filas"])), "ocr": b["ocr"],
                            "fechado_por": b.get("fechado_por", "texto")})
            fila_bloque = filas_b[-1]
            ctx = "PeriodoActual" if col == "actual" else "PeriodoAnterior"
            xml_t = {k: v for (c, k), v in x.items() if c == ctx}
            t = b["total"]
            comp = [abs(abs(b["filas"][f][t]) - abs(xml_t[c])) <= TOL for f, c in XML.items()
                    if t is not None and t in b["filas"].get(f, {}) and xml_t.get(c) is not None]
            # Bloque "desfasado": su total casi no coincide con el XML del periodo (otro anio,
            # otra tabla). Sus diferencias son de lectura, no del documento.
            b["coincide_xml"] = sum(comp) / len(comp) if comp else None
            fila_bloque["coincide_xml"] = b["coincide_xml"]
            chk = chequear(b)
            suma_ok = all(abs(d) <= TOL for c, _, _, d in chk if c == "suma_series")
            series_ok = all(abs(d) <= TOL for c, k, _, d in chk if c != "suma_series" and k != b["total"])
            tip_cols, tip_filas = celdas_tipeo(b, chk)
            fila_bloque["confiable"] = b["confiable"] = suma_ok and all(abs(d) <= TOL for c, k, _, d in chk
                                             if k == b["total"] and c != "suma_series")
            for chequeo, k, terms, d in chk:
                es_total = k == b["total"] and chequeo != "suma_series"
                fila = {**base, "columna": col, "pagina": b["pagina"], "chequeo": chequeo,
                        "col": "total" if k == b["total"] else f"serie_{k + 1}", "es_total": es_total,
                        "dif": d, "cuadra": abs(d) <= TOL, "ocr": b["ocr"], "series_cuadran": series_ok,
                        "pdf": " | ".join(f"{t}={v}" for t, v in terms.items()), "xml": "", "distintos": "",
                        "cuadra_xml": None}
                if es_total:
                    xv = {t: xml_t.get(XML[t]) for t in terms if t in XML}
                    fila["xml"] = " | ".join(f"{t}={v}" for t, v in xv.items())
                    fila["distintos"] = ",".join(t for t, v in terms.items()
                                                 if xv.get(t) is not None and abs(abs(v) - abs(xv[t])) > TOL)
                    dx = dif_xml(chequeo, xml_t)
                    fila["cuadra_xml"] = None if dx is None else abs(dx) <= TOL
                    fila["salto_digitos"] = any(
                        xv.get(t_) is not None and abs(len(str(abs(int(v)))) - len(str(abs(int(xv[t_]))))) >= 2
                        for t_, v in terms.items() if t_ in fila["distintos"].split(","))
                fila["clase"] = clasificar(fila, suma_ok, umbral)
                # Termino distinto impreso con agrupacion irregular ("26.767.9609"): formato, como en el 03b
                if es_total and any((t_, k) in b["irr"] for t_ in fila["distintos"].split(",") if t_):
                    fila["clase"], fila["detalle"] = "observacion_formato", "agrupacion de miles irregular"
                if (es_total and fila["clase"] in ("probable_error_pdf", "probable_error_ambos")
                        and (b["coincide_xml"] or 0) < 0.5):
                    fila["clase"] = "probable_lectura"
                if chequeo in ("evolucion", "transacciones") and not fila["cuadra"] and rotulo_saldo(b["filas"], k):
                    fila["clase"] = "probable_error_rotulo"
                    fila["detalle"] = "aumento neto impreso = inicio + aportes - rescates (saldo con rotulo de aumento neto)"
                det = tip_filas.get(next(iter(terms))) if chequeo == "suma_series" else tip_cols.get((chequeo, k))
                fila["detalle"] = det or fila.get("detalle", "")
                if det and fila["clase"] == "probable_lectura":
                    fila["clase"] = "probable_error_pdf"      # tipeo en una celda de serie
                filas_c.append(fila)

        # --- Cruces con la columna Total ---
        for col, b in por_col.items():
            t = b["total"]
            cie = b["filas"].get("cierre", {}).get(t) if t is not None else None
            e = esf.get((r.rut, r.anio, col))
            if cie is None or not e or e[0] is None:
                continue
            ctx = "PeriodoActual" if col == "actual" else "PeriodoAnterior"
            xc = x.get((ctx, XML["cierre"]))
            d = abs(cie) - abs(e[0])
            fila = {**base, "columna": col, "pagina": b["pagina"], "chequeo": "cierre_esf", "col": "total",
                    "es_total": True, "dif": d, "cuadra": abs(d) <= TOL, "ocr": b["ocr"], "series_cuadran": True,
                    "pdf": f"cierre_ecp={cie} | activo_neto_esf={e[0]}", "xml": f"cierre_ecp={xc} | activo_neto_esf={e[1]}",
                    "distintos": ",".join(n for n, p_, x_ in (("cierre_ecp", cie, xc), ("activo_neto_esf", e[0], e[1]))
                                          if x_ is not None and abs(abs(p_) - abs(x_)) > TOL),
                    "cuadra_xml": None if xc is None or e[1] is None else abs(abs(xc) - abs(e[1])) <= TOL}
            fila["clase"] = clasificar(fila, True, umbral)
            if fila["clase"].startswith("probable_error") and fila["clase"] != "probable_error_xml":
                # el ESF leido en la columna corrida (otra columna o balance de apertura de 2011)
                otros = [v[1] for o in ("actual", "anterior") if (v := esf.get((r.rut, r.anio, o)))]
                otros += [x.get((c_, XML["inicio"])) for c_ in ("PeriodoActual", "PeriodoAnterior")]
                corrido = "activo_neto_esf" in fila["distintos"] and any(
                    v is not None and abs(abs(e[0]) - abs(v)) <= TOL for v in otros)
                if not b["confiable"] or (b["coincide_xml"] or 0) < 0.5 or corrido:
                    fila["clase"] = "probable_lectura"
                elif fila["distintos"] == "activo_neto_esf":
                    # El que no coincide con el XML es el ESF: es terreno del 03c
                    if (r.rut, r.anio, col) in err_03c:
                        fila["detalle"] = "ya en 03c"
                    else:
                        fila["clase"] = "probable_lectura"
            filas_c.append(fila)
        if {"actual", "anterior"} <= set(por_col):
            ba, bp = por_col["actual"], por_col["anterior"]
            ini = ba["filas"].get("inicio", {}).get(ba["total"]) if ba["total"] is not None else None
            cie = bp["filas"].get("cierre", {}).get(bp["total"]) if bp["total"] is not None else None
            if ini is not None and cie is not None:
                xi, xc = x.get(("PeriodoActual", XML["inicio"])), x.get(("PeriodoAnterior", XML["cierre"]))
                d = ini - cie
                fila = {**base, "columna": "actual", "pagina": ba["pagina"], "chequeo": "continuidad", "col": "total",
                        "es_total": True, "dif": d, "cuadra": abs(d) <= TOL, "ocr": ba["ocr"] or bp["ocr"],
                        "series_cuadran": True, "pdf": f"inicio_actual={ini} | cierre_anterior={cie}",
                        "xml": f"inicio_actual={xi} | cierre_anterior={xc}",
                        "distintos": ",".join(n for n, p_, x_ in (("inicio_actual", ini, xi), ("cierre_anterior", cie, xc))
                                              if x_ is not None and abs(p_ - x_) > TOL),
                        "cuadra_xml": None if xi is None or xc is None else abs(xi - xc) <= TOL}
                fila["clase"] = clasificar(fila, True, umbral)
                if (fila["clase"].startswith("probable_error") and fila["clase"] != "probable_error_xml"
                        and not (ba["confiable"] and bp["confiable"]
                                 and (ba["coincide_xml"] or 0) >= 0.5 and (bp["coincide_xml"] or 0) >= 0.5)):
                    fila["clase"] = "probable_lectura"
                filas_c.append(fila)

    bl, ch = pd.DataFrame(filas_b), pd.DataFrame(filas_c)
    bl.to_csv(DIR_PROC / "ecp_bloques.csv", index=False, encoding="utf-8-sig")
    ch.to_csv(DIR_PROC / "ecp_chequeos.csv", index=False, encoding="utf-8-sig")
    nc = ch[ch["clase"] != "cuadra"]
    nc.to_csv(DIR_PROC / "ecp_no_cuadra.csv", index=False, encoding="utf-8-sig")

    # --- Consola ---
    n = len(ok)
    print(f"fondo-anio: {n}")
    for col in ("actual", "anterior"):
        k = int((bl["columna"] == col).sum()) if len(bl) else 0
        print(f"  con bloque {col:<9}: {k:>5} ({k / max(n, 1):.1%})")
    print(f"  bloques con columna Total identificada: {bl['total'].notna().mean():.1%}")
    print(f"  bloques fechados por el texto: {(bl['fechado_por'] == 'texto').mean():.1%} (resto: por XML u orden)")
    print(f"  bloques confiables (todas las filas suman al Total y el Total cuadra): {bl['confiable'].mean():.1%}")
    print(f"  bloques cuyo Total coincide con el XML en >= 50% de las filas: {(bl['coincide_xml'] >= 0.5).mean():.1%}")
    print(f"  activo neto del ESF disponible (03c): {len(esf)} fondo-anio-columna")
    print("\ncolumnas por bloque:", bl["n_cols"].value_counts().sort_index().to_dict())
    print("\nchequeos (filas = bloque-columna o bloque-fila):")
    r_ = ch.groupby(["chequeo", "es_total"]).agg(n=("cuadra", "size"), cuadra_pdf=("cuadra", "mean"),
                                                  cuadra_xml=("cuadra_xml", lambda s: s.dropna().astype(bool).mean()))
    print(r_.assign(cuadra_pdf=lambda d: (d.cuadra_pdf * 100).round(1),
                    cuadra_xml=lambda d: (d.cuadra_xml * 100).round(1)).to_string())
    print("\nno cuadran, clasificados:")
    print(pd.crosstab(nc["clase"], nc["chequeo"], margins=True).to_string())
    pe = nc[nc["clase"].str.startswith("probable_error")]
    print(f"\nprobable_error* ({len(pe)}), primeros 40:")
    for f in pe.sort_values(["clase", "chequeo", "rut", "anio"]).head(40).itertuples():
        print(f"  {f.rut} {f.anio} {f.columna:<8} {f.chequeo:<13} {f.col:<8} {f.clase[15:]:<6} dif={f.dif:>14,.0f} "
              f"distinto={f.distintos or '-'}  pag {f.pagina}  {f.detalle}")
    print("\nvalidacion con casos conocidos:")
    for rut, anio, esperado in casos_conocidos("03d"):
        x_ = ch[(ch["rut"] == rut) & (ch["anio"] == anio)]
        malos = x_[x_["clase"] != "cuadra"]
        resumen = ", ".join(f"{c}x{n}" for c, n in malos["clase"].value_counts().items())
        print(f"  {rut} {anio}: {len(x_)} chequeos, {len(malos)} no cuadran" + (f": {resumen}" if resumen else ""))
        print(f"      esperado: {esperado}")
    print(f"\nsalida: {DIR_PROC / 'ecp_chequeos.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())