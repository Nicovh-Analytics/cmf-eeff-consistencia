"""
Ficha de verificacion: XML -> Excel con forma de estado financiero
==================================================================

Genera, por fondo-anio, un Excel que se lee como el PDF, para comparar a
simple vista durante la verificacion manual:

  - una hoja por estado (ESF, ERI, ECP, EFE) con las cuentas en el orden
    del XML, nombres legibles y columnas Actual / Anterior;
  - el ECP con las series en columnas y el total al final (como el PDF);
  - formato de numero como el PDF: 1.234.567 / (1.234) / -;
  - por cada cifra: XML | PDF | Diferencia | Pagina. Si el cruce no
    encontro la cifra, se PROPONE el monto huerfano mas cercano del PDF;
  - en el periodo Anterior, ademas, el ORIGINAL: la cifra publicada en el
    XML del reporte del anio anterior, y su diferencia;
  - colores: rojo = no encontrado, naranja = signo distinto, amarillo =
    redondeo, morado = el comparativo difiere del original;
  - hoja Huerfanos: montos sin par del cruce en t y t+1, del PDF (con la glosa de su linea) y
    del XML (cuenta no encontrada en el PDF).

ESF, ERI y EFE en forma de estado, con el lector unificado (comun/lector.py + comun/emparejar.py):
  - lectura: estado de cada pagina por titulo (o por contenido si el titulo impreso es de otro
    estado), glosas partidas unidas, montos corridos corregidos solo con evidencia de lectura;
  - cada renglon se empareja con una cuenta del XML: glosario y glosa parecida; si no, valor;
  - bloque 1: coinciden por glosa, en el orden del estado (XML);
    bloque 2: coinciden solo por valor -> glosa del PDF al lado de la cuenta del XML;
    bloque 3: sin coincidencia (solo PDF / solo XML con valor);
  - Dif = |PDF| - |XML| con formula (el signo va en "Coincide"); columnas actual y anterior;
  - Verificacion (al final): por cada subtotal e identidad del estado, una fila que
    reescribe el valor impreso (referencia a su celda), otra con la SUMA en Excel de sus
    partes y otra con la diferencia, para PDF y XML por separado. Partes del PDF: las
    lineas entre el subtotal anterior y el suyo (orden de la pagina, como el 03b);
    partes del XML: los codigos del subtotal;
  - hoja Casos: casos del 04c del fondo-anio; las cuentas de un caso van marcadas.
Hojas t+1 y t-1: cada cifra de t (columna actual) frente a la misma cifra en el reporte de t+1
  (columna anterior); y cada cifra de t-1 que presenta t (columna anterior) frente al reporte de
  t-1 (columna actual). En PDF y en XML, para ESF, ERI, EFE y ECP por serie; y la continuidad cierre t =
  inicio t+1 (ECP por serie y efectivo del EFE). Las hojas "forma" evaluan dentro del mismo t.
  Veredicto por cifra entre las 4 versiones (PDF t, XML t, PDF t+1, XML t+1): 4 iguales -> ok;
  3 contra 1 -> error en la que discrepa; 2 contra 2 -> error en el grupo cuyo documento no cuadra
  internamente (subtotales e identidades en que participa la cifra), si el otro si; los dos de t
  contra los dos de t+1 -> cambia en t+1 (reexpresion o reclasificacion); si no, sin determinar
  (para la revision de notas).
ECP en forma de estado (si el 03d lo leyo): por columna, filas del ECP x series con PDF | XML |
  Dif. El PDF sale de ecp_chequeos (columnas serie_1, serie_2... del 03d), asociadas a la serie
  del XML por la mayor cantidad de valores iguales. Verificacion con formulas por serie:
  transacciones, evolucion, suma de series = total, continuidad (inicio actual = cierre anterior).
Sin lectura espacial (PDF sin cache del 03a) la hoja queda como antes (solo el cruce).

Uso:
  python 06_ficha.py <rut> <anio>          -> una ficha
  python 06_ficha.py --muestra             -> fichas de todos los casos de
                                              verificacion/muestra_verificacion.xlsx
  python 06_ficha.py --planilla <xlsx>     -> fichas de los rut/anio de una planilla de
                                              revision (columnas rut y anio)

Lee:      data/procesado/encabezados.csv, cuentas.csv, cruce_resumen.csv,
          cruce_detalle.csv, cruce_huerfanos.csv,
          ecp_chequeos.csv, casos_unicos.csv (si existe); cache de coordenadas del 03a
Escribe:  verificacion/fichas/{rut}_{anio}.xlsx  (regenerables: no versionar)

Cada cuenta se asigna a su estado recorriendo el XML en orden: los codigos
exclusivos de un estado fijan la seccion y los compartidos (p.ej. diferencias
de cambio sobre efectivo, en ERI y EFE) heredan la seccion vigente.
"""

import importlib
import re
import sys
from pathlib import Path
from comun.secciones import asignar_secciones
from comun.lector_espacial import cargar_coords, filas_espaciales
from comun.lector import leer_estados, paginas_de
from comun.emparejar import emparejar as emparejar_comun

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from config import CMF_HOME, RAIZ

M03B = importlib.import_module("validaciones.estructura.03b_estructura")
SUBTOTALES = M03B.SUBTOTALES

DIR_PROC = CMF_HOME / "procesado"
DIR_FICHAS = RAIZ / "verificacion" / "fichas"
MUESTRA = RAIZ / "verificacion" / "muestra_verificacion.xlsx"

FUENTE = Font(name="Arial", size=10)
FUENTE_B = Font(name="Arial", size=10, bold=True)
FMT_PDF = '#,##0;(#,##0);"-"'
COLORES = {
    "no_encontrado": PatternFill("solid", start_color="FFC7CE"),   # rojo
    "signo_distinto": PatternFill("solid", start_color="FFD8A8"),  # naranja
    "ok_redondeo": PatternFill("solid", start_color="FFF2A8"),     # amarillo
}
ESTADOS = ["ESF", "ERI", "ECP", "EFE"]
CONTEXTOS = {"PeriodoActual": "Actual", "PeriodoAnterior": "Anterior"}

def legible(codigo: str) -> str:
    """'VentaCobroDeActivosFinancieros' -> 'Venta cobro de activos financieros'."""
    palabras = re.findall(r"[A-Z][a-z0-9áéíóúñ]*|[a-z0-9]+|[A-Z]+(?![a-z])", codigo)
    texto = " ".join(palabras).lower()
    texto = re.sub(r"([a-z])(\d)", r"\1 \2", texto)          # "al01" -> "al 01"
    return texto[:1].upper() + texto[1:]


MAX_DIF_PROPUESTA = 0.10    # un huerfano se propone como "valor PDF" si difiere <= 10%
COLOR_ORIGINAL = PatternFill("solid", start_color="D9C3F0")   # morado: difiere del original t-1


class Datos:
    """Carga una sola vez lo necesario, para generar muchas fichas rapido.
    Incluye el XML del anio anterior de cada fondo, para la columna Original."""

    def __init__(self, claves):
        self.enc = pd.read_csv(DIR_PROC / "encabezados.csv", dtype={"rut": str, "rut_agf": str})
        self.enc = self.enc[self.enc["es_ultimo_envio"]]
        k = pd.DataFrame(claves, columns=["rut", "anio"])
        k_prev = k.assign(anio=k["anio"] - 1)
        k_next = k.assign(anio=k["anio"] + 1)                      # reporte t+1 (hoja t+1)
        archivos = pd.concat([self.enc.merge(k, on=["rut", "anio"]),
                              self.enc.merge(k_prev, on=["rut", "anio"]),
                              self.enc.merge(k_next, on=["rut", "anio"])])["archivo"]
        cta = pd.read_csv(DIR_PROC / "cuentas.csv",
                          usecols=["archivo", "contexto", "codigo", "serie", "valor"],
                          dtype={"serie": str})
        self.cta = cta[cta["archivo"].isin(set(archivos))]
        self.res = pd.read_csv(DIR_PROC / "cruce_resumen.csv", dtype={"rut": str})
        self.det = pd.read_csv(DIR_PROC / "cruce_detalle.csv", dtype={"rut": str, "serie": str})
        self.hue = pd.read_csv(DIR_PROC / "cruce_huerfanos.csv", dtype={"rut": str})
        ch = pd.read_csv(DIR_PROC / "ecp_chequeos.csv", dtype={"rut": str})
        k = pd.DataFrame(claves, columns=["rut", "anio"])
        self.ecp = ch.merge(pd.concat([k, k.assign(anio=k["anio"] + 1), k.assign(anio=k["anio"] - 1)])
                            .drop_duplicates(), on=["rut", "anio"])
        ruta = DIR_PROC / "casos_unicos.csv"
        self.casos = pd.read_csv(ruta, dtype={"rut": str}) if ruta.exists() else pd.DataFrame()


class Comparador:
    """Arma, para cada cifra del XML, su contraparte en el PDF y en el original.

    El cruce sabe SI un monto esta en el PDF, no en QUE linea. Por eso:
      - encontrado igual      -> PDF = XML
      - signo distinto        -> PDF = -XML
      - redondeo              -> PDF = XML +-1 (no se guarda cual de los dos)
      - no encontrado         -> se PROPONE el huerfano mas cercano (<= 10%),
                                 con su pagina; si no hay, '?'
    La propuesta es una pista para mirar el PDF, no una lectura de la linea."""

    def __init__(self, det, hue, cta_original):
        self.estado, self.paginas = {}, {}
        for r in det.itertuples():
            k = (r.contexto, r.codigo, "" if pd.isna(r.serie) else r.serie)
            self.estado[k] = r.estado
            self.paginas[k] = "" if pd.isna(r.paginas) else str(r.paginas)
        self.huerfanos = list(hue.drop_duplicates("monto_pdf")[["monto_pdf", "pagina"]]
                              .itertuples(index=False, name=None))
        # Original: la columna "Actual" del reporte del anio anterior
        orig = cta_original[cta_original["contexto"] == "PeriodoActual"]
        self.original = {(c, "" if pd.isna(s) else s): v for c, s, v in
                         orig[["codigo", "serie", "valor"]].itertuples(index=False, name=None)}

    def pdf(self, ctx, codigo, serie, v):
        """Devuelve (valor_pdf, diferencia, pagina, estado)."""
        if v is None or pd.isna(v):
            return None, None, "", None
        k = (ctx, codigo, serie)
        est = self.estado.get(k)
        if est is None or est in ("ok", "ok_debil", "ok_union"):
            return v, 0, self.paginas.get(k, ""), None
        if est == "signo_distinto":
            return -v, -2 * v, self.paginas.get(k, ""), est
        if est == "ok_redondeo":
            return "±1", "±1", "", est
        if self.huerfanos and v:                      # no_encontrado: proponer
            h, pag = min(self.huerfanos, key=lambda x: abs(abs(x[0]) - abs(v)))
            if abs(abs(h) - abs(v)) <= MAX_DIF_PROPUESTA * abs(v):
                h = h if (h >= 0) == (v >= 0) else -h
                return h, h - v, f"{pag} (propuesto)", est
        return "?", None, "", est

    def orig(self, codigo, serie, v):
        """(valor_original, diferencia) o (None, None) si no hay reporte t-1."""
        if not self.original:
            return None, None
        o = self.original.get((codigo, serie))
        if o is None or v is None or pd.isna(v):
            return o, None
        return o, v - o


def _celda(ws, fila, col, v, fill=None, fmt=True):
    vacio = v is None or (not isinstance(v, str) and pd.isna(v))
    c = ws.cell(row=fila, column=col, value=None if vacio else v)
    c.font = FUENTE
    if isinstance(v, str):
        c.alignment = Alignment(horizontal="right")
    elif fmt:
        c.number_format = FMT_PDF
    if fill is not None:
        c.fill = fill
    return c


def _contextos(df):
    return [c for c in CONTEXTOS if c in set(df["contexto"])] + \
           sorted(set(df["contexto"].dropna()) - set(CONTEXTOS))


def hoja_estado(ws, cta_estado, comp: Comparador):
    """ESF / ERI / EFE: por periodo, XML | PDF | Dif | Pag (+ Original | Dif en Anterior)."""
    ctxs = _contextos(cta_estado)
    encab = ["Cuenta"]
    for ctx in ctxs:
        nombre = CONTEXTOS.get(ctx, ctx)
        encab += [f"{nombre} XML", f"{nombre} PDF", "Dif", "Pag"]
        if ctx == "PeriodoAnterior" and comp.original:
            encab += ["Original t-1", "Dif vs orig"]
    for j, t in enumerate(encab, 1):
        c = ws.cell(row=1, column=j, value=t)
        c.font = FUENTE_B
        c.alignment = Alignment(horizontal="center" if j > 1 else "left", wrap_text=True)

    fila = 1
    for r in cta_estado.drop_duplicates(["codigo", "serie"]).itertuples():
        fila += 1
        serie = "" if pd.isna(r.serie) else r.serie
        ws.cell(row=fila, column=1,
                value=legible(r.codigo) + (f"  [{serie}]" if serie else "")).font = FUENTE
        col = 2
        for ctx in ctxs:
            m = cta_estado[(cta_estado["codigo"] == r.codigo) & (cta_estado["contexto"] == ctx)
                           & (cta_estado["serie"].fillna("") == serie)]
            v = m["valor"].iloc[0] if len(m) else None
            p, dif, pag, est = comp.pdf(ctx, r.codigo, serie, v)
            fill = COLORES.get(est)
            _celda(ws, fila, col, v)
            _celda(ws, fila, col + 1, p, fill)
            _celda(ws, fila, col + 2, None if dif == 0 else dif, fill)
            _celda(ws, fila, col + 3, pag, fmt=False)
            col += 4
            if ctx == "PeriodoAnterior" and comp.original:
                o, d = comp.orig(r.codigo, serie, v)
                f2 = COLOR_ORIGINAL if d else None
                _celda(ws, fila, col, o, f2)
                _celda(ws, fila, col + 1, d if d else None, f2)
                col += 2
    ws.column_dimensions["A"].width = 60
    for j in range(2, len(encab) + 1):
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = 15
    ws.freeze_panes = "B2"


def hoja_ecp(ws, cta_ecp, comp: Comparador):
    """ECP: por periodo, bloques XML / PDF / Dif (y Original / Dif vs orig en
    Anterior), con las series en columnas y el Total al final."""
    cta_ecp = cta_ecp.copy()
    cta_ecp["base"] = cta_ecp["codigo"].str.replace("PorSerie$", "", regex=True)
    series = list(cta_ecp["serie"].dropna().drop_duplicates())
    cols = series + ["Total"]
    fila = 1
    for ctx in _contextos(cta_ecp):
        bloque = cta_ecp[cta_ecp["contexto"] == ctx]
        bases = list(bloque["base"].drop_duplicates())
        celdas = {}   # base -> [(xml, pdf, dif, est, orig, dif_orig) por columna]
        for base in bases:
            g = bloque[bloque["base"] == base]
            fila_c = []
            for s in series + [None]:
                m = g[g["serie"] == s] if s else g[g["serie"].isna()]
                if not len(m):
                    fila_c.append((None,) * 6)
                    continue
                cod, v = m.iloc[0]["codigo"], m.iloc[0]["valor"]
                p, dif, _, est = comp.pdf(ctx, cod, s or "", v)
                o, do = comp.orig(cod, s or "", v)
                fila_c.append((v, p, dif, est, o, do))
            celdas[base] = fila_c

        vistas = [("XML", 0, None), ("PDF", 1, "cruce"), ("Diferencia PDF - XML", 2, "cruce")]
        if ctx == "PeriodoAnterior" and comp.original:
            vistas += [("Original t-1 (XML del reporte anterior)", 4, None),
                       ("Diferencia vs original", 5, "orig")]
        nombre = CONTEXTOS.get(ctx, ctx)
        for titulo, idx, color in vistas:
            ws.cell(row=fila, column=1, value=f"{nombre} - {titulo}").font = FUENTE_B
            fila += 1
            ws.cell(row=fila, column=1, value="Cuenta").font = FUENTE_B
            for j, t in enumerate(cols, 2):
                c = ws.cell(row=fila, column=j, value=t)
                c.font = FUENTE_B
                c.alignment = Alignment(horizontal="center")
            for base in bases:
                fila += 1
                ws.cell(row=fila, column=1, value=legible(base)).font = FUENTE
                for j, t in enumerate(celdas[base], 2):
                    v = t[idx]
                    if idx in (2, 5) and v == 0:
                        v = None
                    if color == "orig":
                        fill = COLOR_ORIGINAL if t[5] else None
                    elif color == "cruce":
                        fill = COLORES.get(t[3])
                    else:
                        fill = None
                    _celda(ws, fila, j, v, fill)
            fila += 2
    ws.column_dimensions["A"].width = 60
    for j in range(2, len(cols) + 2):
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = 14


# ---------------------------------------------------------------------------
# Forma de estado: lineas del PDF (lectura espacial) frente a las cuentas del XML
# ---------------------------------------------------------------------------
TOL = 2                         # diferencia de redondeo aceptada al emparejar por valor
FILL_SUBT = PatternFill("solid", start_color="DDEBF7")     # azul: subtotal / identidad
FILL_CASO = PatternFill("solid", start_color="F4B6C2")     # rosado: cuenta de un caso del 04c
FILL_DIF = PatternFill("solid", start_color="FFC7CE")      # rojo: diferencia distinta de 0

# Identidades por estado: (nombre, codigo del resultado, [(signo, codigo)]). "-" resta el valor
# absoluto (gastos, pasivo e impuesto vienen con o sin signo segun la AGF).
IDENTIDADES = {
    "ESF": [("Activo neto = total activo - total pasivo", "ActivoNetoAtribuibleALosParticipes",
             [("+", "TotalActivo"), ("-", "TotalPasivo")])],
    "ERI": [("Utilidad antes de impuesto = ingresos - gastos", "UtilidadPerdidaDeLaOperacionAntesDeImpuesto",
             [("+", "TotalIngresosPerdidasNetosDeLaOperacion"), ("-", "TotalGastosDeOperacion")]),
            ("Utilidad despues de impuesto = antes - impuesto", "UtilidadPerdidaDeLaOperacionDespuesDeImpuesto",
             [("+", "UtilidadPerdidaDeLaOperacionAntesDeImpuesto"),
              ("-", "ImpuestosALasGananciasPorInversionesEnElExterior")])],
    "EFE": [("Aumento neto = operacion + financiamiento", "AumentoNetoDeEfectivoYEfectivoEquivalente",
             [("+", "FlujoNetoOriginadoPorActividadesDeLaOperacion"),
              ("+", "FlujoNetoOriginadoPorActividadesDeFinanciamiento")]),
            ("Saldo final = inicial + aumento neto + dif. de cambio", "SaldoFinalDeEfectivoYEfectivoEquivalente",
             [("+", "SaldoInicialDeEfectivoYEfectivoEquivalente"), ("+", "AumentoNetoDeEfectivoYEfectivoEquivalente"),
              ("+", "DiferenciasDeCambioNetasSobreEfectivoYEfectivoEquivalente")])],
}


# Partes de una identidad que pueden no venir (en cero, sin linea ni cuenta): sin ellas la
# identidad igual se evalua. Las demas son obligatorias: si falta alguna en el documento la
# identidad no se evalua (una plantilla sin "aumento neto" no es un saldo final que no cuadra).
OPCIONALES = {"DiferenciasDeCambioNetasSobreEfectivoYEfectivoEquivalente",
              "ImpuestosALasGananciasPorInversionesEnElExterior"}


def glosa_vista(ln):
    """Glosa partida en varias lineas ('entregados en garantia (+)'): se muestra completa."""
    return ln[2] if ln[1][:1].islower() and ln[2] != ln[1] else ln[1]


def xml_estado(cta_estado):
    """{codigo: (actual, anterior)} de un estado (sin series). Una cuenta sin valor en una columna
    que el XML si trae = 0."""
    cta_estado = cta_estado[cta_estado["serie"].isna()]
    hay_ctx = set(cta_estado["contexto"])
    xml = {}
    for c in cta_estado["codigo"].drop_duplicates():
        m = cta_estado[cta_estado["codigo"] == c].set_index("contexto")["valor"]
        xml[c] = tuple(m.get(ctx, 0 if ctx in hay_ctx else None) for ctx in ("PeriodoActual", "PeriodoAnterior"))
    return xml


COINCIDE = {"ambos": "glosa y valor", "glosa": "glosa", "valor": "valor"}
NOTA_METODO = {"corrido": " (montos corridos una linea)", "monto_sin_glosa": " (monto en linea sin texto)"}


def leer_reporte(coords, paginas_estados, cta):
    """Lector unificado sobre un reporte: {estado: (lineas, par)} para ESF, ERI y EFE, y
    {pagina: (estado, titulo impreso)} de las paginas cuyo titulo es de otro estado.
    lineas: [(pagina, glosa, glosa_ext, actual, anterior)] con monto; par: {i: (codigo, coincide)}."""
    paginas, base = paginas_de(paginas_estados, coords)
    if not paginas:
        return {}, {}
    rs, _ = leer_estados(coords, paginas, base=base)
    out, rotulos = {}, {}
    for est in ("ESF", "ERI", "EFE"):
        sub = [r for r in rs if r["estado"] == est]
        emparejar_comun(sub, xml_estado(cta[cta["estado_fin"] == est]), est)
        lineas, par = [], {}
        for r in sub:
            if r.get("rotulo"):
                rotulos[r["pagina"]] = (est, r["rotulo"])
            if r["metodo"] == "encabezado" or (r["actual"] is None and r["anterior"] is None):
                continue
            if r["codigo"]:
                par[len(lineas)] = (r["codigo"], COINCIDE[r["coincide"]] + NOTA_METODO.get(r["metodo"], ""))
            lineas.append((r["pagina"], r["glosa"], (r["previa"] + " " + r["glosa"]).strip(),
                           r["actual"] or 0, r["anterior"] or 0))
        if lineas:
            out[est] = (lineas, par)
    return out, rotulos


def hoja_forma(ws, est, cta_estado, lineas, par, casos_cod):
    """Hoja de un estado en forma de estado. Devuelve un resumen para la consola."""
    xml = xml_estado(cta_estado)
    de_cod = {c: i for i, (c, _) in par.items()}
    # ventana del estado en el PDF: de la primera a la ultima linea emparejada (en una pagina
    # compartida, las lineas de otro estado no entran como "solo PDF")
    if par:
        lo, hi = min(par), max(par)
        fuera = {i for i in range(len(lineas)) if i < lo or i > hi}
    else:
        fuera = set()

    # ---- filas: (bloque, glosa_pdf, codigo, i_linea, coincide) ----
    filas = []
    for c in xml:                                                  # bloque 1, orden del XML
        i = de_cod.get(c)
        if i is not None and par[i][1] != "valor":
            filas.append(("glosa", glosa_vista(lineas[i]), c, i, par[i][1]))
    for i in sorted(par):                                          # bloque 2, orden del PDF
        if par[i][1] == "valor":
            filas.append(("valor", glosa_vista(lineas[i]), par[i][0], i, "valor"))
    for i, ln in enumerate(lineas):                                # bloque 3
        if i not in par and i not in fuera and (ln[3] or ln[4]):
            filas.append(("solo", glosa_vista(ln), None, i, "solo PDF"))
    for c, (a, b) in xml.items():
        if c not in de_cod and ((a or 0) or (b or 0)):
            filas.append(("solo", "", c, None, "solo XML"))

    encab = ["Glosa PDF", "Cuenta XML", "Actual PDF", "Actual XML", "Dif", "Anterior PDF",
             "Anterior XML", "Dif", "Coincide", "Pag"]
    for j, t in enumerate(encab, 1):
        c = ws.cell(row=1, column=j, value=t)
        c.font, c.alignment = FUENTE_B, Alignment(horizontal="center" if j > 2 else "left", wrap_text=True)
    titulos = {"glosa": "Coinciden por glosa (orden del estado)",
               "valor": "Coinciden solo por valor: glosa del PDF distinta de la cuenta del XML",
               "solo": "Sin coincidencia"}
    subt_cods = {cfg["codigo"] for cfg in SUBTOTALES.values()} | {i[1] for i in IDENTIDADES.get(est, [])}
    fila, bloque, fila_cod, fila_lin = 1, None, {}, {}
    for b, glosa, c, i, coin in filas:
        if b != bloque:
            fila += 2
            ws.cell(row=fila, column=1, value=titulos[b]).font = FUENTE_B
            bloque = b
        fila += 1
        ws.cell(row=fila, column=1, value=glosa).font = FUENTE
        cx = ws.cell(row=fila, column=2, value=legible(c) if c else None)
        cx.font = FUENTE_B if c in subt_cods else FUENTE
        if c in casos_cod:
            cx.fill = FILL_CASO
        ln = lineas[i] if i is not None else None
        xa, xb = xml[c] if c else (None, None)
        for col, v in ((3, ln[3] if ln else None), (4, xa), (6, ln[4] if ln else None), (7, xb)):
            _celda(ws, fila, col, None if v is None or pd.isna(v) else v,
                   FILL_SUBT if c in subt_cods else None)
        for col, (p, x) in ((5, (ln[3] if ln else None, xa)), (8, (ln[4] if ln else None, xb))):
            if p is not None and x is not None and not pd.isna(x):
                L = ws.cell(row=1, column=col - 2).column_letter
                R = ws.cell(row=1, column=col - 1).column_letter
                # en valor absoluto: el signo depende de la convencion de cada documento
                f = _celda(ws, fila, col, f"=ABS({L}{fila})-ABS({R}{fila})")
                f.number_format = FMT_PDF
                if abs(abs(p) - abs(x)) > TOL:
                    f.fill = FILL_DIF
                if p and x and (p > 0) != (x > 0) and "signo" not in coin:
                    coin += ", signo distinto"
        # La cifra del PDF difiere de su cuenta del XML pero es la de OTRA cuenta del XML: la misma
        # cifra esta clasificada distinto (p.ej. costo amortizado vs valor razonable) o dos filas
        # intercambiaron montos. Se dice cual.
        for k, (p, x) in ((0, (ln[3] if ln else None, xa)), (1, (ln[4] if ln else None, xb))):
            if not p or (x is not None and not pd.isna(x) and abs(abs(p) - abs(x)) <= TOL):
                continue
            otra = next((c2 for c2, v2 in xml.items() if c2 != c and v2[k] is not None and not pd.isna(v2[k])
                         and v2[k] and abs(abs(v2[k]) - abs(p)) <= TOL), None)
            if otra:
                coin += f"; {'act' if k == 0 else 'ant'}: PDF = XML de {legible(otra)}"
        ws.cell(row=fila, column=9, value=coin).font = FUENTE
        ws.cell(row=fila, column=10, value=ln[0] if ln else None).font = FUENTE
        if c:
            fila_cod[c] = fila
        if i is not None:
            fila_lin[i] = fila

    # ---- verificacion: subtotales e identidades ----
    fila += 3
    ws.cell(row=fila, column=1, value="Verificacion: impreso, suma de partes (formula) y diferencia").font = FUENTE_B
    resumen = []

    def bloque_chequeo(nombre, filas_pdf, filas_xml, fila_tot, signos=None):
        """filas_*: filas de las partes; signos: {fila: '+'|'-'} (identidades)."""
        nonlocal fila
        fila += 2
        ws.cell(row=fila, column=1, value=nombre).font = FUENTE_B
        for desc, k in (("impreso", 0), ("suma de partes", 1), ("diferencia", 2)):
            fila += 1
            ws.cell(row=fila, column=2, value=desc).font = FUENTE
            for col_v, partes in ((3, filas_pdf), (4, filas_xml), (6, filas_pdf), (7, filas_xml)):
                L = ws.cell(row=1, column=col_v).column_letter
                if k == 0:
                    v = f"={L}{fila_tot}" if fila_tot else None
                elif k == 1:
                    if not partes:
                        v = None
                    elif signos:
                        v = "=" + "".join(("-ABS(" if signos[r] == "-" else "+") + f"{L}{r}" +
                                          (")" if signos[r] == "-" else "") for r in partes)
                    else:
                        v = "=SUM(" + ",".join(f"{L}{r}" for r in partes) + ")"
                else:
                    v = f"={L}{fila - 2}-{L}{fila - 1}" if fila_tot and partes else None
                c = _celda(ws, fila, col_v, v, FILL_SUBT if k == 0 else None)
                c.number_format = FMT_PDF

    # partes del PDF por posicion: lineas entre el subtotal anterior del estado y el suyo
    subts = [(n, cfg) for n, cfg in SUBTOTALES.items() if cfg["estado"] == est]
    pos = sorted((de_cod[cfg["codigo"]], n) for n, cfg in subts if cfg["codigo"] in de_cod)
    inicio = {n: (pos[k - 1][0] + 1 if k else (min(par) if par else 0)) for k, (_, n) in enumerate(pos)}
    for n, cfg in subts:
        i_tot = de_cod.get(cfg["codigo"])
        f_pdf = ([fila_lin[i] for i in range(inicio[n], i_tot) if i in fila_lin
                  and (i not in par or par[i][0] not in subt_cods)] if i_tot is not None else [])
        f_xml = [fila_cod[c] for c in cfg["partes"] if c in fila_cod]
        tot = fila_cod.get(cfg["codigo"])
        if tot or f_xml:
            bloque_chequeo(f"Subtotal: {legible(cfg['codigo'])}", f_pdf, f_xml, tot)
            if i_tot is not None:
                s_pdf = sum((lineas[i][3] or 0) for i in range(inicio[n], i_tot)
                            if i in fila_lin and (i not in par or par[i][0] not in subt_cods))
                resumen.append(f"{n} PDF dif {lineas[i_tot][3] - s_pdf:,.0f}")
    for nombre, res, partes in IDENTIDADES.get(est, []):
        if any(c not in fila_cod for _, c in partes if c not in OPCIONALES):
            continue                                    # falta una parte obligatoria: no se evalua
        filas_p = [(s, fila_cod[c]) for s, c in partes if c in fila_cod]
        if res in fila_cod and filas_p:
            sig = {r: s for s, r in filas_p}
            r_pdf = [r for _, r in filas_p if ws.cell(row=r, column=3).value is not None]
            bloque_chequeo(f"Identidad: {nombre}", r_pdf, [r for _, r in filas_p], fila_cod[res], sig)

    ws.column_dimensions["A"].width = 55
    ws.column_dimensions["B"].width = 55
    for j in range(3, 9):
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = 15
    ws.column_dimensions["I"].width = 40
    ws.freeze_panes = "C2"
    n = pd.Series([f[0] for f in filas]).value_counts().to_dict() if filas else {}
    return f"{est}: glosa {n.get('glosa', 0)}, valor {n.get('valor', 0)}, sin coincidencia {n.get('solo', 0)}" + \
           (f" | {'; '.join(resumen)}" if resumen else "")


# ---------------------------------------------------------------------------
# ECP en forma de estado: lectura del 03d (ecp_chequeos) frente al XML, por serie
# ---------------------------------------------------------------------------
ECP_FILAS = [  # (clave del 03d, nombre, codigo XML del total; por serie + "PorSerie")
    ("inicio", "Activo neto al 1 de enero", "ActivoNetoAtribuibleALosParticipesAl01DeEnero"),
    ("aportes", "Aportes de cuotas", "AportesDeCuotas"),
    ("rescates", "Rescates de cuotas", "RescateDeCuotas"),
    ("neto", "Aumento neto por transacciones de cuotas", "AumentoNetoOriginadoPorTransaccionesDeCuotas"),
    ("res_despues", "Resultado despues de distribucion",
     "AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacion"
     "DespuesDeDistribucionDeBeneficios"),
    ("cierre", "Activo neto al 31 de diciembre", "ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuota"),
]


def _nums(texto):
    """'aportes=1500 | rescates=-500 | neto=1000' -> {'aportes': 1500.0, ...}"""
    out = {}
    for t in str(texto).split("|"):
        if "=" in t:
            k, x = t.rsplit("=", 1)
            try:
                out[k.strip()] = float(x)
            except ValueError:
                pass
    return out


def ecp_pdf(ch):
    """{columna: {col_03d: {clave: valor}}} desde las filas transacciones/evolucion del 03d."""
    out = {}
    for r in ch[ch["chequeo"].isin(["transacciones", "evolucion"])].itertuples():
        d = out.setdefault(r.columna, {}).setdefault(r.col, {})
        for k, v in _nums(r.pdf).items():
            d.setdefault(k, v)
    return out


def ecp_xml(cta_ecp, ctx):
    """{serie|'TOTAL': {clave: valor}} del XML en un contexto."""
    c = cta_ecp[cta_ecp["contexto"] == ctx]
    out = {}
    for clave, _, cod in ECP_FILAS:
        tot = c[c["serie"].isna() & (c["codigo"] == cod)]["valor"]
        if len(tot):
            out.setdefault("TOTAL", {})[clave] = tot.iloc[0]
        ps = c[c["serie"].notna() & (c["codigo"] == cod + "PorSerie")]
        for s, v in zip(ps["serie"], ps["valor"]):
            out.setdefault(s, {})[clave] = v
    return out


def asociar_series(pdf_cols, xml_series):
    """Columna del 03d -> serie del XML por la mayor cantidad de valores iguales (uno a uno).
    'total' -> TOTAL."""
    cand = []
    for col, pv in pdf_cols.items():
        if col == "total":
            continue
        for s, xv in xml_series.items():
            if s == "TOTAL":
                continue
            n = sum(1 for k in pv if k in xv and pv[k] and abs(abs(pv[k]) - abs(xv[k])) <= TOL)
            if n:
                cand.append((n, col, s))
    par, usadas = {"total": "TOTAL"} if "total" in pdf_cols else {}, set()
    for n, col, s in sorted(cand, reverse=True):
        if col not in par and s not in usadas:
            par[col] = s
            usadas.add(s)
    return par


def hoja_ecp_forma(ws, ch, cta_ecp, casos_cod):
    """Por columna (actual / anterior): filas del ECP x series, PDF | XML | Dif por serie; luego
    las verificaciones con formulas (transacciones, evolucion, suma de series, continuidad)."""
    pdf = ecp_pdf(ch)
    fila = 1
    pos = {}                                     # (columna, serie, clave, 'pdf'|'xml') -> celda
    resumen = []
    for columna, ctx in (("actual", "PeriodoActual"), ("anterior", "PeriodoAnterior")):
        xml = ecp_xml(cta_ecp, ctx)
        cols = pdf.get(columna, {})
        if not cols and not xml:
            continue
        par = asociar_series(cols, xml)
        series = [s for s in xml if s != "TOTAL"] + (["TOTAL"] if "TOTAL" in xml else [])
        de_serie = {s: c for c, s in par.items()}
        sin_par = [c for c in cols if c not in par]
        ws.cell(row=fila, column=1, value=f"{columna.capitalize()}").font = FUENTE_B
        fila += 1
        ws.cell(row=fila, column=1, value="Fila").font = FUENTE_B
        for k, s in enumerate(series):
            c0 = 2 + 3 * k
            t = ws.cell(row=fila, column=c0, value=f"{s} ({de_serie.get(s, 'sin columna PDF')})")
            t.font = FUENTE_B
            for j, h in enumerate(("PDF", "XML", "Dif")):
                ws.cell(row=fila + 1, column=c0 + j, value=h).font = FUENTE_B
        fila += 1
        for clave, nombre, cod in ECP_FILAS:
            fila += 1
            ws.cell(row=fila, column=1, value=nombre).font = FUENTE
            for k, s in enumerate(series):
                c0 = 2 + 3 * k
                p = cols.get(de_serie.get(s), {}).get(clave)
                x = xml.get(s, {}).get(clave)
                marca = (cod + ("" if s == "TOTAL" else "PorSerie")) in casos_cod
                _celda(ws, fila, c0, p)
                cx = _celda(ws, fila, c0 + 1, x)
                if marca:
                    cx.fill = FILL_CASO
                if p is not None and x is not None:
                    L = ws.cell(row=1, column=c0).column_letter
                    R = ws.cell(row=1, column=c0 + 1).column_letter
                    f = _celda(ws, fila, c0 + 2, f"=ABS({L}{fila})-ABS({R}{fila})")
                    f.number_format = FMT_PDF
                    if abs(abs(p) - abs(x)) > TOL:
                        f.fill = FILL_DIF
                if p is not None:                    # solo celdas con valor entran a las formulas
                    pos[(columna, s, clave, "pdf")] = f"{ws.cell(row=1, column=c0).column_letter}{fila}"
                if x is not None:
                    pos[(columna, s, clave, "xml")] = f"{ws.cell(row=1, column=c0 + 1).column_letter}{fila}"
        if sin_par:
            fila += 1
            ws.cell(row=fila, column=1, value="Columnas del PDF sin serie del XML: " + ", ".join(
                f"{c} ({', '.join(f'{k}={v:,.0f}' for k, v in cols[c].items())})" for c in sin_par)).font = FUENTE
        resumen.append(f"{columna}: {len(par)} de {len(cols)} columnas del PDF asociadas a {len(series)} series del XML")
        fila += 2

    # ---- verificacion ----
    fila += 1
    ws.cell(row=fila, column=1, value="Verificacion: impreso, formula y diferencia (PDF y XML por serie)").font = FUENTE_B
    series_todas = sorted({k[1] for k in pos}, key=lambda s: (s == "TOTAL", s))
    enc_fila = fila + 1
    for k, s in enumerate(series_todas):
        for j, d in enumerate(("PDF", "XML")):
            ws.cell(row=enc_fila, column=2 + 2 * k + j, value=f"{s} {d}").font = FUENTE_B
    fila = enc_fila

    def chequeo(nombre, impreso, formula):
        """impreso(columna, s, d) -> ref | None; formula(columna, s, d) -> str | None."""
        nonlocal fila
        for columna in ("actual", "anterior"):
            if not any(impreso(columna, s, d) and formula(columna, s, d)
                       for s in series_todas for d in ("pdf", "xml")):
                continue                                   # bloque vacio: no se escribe
            fila += 2
            ws.cell(row=fila, column=1, value=f"{nombre} ({columna})").font = FUENTE_B
            for desc, k in (("impreso", 0), ("formula", 1), ("diferencia", 2)):
                fila += 1
                ws.cell(row=fila, column=1, value=f"   {desc}").font = FUENTE
                for i, s in enumerate(series_todas):
                    for j, d in enumerate(("pdf", "xml")):
                        col = 2 + 2 * i + j
                        L = ws.cell(row=1, column=col).column_letter
                        imp, fm = impreso(columna, s, d), formula(columna, s, d)
                        if not imp or not fm:
                            continue
                        v = f"={imp}" if k == 0 else (f"={fm}" if k == 1 else f"={L}{fila - 2}-{L}{fila - 1}")
                        c = _celda(ws, fila, col, v, FILL_SUBT if k == 0 else None)
                        c.number_format = FMT_PDF

    ref = lambda c, s, cl, d: pos.get((c, s, cl, d))
    def todas(c, s, d, *claves):
        r = [ref(c, s, cl, d) for cl in claves]
        return r if all(r) else None
    chequeo("Transacciones: aportes - |rescates| = neto",
            lambda c, s, d: ref(c, s, "neto", d),
            lambda c, s, d: (lambda r: f"{r[0]}-ABS({r[1]})" if r else None)(todas(c, s, d, "aportes", "rescates")))
    chequeo("Evolucion: inicio + neto + resultado = cierre",
            lambda c, s, d: ref(c, s, "cierre", d),
            lambda c, s, d: (lambda r: "+".join(r) if r else None)(todas(c, s, d, "inicio", "neto", "res_despues")))
    for clave, nombre, _ in ECP_FILAS:
        chequeo(f"Suma de series = total: {nombre.lower()}",
                lambda c, s, d, cl=clave: ref(c, s, cl, d) if s == "TOTAL" else None,
                lambda c, s, d, cl=clave: (lambda r: f"SUM({','.join(r)})" if r else None)(
                    [ref(c, x, cl, d) for x in series_todas if x != "TOTAL" and ref(c, x, cl, d)]))
    # continuidad dentro del mismo documento: inicio actual = cierre del comparativo (anterior)
    if not any(ref("actual", s, "inicio", d) and ref("anterior", s, "cierre", d)
               for s in series_todas for d in ("pdf", "xml")):
        ws.column_dimensions["A"].width = 48
        return "ECP: " + "; ".join(resumen)
    fila += 2
    ws.cell(row=fila, column=1, value="Continuidad: inicio (actual) = cierre (anterior)").font = FUENTE_B
    for desc, k in (("inicio actual", 0), ("cierre anterior", 1), ("diferencia", 2)):
        fila += 1
        ws.cell(row=fila, column=1, value=f"   {desc}").font = FUENTE
        for i, s in enumerate(series_todas):
            for j, d in enumerate(("pdf", "xml")):
                col = 2 + 2 * i + j
                L = ws.cell(row=1, column=col).column_letter
                a, b = ref("actual", s, "inicio", d), ref("anterior", s, "cierre", d)
                if not a or not b:
                    continue
                v = f"={a}" if k == 0 else (f"={b}" if k == 1 else f"={L}{fila - 2}-{L}{fila - 1}")
                c = _celda(ws, fila, col, v, FILL_SUBT if k == 0 else None)
                c.number_format = FMT_PDF

    ws.column_dimensions["A"].width = 48
    for j in range(2, 2 + 3 * max(len(series_todas), 1) + 1):
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = 14
    ws.freeze_panes = "B1"
    return "ECP: " + "; ".join(resumen)


# ---------------------------------------------------------------------------
# Hoja t+1: la cifra de t (columna actual) frente a como la muestra el reporte de t+1
# (columna anterior), en PDF y en XML; y continuidad cierre t = inicio t+1
# ---------------------------------------------------------------------------
def valores_pdf(rep, est):
    """{codigo: (actual, anterior)} del PDF de un reporte (emparejado con su propio XML)."""
    lineas, par = rep["lineas"].get(est, ([], {}))
    return {cod: (lineas[i][3], lineas[i][4]) for i, (cod, _) in par.items()}


def ecp_series(ch, cta_ecp, columna, ctx):
    """{(serie, clave): (pdf, xml)} del ECP de un reporte, en una columna."""
    xml = ecp_xml(cta_ecp, ctx)
    cols = ecp_pdf(ch).get(columna, {})
    par = asociar_series(cols, xml)
    de_serie = {s: c for c, s in par.items()}
    return {(s, k): (cols.get(de_serie.get(s), {}).get(k), v) for s, d in xml.items() for k, v in d.items()}


DOCS = ("PDF t", "XML t", "PDF t+1", "XML t+1")


def cuadra_estado(vals, est):
    """{codigo: True|False} para los codigos que participan en un subtotal o identidad del estado
    (True si todos los chequeos en que participa cuadran). vals: {codigo: valor} de UN documento."""
    res = {}
    def marca(cods, ok):
        for c in cods:
            res[c] = res.get(c, True) and ok
    for cfg in SUBTOTALES.values():
        if cfg["estado"] != est or vals.get(cfg["codigo"]) is None:
            continue
        partes = [c for c in cfg["partes"] if vals.get(c) is not None]
        if partes:
            ok = abs(sum(vals[c] for c in partes) - vals[cfg["codigo"]]) <= TOL
            marca([cfg["codigo"], *partes], ok)
    for _, r, partes in IDENTIDADES.get(est, []):
        if any(vals.get(c) is None for _, c in partes if c not in OPCIONALES):
            continue
        ps = [(sg, c) for sg, c in partes if vals.get(c) is not None]
        if vals.get(r) is not None and ps:
            calc = sum(vals[c] if sg == "+" else -abs(vals[c]) for sg, c in ps)
            marca([r, *[c for _, c in ps]], abs(calc - vals[r]) <= TOL)
    return res


def cuadra_ecp(d):
    """Igual para una serie del ECP: d = {clave: valor}."""
    res = {}
    def marca(ks, ok):
        for k in ks:
            res[k] = res.get(k, True) and ok
    if all(d.get(k) is not None for k in ("aportes", "rescates", "neto")):
        marca(("aportes", "rescates", "neto"), abs(abs(d["aportes"]) - abs(d["rescates"]) - d["neto"]) <= TOL)
    if all(d.get(k) is not None for k in ("inicio", "neto", "res_despues", "cierre")):
        marca(("inicio", "neto", "res_despues", "cierre"),
              abs(d["inicio"] + d["neto"] + d["res_despues"] - d["cierre"]) <= TOL)
    return res


def veredicto(vals, cuadra, docs=DOCS):
    """vals, cuadra: 4 valores / 4 True|False|None en el orden de DOCS. Regla:
    4 iguales -> ok; 3 contra 1 -> error en el que discrepa; 2 contra 2 (o 2 versiones distintas)
    -> error en el grupo cuyo documento no cuadra internamente, si el otro si cuadra; si no,
    sin determinar."""
    hay = [i for i, v in enumerate(vals) if v is not None and not pd.isna(v)]
    if len(hay) < 2:
        return ""
    grupos = []
    for i in hay:
        g = next((g for g in grupos if abs(abs(vals[g[0]]) - abs(vals[i])) <= TOL), None)
        g.append(i) if g is not None else grupos.append([i])
    if len(grupos) == 1:
        return "ok" if len(hay) == 4 else f"ok ({len(hay)} de 4)"
    grupos.sort(key=len, reverse=True)
    nombre = lambda g: " + ".join(docs[i] for i in g)
    if sorted(map(sorted, grupos)) == [[0, 1], [2, 3]]:
        # PDF y XML del primer reporte coinciden entre si, y los dos del siguiente tambien, pero con
        # otra cifra: el reporte siguiente cambio el comparativo (reexpresion o reclasificacion)
        return f"cambia en {docs[2].split()[-1]} (reexpresion o reclasificacion)"
    if len(grupos[0]) > len(grupos[1]) and len(grupos[0]) >= 2:
        return "error en " + ", ".join(nombre(g) for g in grupos[1:])
    ok_g = [all(cuadra[i] is True for i in g) for g in grupos]
    falla_g = [any(cuadra[i] is False for i in g) for g in grupos]
    if sum(ok_g) == 1 and all(f for g_ok, f in zip(ok_g, falla_g) if not g_ok):
        return "error en " + ", ".join(nombre(g) for g, k in zip(grupos, ok_g) if not k) + " (no cuadra)"
    return "sin determinar: " + " | ".join(nombre(g) for g in grupos)


def hoja_t1(ws, t, t1, anio):
    """t, t1: dict(cta, lineas={estado: lineas}, ch) del reporte de t y de t+1 (o None)."""
    if t is None or t1 is None:
        ws["A1"] = f"(falta el reporte {anio if t is None else anio + 1} del fondo: sin comparativo {anio} vs {anio + 1})"
        return f"{anio}/{anio + 1}: sin reporte", None
    nombres_doc = (f"PDF {anio}", f"XML {anio}", f"PDF {anio + 1}", f"XML {anio + 1}")
    encab = ["Cuenta", f"PDF {anio} (actual)", f"PDF {anio + 1} (anterior)", "Dif",
             f"XML {anio} (actual)", f"XML {anio + 1} (anterior)", "Dif", "Veredicto",
             f"Cuadra interna ({' | '.join(nombres_doc)})"]
    fila, cambios, conteo, errores, seccion = 0, {}, {}, [], [""]
    signo = {True: "si", False: "NO", None: "-"}

    def escribir_fila(nombre, p0, p1, x0, x1, negrita=False, cuadra=None):
        nonlocal fila
        fila += 1
        ws.cell(row=fila, column=1, value=nombre).font = FUENTE_B if negrita else FUENTE
        for col, v in ((2, p0), (3, p1), (5, x0), (6, x1)):
            _celda(ws, fila, col, None if v is None or (not isinstance(v, str) and pd.isna(v)) else v)
        hay = False
        for col, (a, b) in ((4, (p0, p1)), (7, (x0, x1))):
            if a is not None and b is not None and not pd.isna(a) and not pd.isna(b):
                L, R = ws.cell(row=1, column=col - 2).column_letter, ws.cell(row=1, column=col - 1).column_letter
                f = _celda(ws, fila, col, f"=ABS({R}{fila})-ABS({L}{fila})")
                f.number_format = FMT_PDF
                if abs(abs(b) - abs(a)) > TOL:
                    f.fill = FILL_DIF
                    hay = True
        if cuadra is not None:
            v = veredicto((p0, x0, p1, x1), cuadra, nombres_doc)
            c = ws.cell(row=fila, column=8, value=v)
            c.font = FUENTE
            if v.startswith(("error", "sin")):
                c.fill = FILL_DIF
            ws.cell(row=fila, column=9, value=" | ".join(signo[k] for k in cuadra)).font = FUENTE
            clave = v.split(":")[0].split(" (")[0] if v else "sin datos"
            conteo[clave] = conteo.get(clave, 0) + 1
            if v.startswith(("error", "sin")):
                errores.append((seccion[0], nombre, v))
        return hay

    def titulo(texto):
        nonlocal fila
        seccion[0] = texto.split()[0]
        fila += 2
        ws.cell(row=fila, column=1, value=texto).font = FUENTE_B
        fila += 1
        for j, h in enumerate(encab, 1):
            c = ws.cell(row=fila, column=j, value=h)
            c.font, c.alignment = FUENTE_B, Alignment(horizontal="center" if j > 1 else "left", wrap_text=True)

    for est in ("ESF", "ERI", "EFE"):
        c0 = t["cta"][(t["cta"]["estado_fin"] == est) & t["cta"]["serie"].isna()]
        c1 = t1["cta"][(t1["cta"]["estado_fin"] == est) & t1["cta"]["serie"].isna()]
        p0, p1 = valores_pdf(t, est), valores_pdf(t1, est)
        x0 = c0[c0["contexto"] == "PeriodoActual"].set_index("codigo")["valor"]
        x1 = c1[c1["contexto"] == "PeriodoAnterior"].set_index("codigo")["valor"]
        cods = list(dict.fromkeys(list(c0["codigo"]) + list(c1["codigo"])))
        docs = ({c: v[0] for c, v in p0.items()}, x0.to_dict(), {c: v[1] for c, v in p1.items()}, x1.to_dict())
        cq = [cuadra_estado({k: v for k, v in d.items() if v is not None and not pd.isna(v)}, est) for d in docs]
        titulo(est)
        n = 0
        # Un documento que SI trae el estado pero no la cuenta la tiene en 0 (la cifra se movio a
        # otra linea o se omitio): sin esto la celda queda en blanco y la Dif no se calcula.
        tiene = (bool(p0), not x0.empty, bool(p1), not x1.empty)
        for cod in cods:
            v = (p0.get(cod, (None,))[0], p1.get(cod, (None, None))[1], x0.get(cod), x1.get(cod))
            if all(x is None or pd.isna(x) for x in v):
                continue
            v = tuple(0 if (x is None or pd.isna(x)) and t else x
                      for x, t in zip(v, (tiene[0], tiene[2], tiene[1], tiene[3])))
            n += escribir_fila(legible(cod), *v, cuadra=tuple(q.get(cod) for q in cq))
        cambios[est] = n

    # ECP por serie
    c0 = t["cta"][t["cta"]["estado_fin"] == "ECP"]
    c1 = t1["cta"][t1["cta"]["estado_fin"] == "ECP"]
    e0 = ecp_series(t["ch"], c0, "actual", "PeriodoActual")
    e1 = ecp_series(t1["ch"], c1, "anterior", "PeriodoAnterior")
    titulo("ECP (por serie)")
    n = 0
    series = list(dict.fromkeys([s for s, _ in e0] + [s for s, _ in e1]))
    series = [s for s in series if s != "TOTAL"] + (["TOTAL"] if "TOTAL" in series else [])
    for s in series:
        por_doc = [{k: e[(s, k)][j] for k, _, _ in ECP_FILAS if (s, k) in e and e[(s, k)][j] is not None}
                   for e, j in ((e0, 0), (e0, 1), (e1, 0), (e1, 1))]
        cq = [cuadra_ecp(d) for d in por_doc]
        for clave, nombre, _ in ECP_FILAS:
            a, b = e0.get((s, clave), (None, None)), e1.get((s, clave), (None, None))
            if any(v is not None for v in (*a, *b)):
                n += escribir_fila(f"{s} · {nombre}", a[0], b[0], a[1], b[1], negrita=(s == "TOTAL"),
                                   cuadra=tuple(q.get(clave) for q in cq))
    cambios["ECP"] = n

    # Continuidad: cierre de t = inicio de t+1 (columna actual de cada reporte)
    titulo(f"Continuidad: cierre {anio} = inicio {anio + 1}")
    ws.cell(row=fila, column=2, value=f"PDF cierre {anio}")
    ws.cell(row=fila, column=3, value=f"PDF inicio {anio + 1}")
    ws.cell(row=fila, column=5, value=f"XML cierre {anio}")
    ws.cell(row=fila, column=6, value=f"XML inicio {anio + 1}")
    e1a = ecp_series(t1["ch"], c1, "actual", "PeriodoActual")
    for s in series:
        a, b = e0.get((s, "cierre"), (None, None)), e1a.get((s, "inicio"), (None, None))
        if any(v is not None for v in (*a, *b)):
            escribir_fila(f"ECP {s}", a[0], b[0], a[1], b[1], negrita=(s == "TOTAL"))
    for est, cierre, inicio in (("EFE", "SaldoFinalDeEfectivoYEfectivoEquivalente",
                                 "SaldoInicialDeEfectivoYEfectivoEquivalente"),):
        c0e = t["cta"][(t["cta"]["estado_fin"] == est) & t["cta"]["serie"].isna()]
        c1e = t1["cta"][(t1["cta"]["estado_fin"] == est) & t1["cta"]["serie"].isna()]
        p0, p1 = valores_pdf(t, est), valores_pdf(t1, est)
        x0 = c0e[c0e["contexto"] == "PeriodoActual"].set_index("codigo")["valor"]
        x1 = c1e[c1e["contexto"] == "PeriodoActual"].set_index("codigo")["valor"]
        escribir_fila(f"EFE efectivo: saldo final {anio} = saldo inicial {anio + 1}", p0.get(cierre, (None,))[0],
                      p1.get(inicio, (None,))[0], x0.get(cierre), x1.get(inicio))

    ws.column_dimensions["A"].width = 60
    for j in range(2, 8):
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = 17
    ws.column_dimensions["H"].width = 40
    ws.column_dimensions["I"].width = 22
    return (f"{anio} vs {anio + 1}: filas que cambian " + ", ".join(f"{k} {v}" for k, v in cambios.items())
            + " | veredictos " + ", ".join(f"{k} {v}" for k, v in sorted(conteo.items()))), errores


def _archivo(datos, rut, anio):
    e = datos.enc[(datos.enc["rut"] == rut) & (datos.enc["anio"] == anio)]
    return e["archivo"].iloc[0] if len(e) else "(no disponible)"


def _pdf(datos, rut, anio):
    r = datos.res[(datos.res["rut"] == rut) & (datos.res["anio"] == anio)]
    if len(r) and pd.notna(r["pdf"].iloc[0]):
        return str(CMF_HOME / "archivos" / rut / str(anio) / r["pdf"].iloc[0])
    return "(no disponible)"


def resumen_fondo(info, errores, casos, anio):
    """Arriba de la hoja Fondo: estados con error segun el veredicto t+1 y casos del 04c."""
    filas = [("RESUMEN", "")]
    if errores is None:
        filas.append(("EEFF con error", f"sin reportes {anio - 1} ni {anio + 1}: no hay veredicto"))
    else:
        por_est = {}
        for est, nombre, v in errores:
            por_est.setdefault(est, {}).setdefault(v.split(" (")[0], []).append(nombre.split(" · ")[0])
        filas.append(("EEFF con error", ", ".join(por_est) if por_est else "ninguno: todas las cifras ok"))
        for est, vs in por_est.items():
            for v, nombres in vs.items():
                det = ", ".join(dict.fromkeys(nombres))
                filas.append((f"  {est}", f"{v}: {len(nombres)} cifras ({det[:150]})"))
    filas.append(("Casos del 04c", f"{len(casos)} (hoja Casos)" if len(casos) else "ninguno"))
    filas.append(("", ""))
    info.insert_rows(1, len(filas))
    for i, (k, v) in enumerate(filas, 1):
        info.cell(row=i, column=1, value=k).font = FUENTE_B
        c = info.cell(row=i, column=2, value=v)
        c.font = FUENTE_B if k == "EEFF con error" else FUENTE
        c.alignment = Alignment(wrap_text=True)
        if k == "EEFF con error" and errores:
            c.fill = FILL_DIF


def hoja_huerfanos(ws, datos, rut, anio, reportes):
    """Montos sin par del cruce (identificacion numerica del 04), de t y de t+1:
      PDF: montos de las paginas de estados que no calzan con ninguna cifra del XML; se busca la
           linea que los contiene (lectura espacial) para mostrar su glosa y columna.
      XML: cifras del XML que no se encontraron en el PDF (cuenta, serie y columna).
    Sirve de control de cobertura: lo que la lectura por lineas no tomo aparece aqui."""
    encab = ["Documento", "Pagina", "Columna", "Glosa (PDF) / cuenta (XML)", "Monto"]
    for j, t in enumerate(encab, 1):
        ws.cell(row=1, column=j, value=t).font = FUENTE_B
    filas = []
    for a, etiqueta in ((anio, "t"), (anio + 1, "t+1")):
        rep_a = reportes.get(a)
        co = rep_a.get("coords") if rep_a else None
        lineas = {}                                         # pagina -> filas espaciales
        # ECP: series en columnas -> la lectura espacial (2 columnas) no sirve; se usa la del 03d
        ecp_val = {}                                        # |monto| -> (columna, "fila [col -> serie]")
        if rep_a is not None and len(rep_a["ch"]):
            nombres = {k: n for k, n, _ in ECP_FILAS}
            pdf_ecp = ecp_pdf(rep_a["ch"])
            c_ecp = rep_a["cta"][rep_a["cta"]["estado_fin"] == "ECP"]
            for columna, ctx in (("actual", "PeriodoActual"), ("anterior", "PeriodoAnterior")):
                par = asociar_series(pdf_ecp.get(columna, {}), ecp_xml(c_ecp, ctx))
                for col, d in pdf_ecp.get(columna, {}).items():
                    for k, v in d.items():
                        if v:
                            ecp_val.setdefault(round(abs(v)), (columna, f"ECP {nombres.get(k, k)} "
                                                         f"[{col} -> {par.get(col, 'sin serie')}]"))
            pags_ecp = set(rep_a["ch"]["pagina"].dropna().astype(int))
        else:
            pags_ecp = set()
        hue = datos.hue[(datos.hue["rut"] == rut) & (datos.hue["anio"] == a)]
        for r in hue.drop_duplicates(["pagina", "monto_pdf"]).itertuples():
            glosa, col = "", ""
            pag = None if pd.isna(r.pagina) else int(r.pagina)
            if pag in pags_ecp:
                # pagina del ECP: solo la lectura del 03d (la espacial confunde series con columnas)
                col, glosa = ecp_val.get(round(abs(r.monto_pdf)),
                                         ("", "ECP: monto que el 03d no leyo (fila o serie sin lectura)"))
            elif co is not None and pag is not None and str(pag) in co["paginas"]:
                if pag not in lineas:
                    lineas[pag] = filas_espaciales(co["paginas"][str(pag)])[0]
                for g, x_act, x_ant, _ in lineas[pag]:
                    if x_act is not None and x_act and abs(abs(x_act) - abs(r.monto_pdf)) <= 1:
                        glosa, col = g, "actual"
                        break
                    if x_ant is not None and x_ant and abs(abs(x_ant) - abs(r.monto_pdf)) <= 1:
                        glosa, col = g, "anterior"
                        break
            filas.append((f"PDF {etiqueta} ({a})", pag, col, glosa or "(sin linea ubicada)", r.monto_pdf))
        det = datos.det[(datos.det["rut"] == rut) & (datos.det["anio"] == a) & (datos.det["estado"] == "no_encontrado")]
        for r in det.itertuples():
            serie = "" if pd.isna(r.serie) else f" [{r.serie}]"
            filas.append((f"XML {etiqueta} ({a})", None, CONTEXTOS.get(r.contexto, r.contexto).lower(),
                          legible(r.codigo) + serie, r.valor_xml))
    for i, f in enumerate(filas, 2):
        for j, v in enumerate(f, 1):
            c = ws.cell(row=i, column=j, value=None if v is None or (not isinstance(v, str) and pd.isna(v)) else v)
            c.font = FUENTE
            if j == 5:
                c.number_format = FMT_PDF
    if not filas:
        ws["A2"] = "(sin montos huerfanos en t ni en t+1)"
    for j, w in enumerate([18, 8, 10, 70, 18], 1):
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = w
    ws.freeze_panes = "A2"


def hoja_casos(wb, casos):
    ws = wb.create_sheet("Casos", 1)
    cols = ["caso_id", "tipo", "columna", "estado_raiz", "linea_raiz", "dif", "fuentes", "estados", "lineas", "pagina"]
    for j, t in enumerate(cols, 1):
        ws.cell(row=1, column=j, value=t).font = FUENTE_B
    for i, r in enumerate(casos[cols].itertuples(index=False), 2):
        for j, v in enumerate(r, 1):
            c = ws.cell(row=i, column=j, value=None if pd.isna(v) else v)
            c.font = FUENTE
            if cols[j - 1] == "dif":
                c.number_format = FMT_PDF
    for j, w in enumerate([10, 18, 10, 10, 40, 14, 22, 12, 80, 8], 1):
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = w


def generar(datos: Datos, rut: str, anio: int):
    enc_t = datos.enc[(datos.enc["rut"] == rut) & (datos.enc["anio"] == anio)]
    if enc_t.empty:
        print(f"  ! {rut} {anio}: no esta en encabezados.csv")
        return None
    enc = enc_t.iloc[0]
    cta = datos.cta[datos.cta["archivo"] == enc["archivo"]].copy()
    cta = cta[cta["valor"].notna() & cta["codigo"].notna()]      # algun XML trae cuentas sin codigo
    cta["estado_fin"] = asignar_secciones(cta["codigo"].tolist())   # orden del XML
    prev = datos.enc[(datos.enc["rut"] == rut) & (datos.enc["anio"] == anio - 1)]
    cta_orig = datos.cta[datos.cta["archivo"].isin(prev["archivo"])]
    det = datos.det[(datos.det["rut"] == rut) & (datos.det["anio"] == anio)]
    hue = datos.hue[(datos.hue["rut"] == rut) & (datos.hue["anio"] == anio)]
    res = datos.res[(datos.res["rut"] == rut) & (datos.res["anio"] == anio)]
    comp = Comparador(det, hue, cta_orig)
    casos = (datos.casos[(datos.casos["rut"] == rut) & (datos.casos["anio_doc"] == anio)]
             if len(datos.casos) else pd.DataFrame())
    casos_cod = {x.split("/")[0] for v in casos.get("lineas", pd.Series(dtype=str)).dropna()
                 for x in str(v).split(",")}
    pdf_nombre = res["pdf"].iloc[0] if len(res) and pd.notna(res["pdf"].iloc[0]) else None
    coords = cargar_coords(rut, anio, pdf_nombre) if pdf_nombre else None
    resumen = []

    def reporte(a):
        """cta (con estado), lineas del PDF por estado y lectura del ECP del 03d de un anio."""
        e = datos.enc[(datos.enc["rut"] == rut) & (datos.enc["anio"] == a)]
        if e.empty:
            return None
        c = datos.cta[(datos.cta["archivo"] == e.iloc[0]["archivo"])]
        c = c[c["valor"].notna() & c["codigo"].notna()].copy()
        c["estado_fin"] = asignar_secciones(c["codigo"].tolist())
        r = datos.res[(datos.res["rut"] == rut) & (datos.res["anio"] == a)]
        nom = r["pdf"].iloc[0] if len(r) and pd.notna(r["pdf"].iloc[0]) else None
        co = coords if a == anio else (cargar_coords(rut, a, nom) if nom else None)
        lin, rot = leer_reporte(co, r["paginas_estados"].iloc[0] if len(r) else None, c)
        ch = datos.ecp[(datos.ecp["rut"] == rut) & (datos.ecp["anio"] == a)]
        return dict(cta=c, lineas=lin, rotulos=rot, ch=ch, coords=co)
    rep_t, rep_t1, rep_tm1 = reporte(anio), reporte(anio + 1), reporte(anio - 1)

    wb = Workbook()
    info = wb.active
    info.title = "Fondo"
    pdf = res["pdf"].iloc[0] if len(res) and pd.notna(res["pdf"].iloc[0]) else ""
    pares = [
        ("Fondo", enc["nombre_fondo"]), ("RUT", rut), ("Anio", anio),
        ("AGF", enc["nombre_agf"]), ("Auditor", enc.get("auditor_firma")),
        ("Moneda", enc["moneda"]), ("XML", enc["archivo"]),
        ("XML t+1", _archivo(datos, rut, anio + 1)),
        ("XML t-1", (prev["archivo"].iloc[0] if len(prev) else "(no disponible)")
                    + "   (solo en hojas 'cruce': columna Original)"),
        ("PDF", str(CMF_HOME / "archivos" / rut / str(anio) / pdf) if pdf else ""),
        ("PDF t+1", _pdf(datos, rut, anio + 1)),
        ("Paginas de estados en el PDF", res["paginas_estados"].iloc[0] if len(res) else ""),
        ("Titulo impreso de otro estado", "; ".join(f"pag. {p}: {e} bajo el titulo de {t}"
                                                    for p, (e, t) in sorted(rep_t["rotulos"].items()))
                                          or "(no)"),
        ("% encontrado (tolerante)", res["pct_tolerante"].iloc[0] if len(res) else ""),
        ("", ""),
        ("Como leer", ""),
        ("Hojas 'cruce'", "solo si no hay lectura por lineas del PDF: identificacion numerica (cruce del "
                          "04), parte del XML y busca cada monto en el PDF sin saber en que linea esta"),
        ("Huerfanos", "montos sin par del cruce en t y t+1: del PDF (con la glosa de su linea) y del XML "
                      "(cuenta no encontrada en el PDF). Control de lo que la lectura por lineas no tomo"),
        ("  PDF", "valor del PDF segun el cruce. Si no se encontro, se PROPONE el monto huerfano "
                  "mas cercano (<=10%), con su pagina: es una pista, confirmar en el PDF"),
        ("  Original t-1", "columna Actual del XML del reporte anterior (solo periodo Anterior)"),
        ("  rojo", "cifra del XML no encontrada en el PDF (PDF = propuesta o '?')"),
        ("  naranja", "monto encontrado con signo distinto"),
        ("  amarillo", "encontrado con diferencia de redondeo (+-1)"),
        ("  morado", "el comparativo difiere del original publicado el anio anterior"),
        ("", ""),
        ("Hojas 'forma'", "lineas leidas del PDF frente a las cuentas del XML: coinciden por glosa, "
                          "solo por valor (glosa distinta) y sin coincidencia. Al final, cada subtotal e "
                          "identidad: impreso, suma de partes (formula) y diferencia"),
        ("  azul", "subtotal / identidad"),
        ("  rosado", "cuenta que forma parte de un caso del 04c (hoja Casos)"),
        ("  rojo (Dif)", "PDF y XML difieren mas que el redondeo"),
    ]
    for i, (k, v) in enumerate(pares, 1):
        info.cell(row=i, column=1, value=k).font = FUENTE_B
        c = info.cell(row=i, column=2, value=None if pd.isna(v) else v)
        c.font = FUENTE
        c.alignment = Alignment(wrap_text=True)
    etiquetas = [p[0] for p in pares]
    for k, fill in (("  rojo", COLORES["no_encontrado"]), ("  naranja", COLORES["signo_distinto"]),
                    ("  amarillo", COLORES["ok_redondeo"]), ("  morado", COLOR_ORIGINAL)):
        info.cell(row=etiquetas.index(k) + 1, column=1).fill = fill
    info.column_dimensions["A"].width = 30
    info.column_dimensions["B"].width = 90

    for est in ESTADOS:
        ws = wb.create_sheet(est)
        parte = cta[cta["estado_fin"] == est]
        if parte.empty:
            ws["A1"] = "(sin cuentas en el XML para este estado)"
            continue
        ch = datos.ecp[(datos.ecp["rut"] == rut) & (datos.ecp["anio"] == anio)]
        if est == "ECP" and len(ch):
            ws.title = "ECP forma"
            resumen.append(hoja_ecp_forma(ws, ch, parte, casos_cod))
        elif est != "ECP" and est in rep_t["lineas"]:
            ws.title = f"{est} forma"
            resumen.append(hoja_forma(ws, est, parte, *rep_t["lineas"][est], casos_cod))
        else:                       # sin lectura por lineas: vista del cruce (identificacion numerica)
            ws.title = f"{est} cruce"
            (hoja_ecp if est == "ECP" else hoja_estado)(ws, parte, comp)
    if len(casos):
        hoja_casos(wb, casos)
    # Dos comparativos: el periodo t frente al reporte t+1 (su columna anterior) y el periodo t-1
    # que presenta t (columna anterior) frente al reporte t-1 (su columna actual)
    txt, err_t1 = hoja_t1(wb.create_sheet(f"t+1 ({anio + 1})"), rep_t, rep_t1, anio)
    txt_m, err_tm1 = hoja_t1(wb.create_sheet(f"t-1 ({anio - 1})"), rep_tm1, rep_t, anio - 1)
    resumen += [txt_m, txt]
    errores = None if err_t1 is None and err_tm1 is None else (err_tm1 or []) + (err_t1 or [])
    resumen_fondo(info, errores, casos, anio)
    # orden: resumen, casos, comparativos, los estados leidos del PDF y al final las vistas del cruce
    orden = ["Fondo", "Casos", f"t-1 ({anio - 1})", f"t+1 ({anio + 1})", "ESF forma", "ERI forma", "ECP forma", "EFE forma"]
    hojas = {w.title: w for w in wb.worksheets}
    wb._sheets = [hojas[n] for n in orden if n in hojas] + [w for w in wb.worksheets if w.title not in orden]

    hoja_huerfanos(wb.create_sheet("Huerfanos"), datos, rut, anio, {anio: rep_t, anio + 1: rep_t1})

    DIR_FICHAS.mkdir(parents=True, exist_ok=True)
    ruta = DIR_FICHAS / f"{rut}_{anio}.xlsx"
    wb.save(ruta)
    for r in resumen:
        print(f"    {r}")
    return ruta


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--muestra":
        m = pd.read_excel(MUESTRA, sheet_name="Muestra", dtype={"rut": str})
        claves = list(zip(m["rut"], m["anio"].astype(int)))
    elif len(sys.argv) == 3 and sys.argv[1] == "--planilla":
        m = pd.read_excel(sys.argv[2], dtype={"rut": str})
        claves = list(dict.fromkeys(zip(m["rut"], m["anio"].astype(int))))
    elif len(sys.argv) == 3:
        claves = [(sys.argv[1], int(sys.argv[2]))]
    else:
        print(__doc__)
        return 1

    datos = Datos(claves)
    for rut, anio in claves:
        try:
            ruta = generar(datos, rut, anio)
        except Exception as e:                       # una ficha que falla no corta el lote
            print(f"  ! {rut} {anio}: {type(e).__name__}: {e}")
            continue
        if ruta:
            print(f"  {rut} {anio} -> {ruta.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())