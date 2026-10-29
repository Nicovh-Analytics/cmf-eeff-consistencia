"""Revision manual asistida de una planilla de casos del 03b o del 03c.

Uso (desde la raiz del repo):
    python run.py --revisar verificacion/muestra_03b_esf_eri.xlsx     (si lo agregas a run.py)
    PYTHONPATH=. python herramientas/revisar.py verificacion/muestra_03b_esf_eri.xlsx
    PYTHONPATH=. python herramientas/revisar.py verificacion/muestra_03b_esf_eri.xlsx --todos

Por cada fila sin veredicto:
  1. abre el PDF del caso en la pagina del subtotal (Edge, que respeta #page=N);
     en planillas del 03c (columna "identidad"), una pestana por cada pagina involucrada;
  2. muestra lo que leyo el 03b (subtotal impreso, suma de lineas, XML y detalle) o,
     en el 03c, cada termino de la identidad en PDF y XML lado a lado;
  3. pide el veredicto con una tecla y una nota opcional.
Guarda la planilla despues de CADA respuesta: se puede cortar con q y retomar.
Solo escribe las columnas veredicto / doc_con_error / nota de la planilla.
"""
import os
import re
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
    enc = pd.read_csv(CMF_HOME / "procesado" / "encabezados.csv", dtype={"rut": str},
                      usecols=["rut", "anio", "archivo", "es_ultimo_envio"])
    xmls = {(r.rut, int(r.anio)): r.archivo for r in enc[enc["es_ultimo_envio"]].itertuples()}

    # XML: solo las cuentas sin serie de los fondos de la planilla (se lee una vez)
    modo_03c = "identidad" in df.columns or "chequeo" in df.columns   # 03c/03d: PDF y XML por termino
    modo_03d = "chequeo" in df.columns
    subtotales, xml = {}, {}
    # 03d: cifras por serie del XML, para los casos de serie (el 03d no empareja nombres de series)
    ECP = {"inicio": "ActivoNetoAtribuibleALosParticipesAl01DeEnero", "aportes": "AportesDeCuotas",
           "rescates": "RescateDeCuotas", "neto": "AumentoNetoOriginadoPorTransaccionesDeCuotas",
           "res_antes": "AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionAntesDeDistribucionDeBeneficios",
           "res_despues": "AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionDespuesDeDistribucionDeBeneficios",
           "cierre": "ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuota"}
    xml_serie = {}
    if modo_03d:
        cs = pd.read_csv(CMF_HOME / "procesado" / "cuentas.csv", dtype={"rut": str, "serie": str},
                         usecols=["rut", "anio", "contexto", "codigo", "serie", "valor"])
        cs = cs[cs["serie"].notna() & cs["rut"].isin(set(df["rut"]))
                & cs["codigo"].isin({c + "PorSerie" for c in ECP.values()})]
        for r_ in cs.itertuples():
            xml_serie.setdefault((r_.rut, int(r_.anio), r_.contexto, r_.codigo), []).append((r_.serie, r_.valor))
    if not modo_03c:
        subtotales = cargar_subtotales()
        cta = pd.read_csv(CMF_HOME / "procesado" / "cuentas.csv", dtype={"rut": str, "serie": str},
                          usecols=["rut", "anio", "contexto", "codigo", "serie", "valor"])
        cta = cta[cta["serie"].isna() & cta["rut"].isin(set(df["rut"]))]
        xml = {(r.rut, int(r.anio), r.contexto, r.codigo): r.valor for r in cta.itertuples()}

    def terminos(texto):
        """'total_activo=123 | activo_neto=45.0' -> {'total_activo': 123.0, ...}"""
        out = {}
        for t in str(texto).split(" | "):
            if "=" in t:
                k, v = t.rsplit("=", 1)
                out[k.strip()] = float(v) if v.strip() not in ("", "None", "nan") else None
        return out

    def mostrar_series(r):
        """Valores por serie del XML para la fila del caso, marcando el impreso y el esperado."""
        det = str(r.get("detalle", ""))
        m = re.search(r"celda (\w+)/serie_\d+: impreso (-?[\d,]+), cuadraria con (-?[\d,]+)", det)
        fila = m.group(1) if m else next(iter(terminos(r.get("pdf"))), None)
        if fila not in ECP:
            return
        imp, esp = (float(m.group(i).replace(",", "")) for i in (2, 3)) if m else (None, None)
        ctx = "PeriodoActual" if r["columna"] == "actual" else "PeriodoAnterior"
        vals = xml_serie.get((r["rut"], int(r["anio"]), ctx, ECP[fila] + "PorSerie"), [])
        print(f"   XML por serie, fila '{fila}' ({ctx}):" + ("" if vals else " (sin datos por serie)"))
        for serie, v in vals:
            marca = ("  <- igual al impreso" if imp is not None and abs(abs(v) - abs(imp)) <= 2 else
                     "  <- igual al que cuadraria" if esp is not None and abs(abs(v) - abs(esp)) <= 2 else "")
            print(f"      {serie:<20} {monto(v):>16}{marca}")

    def mostrar_03c(r):
        distintos = set(str(r.get("terminos_distintos_xml", r.get("distintos", ""))).split(","))
        print(f"  dif PDF {monto(r.get('dif_pdf', r.get('dif')))} | dif XML {monto(r.get('dif_xml'))}"
              f"   (cuadra_pdf={r.get('cuadra_pdf', r.get('cuadra'))}, cuadra_xml={r.get('cuadra_xml')})")
        print(f"     {'termino':<22} {'PDF':>16} {'XML':>16}")
        tp, tx = terminos(r.get("pdf")), terminos(r.get("xml"))
        for k in tp:
            marca = "  <- distinto" if k in distintos else ""
            print(f"     {k:<22} {monto(tp[k]):>16} {monto(tx.get(k)):>16}{marca}")

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

    def ruta_xml(rut, anio):
        nombre = xmls.get((rut, anio))
        return CMF_HOME / "archivos" / rut / str(anio) / nombre if nombre else None

    def ruta_pdf(rut, anio):
        nombre = pdfs.get((rut, anio))
        return CMF_HOME / "archivos" / rut / str(anio) / nombre if nombre else None

    todos = "--todos" in sys.argv
    casos = list(df.index) if todos else list(df.index[df["veredicto"].str.strip() == ""])
    print(f"{len(casos)} casos {'(todos)' if todos else 'pendientes'} de {len(df)}.\n  Teclas: "
          + ", ".join(f"{k}={v}" for k, v in VEREDICTOS.items())
          + "\n  v=ver XML del envio, a=PDF anio anterior, f=PDF anio siguiente, b=volver al caso anterior,"
            " s=saltar, q=guardar y salir")

    pos = 0
    while 0 <= pos < len(casos):
        i = casos[pos]
        r = df.loc[i]
        anio = int(r["anio"])
        if modo_03c:
            que = r["identidad"] if "identidad" in r else f"ECP {r['chequeo']} / {r['col']}"
            print(f"\n[{pos + 1}/{len(casos)}] {r['rut']} {anio}  {que} ({r['columna']})"
                  f"  pag. {r.get('paginas', r.get('pagina', '?'))}  [{r.get('estrato', '')} {r.get('clase', '')}]")
            if str(r.get("detalle", "")).strip() not in ("", "nan"):
                print(f"  detalle: {r['detalle']}")
            mostrar_03c(r)
            if modo_03d and (r["col"] != "total" or r["chequeo"] == "suma_series"):
                mostrar_series(r)
        else:
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
        if not pdf:
            print("  (sin PDF en cruce_resumen)")
        elif modo_03c:
            for p in str(r.get("paginas", r.get("pagina", ""))).split(","):     # ESF y EFE pueden estar en paginas distintas
                abrir_pdf(pdf, int(p) if p.strip().isdigit() else None)
        else:
            abrir_pdf(pdf, r.get("pagina"))

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
            if k == "v":
                rx = ruta_xml(r["rut"], anio)
                abrir_pdf(rx) if rx else print("  (sin XML en encabezados)")   # Edge muestra el XML como arbol
                if rx:
                    print("  (en el XML: Ctrl+F con el codigo; PeriodoActual/PeriodoAnterior indican la columna)")
                continue
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