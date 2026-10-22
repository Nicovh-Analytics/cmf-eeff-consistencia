"""Revision manual asistida de una planilla de casos del 03b.

Uso (desde la raiz del repo):
    python run.py --revisar verificacion/muestra_03b_esf_eri.xlsx     (si lo agregas a run.py)
    PYTHONPATH=. python herramientas/revisar.py verificacion/muestra_03b_esf_eri.xlsx
    PYTHONPATH=. python herramientas/revisar.py verificacion/muestra_03b_esf_eri.xlsx --todos

Por cada fila sin veredicto:
  1. abre el PDF del caso en la pagina del subtotal (Edge, que respeta #page=N);
  2. muestra lo que leyo el 03b: subtotal impreso, suma de lineas, XML y detalle;
  3. pide el veredicto con una tecla y una nota opcional.
Guarda la planilla despues de CADA respuesta: se puede cortar con q y retomar.
Solo escribe las columnas veredicto / doc_con_error / nota de la planilla.
"""
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from config import CMF_HOME

VEREDICTOS = {"e": "error_pdf", "x": "error_xml", "l": "lectura", "o": "otro",
              "1": "error_pdf", "2": "error_xml", "3": "lectura", "4": "otro"}
DOC = {"e": "PDF", "x": "XML", "1": "PDF", "2": "XML"}


def cargar_subtotales():
    """Configuracion de subtotales del 03b (codigo XML y partes), para mostrar el XML."""
    import importlib
    try:
        return importlib.import_module("validaciones.estructura.03b_estructura").SUBTOTALES
    except Exception as e:                      # la revision sigue sin el bloque XML
        print(f"(sin detalle XML: no se pudo leer la configuracion del 03b: {e})")
        return {}


def monto(v):
    return "-" if pd.isna(v) else f"{v:,.0f}".replace(",", ".")


def abrir_pdf(ruta, pagina=None):
    """Abre el PDF en Edge en la pagina indicada; si falla, con el visor por defecto."""
    if not ruta.exists():
        print(f"  (no existe {ruta})")
        return
    url = ruta.resolve().as_uri() + (f"#page={int(pagina)}" if pd.notna(pagina) else "")
    try:
        subprocess.Popen(["cmd", "/c", "start", "", "msedge", url])
    except OSError:
        os.startfile(ruta)              # sin pagina, pero al menos abre


def guardar(df, planilla):
    while True:
        try:
            df.to_excel(planilla, index=False)
            return
        except PermissionError:
            input(f"  {planilla.name} esta abierto en Excel: cierralo y presiona Enter ")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    planilla = Path(sys.argv[1])
    df = pd.read_excel(planilla, dtype={"rut": str})
    for c in ("veredicto", "doc_con_error", "nota"):
        df[c] = df[c].fillna("").astype(str) if c in df else ""

    res = pd.read_csv(CMF_HOME / "procesado" / "cruce_resumen.csv",
                      dtype={"rut": str}, usecols=["rut", "anio", "pdf"])
    pdfs = {(r.rut, int(r.anio)): r.pdf for r in res.itertuples() if isinstance(r.pdf, str)}

    # XML: solo las cuentas sin serie de los fondos de la planilla (se lee una vez)
    subtotales = cargar_subtotales()
    cta = pd.read_csv(CMF_HOME / "procesado" / "cuentas.csv", dtype={"rut": str, "serie": str},
                      usecols=["rut", "anio", "contexto", "codigo", "serie", "valor"])
    cta = cta[cta["serie"].isna() & cta["rut"].isin(set(df["rut"]))]
    xml = {(r.rut, int(r.anio), r.contexto, r.codigo): r.valor for r in cta.itertuples()}

    def mostrar_xml(rut, anio, subtotal, columna):
        cfg = subtotales.get(subtotal)
        if not cfg:
            return
        ctx = "PeriodoActual" if columna == "actual" else "PeriodoAnterior"
        print(f"   XML ({ctx}):")
        for c in cfg["partes"]:
            v = xml.get((rut, anio, ctx, c))
            if v:                                # solo partidas con monto
                print(f"      {c[:45]:<45} {monto(v):>16}")
        print(f"      {'= ' + cfg['codigo'][:43]:<45} {monto(xml.get((rut, anio, ctx, cfg['codigo']))):>16}")

    def ruta_pdf(rut, anio):
        nombre = pdfs.get((rut, anio))
        return CMF_HOME / "archivos" / rut / str(anio) / nombre if nombre else None

    todos = "--todos" in sys.argv
    casos = list(df.index) if todos else list(df.index[df["veredicto"].str.strip() == ""])
    print(f"{len(casos)} casos {'(todos)' if todos else 'pendientes'} de {len(df)}.\n  Teclas: "
          + ", ".join(f"{k}={v}" for k, v in VEREDICTOS.items())
          + "\n  a=PDF anio anterior, f=PDF anio siguiente, b=volver al caso anterior,"
            " s=saltar, q=guardar y salir")

    pos = 0
    while 0 <= pos < len(casos):
        i = casos[pos]
        r = df.loc[i]
        anio = int(r["anio"])
        print(f"\n[{pos + 1}/{len(casos)}] {r['rut']} {anio}  {r.get('subtotal', '')} ({r.get('columna', '')})"
              f"  pag. {r.get('pagina', '?')}  [{r.get('clase', '')}, {r.get('patron', '')}]")
        print(f"  impreso {monto(r.get('subtotal_pdf'))} | suma lineas {monto(r.get('suma_lineas_pdf'))}"
              f" | XML {monto(r.get('subtotal_xml'))} | dif {monto(r.get('dif'))}")
        print("   PDF (lineas sumadas):")
        for linea in str(r.get("detalle", "")).split(" | "):
            print("     ", linea)
        mostrar_xml(r["rut"], anio, r.get("subtotal"), r.get("columna"))
        if r["veredicto"].strip():
            print(f"  ya revisado: {r['veredicto']}  |  nota: {r['nota'] or '-'}")

        pdf = ruta_pdf(r["rut"], anio)
        abrir_pdf(pdf, r.get("pagina")) if pdf else print("  (sin PDF en cruce_resumen)")

        while True:
            k = input("  veredicto> ").strip().lower()
            if k == "q":
                guardar(df, planilla)
                print(f"guardado: {planilla}")
                return
            if k == "s":
                pos += 1
                break
            if k == "b":
                if pos == 0:
                    print("  (es el primer caso)")
                    continue
                pos -= 1
                break
            if k in ("a", "f"):
                otro = anio - 1 if k == "a" else anio + 1
                ruta = ruta_pdf(r["rut"], otro)
                abrir_pdf(ruta) if ruta else print(f"  (sin PDF de {otro})")
                continue
            if k in VEREDICTOS:
                df.at[i, "veredicto"] = VEREDICTOS[k]
                df.at[i, "doc_con_error"] = DOC.get(k, "")
                anterior = df.at[i, "nota"]
                nota = input(f"  nota (Enter = {'mantener la anterior' if anterior else 'sin nota'})> ").strip()
                df.at[i, "nota"] = nota or anterior
                guardar(df, planilla)
                pos += 1
                break
            print("  tecla no valida")

    print(f"\nlisto: {planilla}")


if __name__ == "__main__":
    main()