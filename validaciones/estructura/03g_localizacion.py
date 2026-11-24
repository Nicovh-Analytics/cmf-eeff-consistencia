"""
03g - Localizacion: cuando un subtotal del PDF no suma sus lineas, cual cifra es la mala.

Protocolo (footing -> cross-footing -> ancla), por fondo-anio-columna-subtotal con suma fallida:
  1. footing      d = subtotal impreso - suma de sus lineas (estructura_efe.csv del 03b)
  2. propagacion  el nivel superior, ¿cierra con el impreso o con la suma interna?
                    operacion/inversion/financiamiento -> aumento neto (03b)
                    aumento neto -> evolucion del efectivo (03b)
                    evolucion del efectivo -> efectivo del ESF (identidades 03c)
                    total activo/pasivo -> activo - pasivo = activo neto (03c)
                    total ingresos/gastos -> ingresos - gastos = utilidad (03c)
                  cierra con la suma interna -> el subtotal impreso es el malo   (error_subtotal)
                  cierra con el impreso      -> una linea es la mala             (error_linea)
                  ninguno                    -> revisar (doble falla)
  3. ancla        EFE: la evolucion del efectivo suma y su saldo final = efectivo del ESF (ok / falla)
  4. firmas, antes que el error del emisor:
                  redondeo         |d| <= tolerancia de la moneda
                  signo_subtotal   impreso = -(suma de lineas): el 03b compara en valor absoluto
                  lectura_ocr      el 03b ya lo marco como lectura de una pagina OCR
                  arrastre         un hijo con la misma diferencia ya no suma (el error es del hijo)
                  fila_desplazada  el subtotal impreso es igual a otro renglon de la pagina
                  inversion_signo  una linea v con 2|v| = |d|
                  omision_lectura  hay un renglon de monto |d| en la pagina que no entro a la suma
                  (fila / inversion / omision solo con montos >= 100: debajo, coincidencias casuales)
Marcas: dudosa (alguna linea leida con ? o #), un_digito (impreso y suma difieren en un digito),
repite_t1 (el mismo impreso en el PDF de t y en el comparativo del PDF de t+1: lo escribio el
emisor, no es lectura), xml_sigue (el XML trae el impreso, la suma interna u otro).

No cambia casos: el 04c agrega la localizacion a cada caso como evidencia.
Validacion contra las muestras de precision: verificacion/ (privado).

Lee:      estructura_efe.csv, estructura_efe_no_suma.csv, renglones_pdf.csv (03b), identidades.csv (03c)
Escribe:  data/procesado/localizacion.csv
"""
import re

import pandas as pd

from config import CMF_HOME

P = CMF_HOME / "procesado"
TOL = 1.0
MIN_FIRMA = 100.0       # firmas por igualdad de montos: bajo esto las coincidencias son casuales
TOL_REDONDEO = {"$$": 2.0}           # miles de pesos ($$); PROM (dolares) 1 -> en dolares 2 ya es material
ESTADO = {"operacion": "EFE", "inversion": "EFE", "financiamiento": "EFE", "aumento_neto": "EFE",
          "evolucion_efectivo": "EFE", "total_activo": "ESF", "total_pasivo": "ESF",
          "total_ingresos": "ERI", "total_gastos": "ERI"}
PADRE_03B = {"operacion": "aumento_neto", "inversion": "aumento_neto", "financiamiento": "aumento_neto",
             "aumento_neto": "evolucion_efectivo"}
PADRE_03C = {"evolucion_efectivo": "efectivo_esf_efe", "total_activo": "activo_menos_pasivo",
             "total_pasivo": "activo_menos_pasivo", "total_ingresos": "ingresos_menos_gastos",
             "total_gastos": "ingresos_menos_gastos"}
HIJOS = {"aumento_neto": ["operacion", "inversion", "financiamiento"], "evolucion_efectivo": ["aumento_neto"]}
RE_DET = re.compile(r"=(-?\d+(?:\.\d+)?)([?#]?)")


def cerca(a, b, tol=TOL):
    return pd.notna(a) and pd.notna(b) and abs(a - b) <= tol


def un_digito(a, b):
    """Impreso y suma difieren en un solo digito (mismo largo): tipeo del emisor o lectura de un caracter."""
    if pd.isna(a) or pd.isna(b):
        return False
    x, y = str(abs(int(round(a)))), str(abs(int(round(b))))
    return len(x) == len(y) and sum(i != j for i, j in zip(x, y)) == 1


def cierre(dp, d):
    """Como cierra el padre: con el impreso (dp ~ 0) o con la suma interna (|dp| ~ |d|)."""
    if pd.isna(dp):
        return "sin_padre"
    if abs(dp) <= TOL:
        return "impreso"
    if abs(abs(dp) - abs(d)) <= TOL:
        return "interno"
    return "ninguno"


def main():
    ee = pd.read_csv(P / "estructura_efe.csv", dtype={"rut": str}, low_memory=False)
    ee = ee[ee["subtotal"].isin(ESTADO) & ee["subtotal_pdf"].notna() & ee["suma_lineas_pdf"].notna()]
    ee = ee.drop_duplicates(["rut", "anio", "columna", "subtotal"])
    ee["d"] = ee["subtotal_pdf"] - ee["suma_lineas_pdf"]
    E = ee.set_index(["rut", "anio", "columna", "subtotal"])

    idn = pd.read_csv(P / "identidades.csv", dtype={"rut": str}, low_memory=False,
                      usecols=["rut", "anio", "identidad", "columna", "dif_pdf", "cuadra_pdf"])
    I = idn.drop_duplicates(["rut", "anio", "columna", "identidad"]).set_index(["rut", "anio", "columna", "identidad"])

    fallan = ee[ee["d"].abs() > TOL]
    claves = set(zip(fallan["rut"], fallan["anio"]))
    rg = pd.read_csv(P / "renglones_pdf.csv", dtype={"rut": str}, usecols=["rut", "anio", "pagina", "glosa", "actual", "anterior"])
    rg = rg[[k in claves for k in zip(rg["rut"], rg["anio"])]]
    R = {k: g for k, g in rg.groupby(["rut", "anio", "pagina"])}
    ns = pd.read_csv(P / "estructura_efe_no_suma.csv", dtype={"rut": str}, usecols=["rut", "anio", "subtotal", "columna", "clase"])
    C03B = {(a, b, c, e): f for a, b, c, e, f in ns.drop_duplicates(["rut", "anio", "subtotal", "columna"]).itertuples(index=False)}

    filas = []
    for r in fallan.itertuples():
        k = (r.rut, r.anio, r.columna)
        d, sub = r.d, r.subtotal
        tol_r = TOL_REDONDEO.get(str(r.moneda).upper(), TOL)

        # 2. propagacion
        if sub in PADRE_03B:
            p = E.loc[k + (PADRE_03B[sub],)] if k + (PADRE_03B[sub],) in E.index else None
            dp = p["d"] if p is not None else float("nan")
        else:
            p = I.loc[k + (PADRE_03C[sub],)] if k + (PADRE_03C[sub],) in I.index else None
            dp = p["dif_pdf"] if p is not None else float("nan")
        cie = cierre(dp, d)

        # 3. ancla del EFE
        ancla = "na"
        if ESTADO[sub] == "EFE":
            ev = E.loc[k + ("evolucion_efectivo",)] if k + ("evolucion_efectivo",) in E.index else None
            es = I.loc[k + ("efectivo_esf_efe",)] if k + ("efectivo_esf_efe",) in I.index else None
            if ev is not None and es is not None:
                ancla = "ok" if abs(ev["d"]) <= TOL and bool(es["cuadra_pdf"]) else "falla"

        # 4. firmas
        det = RE_DET.findall(str(r.detalle))
        vals = [float(v) for v, _ in det]
        dudosa = any(m for _, m in det)
        pag = R.get((r.rut, r.anio, r.pagina))
        col = pag[r.columna].dropna() if pag is not None and r.columna in pag else pd.Series(dtype=float)
        grande = abs(d) >= MIN_FIRMA
        n_igual = int((col == r.subtotal_pdf).sum()) if abs(r.subtotal_pdf) >= MIN_FIRMA else 0   # exacto
        omis = grande and any(cerca(abs(v), abs(d)) for v in col if not any(cerca(v, u) for u in vals) and not cerca(v, r.subtotal_pdf))
        inv = grande and any(cerca(2 * abs(v), abs(d)) for v in vals)
        arr = next((h for h in HIJOS.get(sub, []) if k + (h,) in E.index and abs(E.loc[k + (h,)]["d"]) > TOL
                    and cerca(abs(E.loc[k + (h,)]["d"]), abs(d))), None)

        c03b = C03B.get((r.rut, r.anio, sub, r.columna), "")
        dig = un_digito(r.subtotal_pdf, r.suma_lineas_pdf)
        if abs(d) <= tol_r:
            loc = "redondeo"
        elif cerca(r.subtotal_pdf, -r.suma_lineas_pdf):
            loc = "signo_subtotal"           # el 03b compara en valor absoluto: presentacion del signo, no cifra
        elif c03b == "probable_lectura_ocr":
            loc = "lectura_ocr"
        elif arr:
            loc = f"arrastre_{arr}"
        elif n_igual >= 2:
            loc = "fila_desplazada"
        elif inv:
            loc = "inversion_signo"
        elif cie == "interno":
            loc = "error_subtotal"
        elif cie == "impreso":
            loc = "omision_lectura" if omis else "error_linea"      # dudosa queda como marca, no localiza
        else:
            loc = "revisar"
        xml = ("interno" if cerca(r.subtotal_xml, r.suma_lineas_pdf) else
               "impreso" if cerca(r.subtotal_xml, r.subtotal_pdf) else "otro")
        filas.append(dict(rut=r.rut, anio=r.anio, columna=r.columna, estado=ESTADO[sub], subtotal=sub,
                          pagina=r.pagina, moneda=r.moneda, impreso=r.subtotal_pdf, suma_lineas=r.suma_lineas_pdf,
                          d=d, xml=r.subtotal_xml, cierra=cie, dif_padre=dp, ancla=ancla, xml_sigue=xml,
                          localizacion=loc, dudosa=dudosa, un_digito=dig, clase_03b=c03b))
    loc = pd.DataFrame(filas)
    # repite_t1: el mismo impreso en el PDF de t (actual) y en el comparativo del PDF de t+1 (anterior):
    # dos archivos distintos con la misma cifra -> la escribio el emisor, no es lectura
    a = loc[loc["columna"] == "actual"][["rut", "anio", "subtotal", "impreso"]]
    b = loc[loc["columna"] == "anterior"][["rut", "anio", "subtotal", "impreso"]].assign(anio=lambda x: x["anio"] - 1)
    rep = set(map(tuple, a.merge(b, on=["rut", "anio", "subtotal", "impreso"]).values))
    loc["repite_t1"] = [(r, an if c == "actual" else an - 1, s, i) in rep
                        for r, an, c, s, i in zip(loc["rut"], loc["anio"], loc["columna"], loc["subtotal"], loc["impreso"])]
    loc.to_csv(P / "localizacion.csv", index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 220)
    print(f"subtotales que no suman en el PDF: {len(loc)} en {loc[['rut', 'anio']].drop_duplicates().shape[0]} fondo-anio\n")
    print(pd.crosstab(loc["localizacion"], loc["estado"], margins=True).to_string(), "\n")
    print("cierre x ancla:")
    print(pd.crosstab(loc["cierra"], loc["ancla"], margins=True).to_string(), "\n")

    print("repite en t y t+1 (evidencia de emisor) por localizacion:")
    print(loc.groupby("localizacion")["repite_t1"].sum().to_string(), "\n")
    cand = loc[loc["un_digito"] & (loc["localizacion"] == "error_subtotal")]
    print(f"un digito distinto en PDF de texto con la cadena cerrando con la suma interna: {len(cand)} "
          "(tipeo del emisor si el PDF lo muestra asi)")
    print(cand[["rut", "anio", "columna", "subtotal", "pagina", "impreso", "suma_lineas", "xml", "ancla", "clase_03b", "repite_t1"]]
          .to_string(index=False), "\n")

    print(f"\n-> {P / 'localizacion.csv'}")


if __name__ == "__main__":
    main()
