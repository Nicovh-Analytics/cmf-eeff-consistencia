"""
03e - Comparativos PDF vs PDF: lo que un PDF informa para el año t (columna actual) contra
lo que el PDF del año t+1 informa para ese mismo año (columna anterior).

El 07 hace esto con el XML. Aqui se hace con el PDF, que es lo que lee el publico, y se cruza
con el XML de ambos años para saber que documento cambio:

  cuadra                    el PDF de t y el comparativo del PDF de t+1 dicen lo mismo
  pdf_corregido_despues     el PDF de t difiere de su XML; el comparativo de t+1 coincide con
                            el XML (de ambos años): el error del PDF de t se corrigio al año
                            siguiente, sin cambiar el XML
  pdf_error_comparativo     el PDF de t coincide con su XML; el comparativo del PDF de t+1 no
                            (el XML de t+1 si): error introducido al copiar el comparativo
  reexpresion               cada PDF coincide con su XML, pero el XML de t+1 cambio la cifra de t:
                            los dos documentos reexpresan (buscar nota)
  otro                      ninguna de las anteriores (PDF y XML distintos en ambos años, etc.)
  sin_xml                   falta el XML de alguna de las cuatro cifras
  lectura                   alguna de las dos lecturas del PDF es de OCR o se ubico solo por glosa

Lineas: los 6 subtotales del 03b (estructura_efe.csv) y las 6 lineas del 03c (lineas_03c.csv).
No lee PDF: usa lo que ya ubicaron el 03b y el 03c.

Lee:      estructura_efe.csv (03b), lineas_03c.csv (03c), encabezados.csv
Escribe:  data/procesado/comparativos_pdf.csv            todas las comparaciones
          data/procesado/comparativos_pdf_difieren.csv   las que no cuadran
"""
import sys

import pandas as pd

from config import CMF_HOME, casos_conocidos, umbral_materialidad

DIR_PROC = CMF_HOME / "procesado"
TOL = 1


def leer_lineas():
    """Tabla larga: rut, anio, linea, columna, pdf, xml, motivo de duda ("ocr", "solo_glosa" o "") y dudosa."""
    est = pd.read_csv(DIR_PROC / "estructura_efe.csv", dtype={"rut": str})
    est = est[est["ubicado"] == True]
    a = pd.DataFrame({"rut": est["rut"], "anio": est["anio"], "linea": est["subtotal"], "columna": est["columna"],
                      "pdf": est["subtotal_pdf"], "xml": est["subtotal_xml"], "pagina": est["pagina"],
                      "motivo": (est["pagina_ocr"].fillna(False).astype(bool).map({True: "ocr", False: ""})
                                 if "pagina_ocr" in est else "")})
    l = pd.read_csv(DIR_PROC / "lineas_03c.csv", dtype={"rut": str})
    b = pd.DataFrame({"rut": l["rut"], "anio": l["anio"], "linea": l["linea"], "columna": l["columna"],
                      "pdf": l["pdf"], "xml": l["xml"], "pagina": l["pagina"],
                      "motivo": [("ocr" if o else "solo_glosa" if m == "solo_glosa" else "")
                                 for o, m in zip(l["ocr"].fillna(False).astype(bool), l["metodo"])]})
    t = pd.concat([a, b], ignore_index=True).drop_duplicates(["rut", "anio", "linea", "columna"])
    t["dudosa"] = t["motivo"] != ""
    return t


def igual(a, b):
    return pd.notna(a) and pd.notna(b) and abs(abs(a) - abs(b)) <= TOL


ESF_2011 = {"total_activo", "total_pasivo", "activo_neto", "efectivo"}


def lectura_probable(pdf, xml):
    """El PDF difiere del XML con una huella de lectura nuestra (revision del 03d: 4 de 5):
    monto en 0 (columna o fila no leida) o el mismo numero con un digito de mas o de menos."""
    if pd.isna(pdf) or pd.isna(xml):
        return False
    if abs(pdf) <= TOL < abs(xml):
        return True
    a, b = str(abs(int(pdf))), str(abs(int(xml)))
    if abs(len(a) - len(b)) == 1:
        largo, corto = (a, b) if len(a) > len(b) else (b, a)
        return any(largo[:i] + largo[i + 1:] == corto for i in range(len(largo)))
    return False


VERSIONES = ["pdf_t", "xml_t", "pdf_t1", "xml_t1"]


def patron(r):
    """Cual de las 4 versiones del monto (PDF t, XML t, comparativo PDF t+1, comparativo XML t+1) no
    calza. Independiente de la lectura: la duda se lleva aparte (motivo_t / motivo_t1).
    Devuelve (patron, dif): dif = |version distinta| - |las otras| (0 si cuadra)."""
    v = [getattr(r, k) for k in VERSIONES]
    if any(pd.isna(x) for x in v):
        return "incompleto", float("nan")
    pt, xt, p1, x1 = v
    if igual(pt, xt) and igual(pt, p1) and igual(pt, x1):
        return "cuadra", 0.0
    for i, k in enumerate(VERSIONES):
        resto = [v[j] for j in range(4) if j != i]
        if igual(resto[0], resto[1]) and igual(resto[0], resto[2]):
            return "solo_" + k, abs(v[i]) - abs(resto[0])
    if igual(pt, xt) and igual(p1, x1):
        return "reexpresion", abs(p1) - abs(pt)
    if igual(pt, p1) and igual(xt, x1):
        return "criterio", abs(xt) - abs(pt)       # PDF y XML distintos, igual en los dos anios
    return "otro", abs(p1) - abs(pt)


def clasificar(r):
    if r.dudosa_t or r.dudosa_t1:
        return "lectura"
    if igual(r.pdf_t, r.pdf_t1):
        return "cuadra"
    if pd.isna(r.xml_t) or pd.isna(r.xml_t1):
        return "sin_xml"
    xml_igual = igual(r.xml_t, r.xml_t1)
    pdf_t_ok, pdf_t1_ok = igual(r.pdf_t, r.xml_t), igual(r.pdf_t1, r.xml_t1)
    if xml_igual and not pdf_t_ok and pdf_t1_ok:
        # 2011: el ESF trae la columna del balance de apertura y algunas plantillas no se reconocen
        # (limitacion del lector espacial): la diferencia del PDF 2011 puede ser nuestra
        if lectura_probable(r.pdf_t, r.xml_t) or (r.anio == 2011 and r.linea in ESF_2011):
            return "lectura"
        return "pdf_corregido_despues"
    if xml_igual and pdf_t_ok and not pdf_t1_ok:
        if lectura_probable(r.pdf_t1, r.xml_t1):
            return "lectura"
        return "pdf_error_comparativo"
    if not xml_igual and pdf_t_ok and pdf_t1_ok:
        return "reexpresion"
    return "otro"


def main():
    t = leer_lineas()
    act = t[t["columna"] == "actual"].drop(columns="columna")
    ant = t[t["columna"] == "anterior"].drop(columns="columna").assign(anio=lambda d: d["anio"] - 1)
    c = act.merge(ant, on=["rut", "anio", "linea"], suffixes=("_t", "_t1"))
    enc = pd.read_csv(DIR_PROC / "encabezados.csv", dtype={"rut": str})
    enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "moneda", "nombre_agf"]]
    c = c.merge(enc, on=["rut", "anio"], how="left")
    c["dif"] = c["pdf_t1"].abs() - c["pdf_t"].abs()
    c["clase"] = [clasificar(r) for r in c.itertuples()]
    c["patron"], c["dif_patron"] = zip(*[patron(r) for r in c.itertuples()])
    inm = (c["clase"] != "cuadra") & (c["clase"] != "lectura") & \
          (c["dif"].abs() <= c["moneda"].map(umbral_materialidad))
    c.loc[inm, "clase"] = "observacion_inmaterial"
    c = c.rename(columns={"anio": "anio_t"})
    c.to_csv(DIR_PROC / "comparativos_pdf.csv", index=False, encoding="utf-8-sig")
    nc = c[~c["clase"].isin(["cuadra"])]
    nc.to_csv(DIR_PROC / "comparativos_pdf_difieren.csv", index=False, encoding="utf-8-sig")

    print(f"pares (linea, anio t con PDF t y PDF t+1): {len(c)}  "
          f"({c[['rut', 'anio_t']].drop_duplicates().shape[0]} fondo-anio)")
    print("\nclase x linea:")
    print(pd.crosstab(c["linea"], c["clase"], margins=True).to_string())
    for clase in ("pdf_corregido_despues", "pdf_error_comparativo", "reexpresion", "otro"):
        x = c[c["clase"] == clase].sort_values(["rut", "anio_t"])
        if not len(x):
            continue
        print(f"\n{clase} ({len(x)}; {x[['rut', 'anio_t']].drop_duplicates().shape[0]} fondo-anio), primeros 25:")
        for r in x.head(25).itertuples():
            print(f"  {r.rut:>6} {r.anio_t}->{r.anio_t + 1}  {r.linea:<22} PDF {r.pdf_t:>16,.0f} -> {r.pdf_t1:>16,.0f}"
                  f"   XML {r.xml_t if pd.notna(r.xml_t) else float('nan'):>16,.0f} -> "
                  f"{r.xml_t1 if pd.notna(r.xml_t1) else float('nan'):>16,.0f}")

    print("\nvalidacion con casos conocidos:")
    for rut, anio, esperado in casos_conocidos("03e"):
        x = c[(c["rut"] == rut) & (c["anio_t"] == anio) & (c["clase"] != "cuadra")]
        print(f"  {rut} {anio}->{anio + 1}: " + (", ".join(f"{r.linea}:{r.clase}" for r in x.itertuples()) or
                                                 "todo cuadra"))
        print(f"      esperado: {esperado}")
    print(f"\nsalida: {DIR_PROC / 'comparativos_pdf.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
