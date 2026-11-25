"""
Medicion (no cambia nada): ¿las reglas del catalogo evaluadas sobre los hechos del PDF reproducen lo que
hoy dicen el 03b (subtotales) y el 03c (identidades entre estados)?

El 03b suma por POSICION (los renglones sobre el subtotal hasta un corte); el motor suma por CODIGO (los
renglones a los que el emparejador asigno codigo). Donde no coinciden se ve por que: una linea con cifra
sin codigo, un codigo asignado a otro renglon, el total leido de otra fila. Eso dice si el motor puede
reemplazar al 03b y al 03c, y que falta en el emparejador.

    cuadra (03b/03c)   lo que dice hoy la etapa
    cuadra (motor)     |abs(total) - abs(suma de partes)| <= TOL  (el PDF imprime signos de presentacion)
    total igual        el motor tomo el mismo subtotal impreso que el 03b (+-TOL)

Uso:
    PYTHONPATH=. python herramientas/medir_motor_pdf.py
-> data/procesado/medicion_motor_pdf.csv (una fila por regla-documento-columna comparada)
"""
import sys

import pandas as pd

import catalogo
from config import CMF_HOME
from motor import hechos, reglas

P = CMF_HOME / "procesado"
TOL = 2
CTX = {"actual": "PeriodoActual", "anterior": "PeriodoAnterior"}


def motor_pdf(r_cat: pd.DataFrame) -> pd.DataFrame:
    """Motor sobre el PDF con el signo impreso y con el signo oficial en las partes; cuadra = con
    cualquiera de los dos (el signo de presentacion no es un error de cifra)."""
    ident = {n: (t, catalogo.terminos(p)) for n, t, p in zip(r_cat["nombre"], r_cat["total"], r_cat["partes"])}
    h = hechos.pdf()
    a = reglas.por_columna(h, identidades=ident).reset_index()
    b = reglas.por_columna(h, identidades=ident, signo_oficial=True).reset_index()
    m = a.merge(b[["archivo", "contexto", "identidad", "suma_partes"]].rename(columns={"suma_partes": "suma_signo"}),
                on=["archivo", "contexto", "identidad"])
    cuadra = lambda t, s: (t.abs() - s.abs()).abs() <= TOL
    m["cuadra_impreso"] = cuadra(m["total"], m["suma_partes"])
    m["cuadra_motor"] = m["cuadra_impreso"] | cuadra(m["total"], m["suma_signo"])
    return m.rename(columns={"total": "total_motor", "suma_partes": "suma_motor"})


def causa(r) -> str:
    """Por que el motor no cuadra donde la etapa si (o al reves)."""
    t, s, s2 = abs(r["total_motor"]), abs(r["suma_motor"]), abs(r["suma_signo"])
    if r["cuadra_motor"] and not r["cuadra_impreso"]:
        return "signo de presentacion (cuadra con el signo oficial)"
    if r["cuadra_motor"]:
        return "motor cuadra, la etapa no"
    if t and abs(s - 2 * t) <= TOL:
        return "suma = 2 x total (un subtotal o el total quedo como parte)"
    if not s:
        return "partes sin codigo (suma 0)"
    return "otro (codigo en otra linea o linea sin codigo)"


def main():
    cat = catalogo.reglas()
    pd.set_option("display.width", 220)

    # --- 03b: subtotales -----------------------------------------------------------------------------
    r3b = cat[(cat["clave_03b"] != "") & (cat["activa"] == "si")]
    m = motor_pdf(r3b).merge(r3b[["nombre", "clave_03b"]].rename(columns={"nombre": "identidad"}))
    e = pd.read_csv(P / "estructura_efe.csv", dtype={"rut": str}, low_memory=False,
                    usecols=["rut", "anio", "subtotal", "columna", "ubicado", "subtotal_pdf", "suma_lineas_pdf", "pdf_suma"])
    e = e[e["ubicado"] == True].drop_duplicates(["rut", "anio", "subtotal", "columna"])
    e = e.assign(archivo=e["rut"] + "_" + e["anio"].astype(str), contexto=e["columna"].map(CTX))
    b = e.merge(m, left_on=["archivo", "contexto", "subtotal"], right_on=["archivo", "contexto", "clave_03b"],
                how="left")
    b["evaluado_motor"] = b["total_motor"].notna()
    b["total_igual"] = (b["total_motor"].abs() - b["subtotal_pdf"].abs()).abs() <= TOL
    b["cuadra_03b"] = b["pdf_suma"] == True
    print(f"03b: {len(b)} subtotales ubicados; el motor evalua {b['evaluado_motor'].mean():.1%} "
          f"(el resto: el total del subtotal no tiene codigo en los renglones)\n")
    ev = b[b["evaluado_motor"]]
    print("por subtotal (evaluados por el motor):")
    print(ev.groupby("subtotal").agg(n=("cuadra_03b", "size"), total_igual=("total_igual", "mean"),
                                     cuadra_03b=("cuadra_03b", "mean"), cuadra_motor=("cuadra_motor", "mean"))
          .round(3).to_string(), "\n")
    print("cuadra 03b x cuadra motor:")
    print(pd.crosstab(ev["cuadra_03b"], ev["cuadra_motor"], margins=True).to_string(), "\n")
    desac = ev[ev["cuadra_03b"] != ev["cuadra_motor"]].copy()
    print("causa de los desacuerdos:")
    print(desac.apply(causa, axis=1).value_counts().to_string(), "\n")
    print("desacuerdos (muestra):")
    print(desac[["rut", "anio", "subtotal", "columna", "subtotal_pdf", "suma_lineas_pdf", "total_motor", "suma_motor",
                 "cuadra_03b", "cuadra_motor"]].head(20).to_string(index=False), "\n")

    # --- 03c: identidades entre estados --------------------------------------------------------------
    r3c = cat[(cat["clave_03c"] != "") & (cat["activa"] == "si")]
    m3c = motor_pdf(r3c).merge(r3c[["nombre", "clave_03c"]].rename(columns={"nombre": "identidad"}))
    i3 = pd.read_csv(P / "identidades.csv", dtype={"rut": str}, low_memory=False,
                     usecols=["rut", "anio", "identidad", "columna", "cuadra_pdf", "dif_pdf"])
    i3 = i3[i3["cuadra_pdf"].notna()].drop_duplicates(["rut", "anio", "identidad", "columna"])
    i3 = i3.assign(archivo=i3["rut"] + "_" + i3["anio"].astype(str), contexto=i3["columna"].map(CTX))
    c = i3.merge(m3c.drop(columns="identidad"), left_on=["archivo", "contexto", "identidad"],
                 right_on=["archivo", "contexto", "clave_03c"], how="left")
    c["evaluado_motor"] = c["total_motor"].notna()
    c["cuadra_03c"] = c["cuadra_pdf"].astype(str).str.lower() == "true"
    print(f"03c: {len(c)} identidades evaluadas; el motor evalua {c['evaluado_motor'].mean():.1%}\n")
    evc = c[c["evaluado_motor"]]
    print(evc.groupby("identidad").apply(lambda g: pd.Series(dict(
        n=len(g), cuadra_03c=g["cuadra_03c"].mean(), cuadra_motor=g["cuadra_motor"].mean(),
        acuerdo=(g["cuadra_03c"] == g["cuadra_motor"]).mean())), include_groups=False).round(3).to_string(), "\n")
    print("03c con el signo impreso solamente (sin signo oficial):",
          f"{(evc['cuadra_03c'] == evc['cuadra_impreso']).mean():.3%} de acuerdo;",
          f"con signo oficial: {(evc['cuadra_03c'] == evc['cuadra_motor']).mean():.3%}")
    d3 = evc[evc["cuadra_03c"] != evc["cuadra_motor"]]
    if len(d3):
        print("causa de los desacuerdos 03c:")
        print(d3.apply(causa, axis=1).value_counts().to_string())
    print("desacuerdos 03c (muestra):")
    print(evc[evc["cuadra_03c"] != evc["cuadra_motor"]][["rut", "anio", "identidad", "columna", "dif_pdf",
          "total_motor", "suma_motor", "cuadra_03c", "cuadra_motor"]].head(15).to_string(index=False))

    out = pd.concat([b.assign(etapa="03b", regla=b["subtotal"]), c.assign(etapa="03c", regla=c["identidad"])])
    out.to_csv(P / "medicion_motor_pdf.csv", index=False, encoding="utf-8-sig")
    print(f"\n-> {P / 'medicion_motor_pdf.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
