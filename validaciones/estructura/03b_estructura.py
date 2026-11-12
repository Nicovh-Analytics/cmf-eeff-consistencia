"""
Pasada estructural del PDF: subtotales del ESF, la ERI y el EFE, e identidades del EFE
=====================================================================================

Complementa al cruce por numeros (03/04). Aquel busca si cada cifra del XML
APARECE en el PDF; tiene un punto ciego: si el valor equivocado del PDF
coincide con otra cifra del XML, no queda huerfano y el error no forma par.

Lectura y emparejamiento: el lector unificado (comun/lector.py + comun/emparejar.py),
el mismo de la ficha. Cada renglon del PDF ya trae su cuenta del XML (glosa y valor,
glosa sola o valor solo; uno a uno). Sobre eso:
  1. Subtotal = el renglon de su codigo. metodo: glosa_y_valor / valor (rotulo distinto)
     / solo_glosa (el valor impreso difiere del XML).
  2. Componentes = renglones con montos entre el subtotal anterior del mismo estado y el
     subtotal; un renglon de otro subtotal o identidad corta, y una linea "subtotal/total"
     sin cuenta propia justo encima del subtotal con sus mismos montos se salta.
  3. Por columna:
       pdf_suma   = el subtotal impreso es la suma de sus lineas?
       igual_xml  = el subtotal impreso es igual al del XML?
       n lineas   = lineas distintas de cero en PDF vs codigos en XML
       agregacion = cifra del XML que es la suma de 2-3 lineas del PDF sin par
  4. Identidades del EFE (aumento neto, evolucion del efectivo) con los renglones de sus codigos.
  5. Clasificacion de los que no suman: probable_error / _tipeo /
     _linea_no_sumada, probable_lectura, revisar_linea_faltante.

Lee:      data/procesado/cruce_resumen.csv, encabezados.csv, cuentas.csv
          data/coords_pdf/...                  (03a_coordenadas.py, 03a_ocr.py)
Escribe:  data/procesado/estructura_efe.csv          1 fila por fondo-anio-subtotal-columna
          data/procesado/renglones_pdf.csv           renglones del lector ya emparejados (03f; rotulos en el 04c)
          data/procesado/estructura_efe_no_suma.csv  los que no suman, clasificados
"""

import itertools
import re
import sys
from pathlib import Path

import pandas as pd

from config import casos_conocidos, umbral_materialidad, CMF_HOME
from comun.emparejar import leer_y_emparejar
from comun.lector_espacial import cargar_coords
from comun.secciones import asignar_secciones

BASE_DIR = Path(__file__).resolve().parent
DIR_PROC = CMF_HOME / "procesado"

TOL = 2                     # diferencia tolerada al sumar lineas (redondeo)

MAX_PARTES_AGREGACION = 3   # una cifra XML puede ser suma de hasta 3 lineas PDF

# Subtotales del EFE: codigo XML, glosa esperada en el PDF, codigos componentes.
SUBTOTALES = {
    "operacion": dict(
        estado="EFE",
        codigo="FlujoNetoOriginadoPorActividadesDeLaOperacion",
        glosa=re.compile(r"flujo.*operaci", re.I),
        partes=["CompraDeActivosFinancieros", "VentaCobroDeActivosFinancieros",
                "InteresesDiferenciasDeCambioYReajustesRecibidos",
                "LiquidacionDeInstrumentosFinancierosDerivados", "DividendosRecibidos",
                "MontosPagadosASociedadAdministradoraEIntermediarios",
                "MontosRecibidosDeSociedadAdministradoraEIntermediarios",
                "OtrosIngresosDeOperacion", "OtrosGastosDeOperacionPagados"]),
    "financiamiento": dict(
        estado="EFE",
        codigo="FlujoNetoOriginadoPorActividadesDeFinanciamiento",
        glosa=re.compile(r"flujo.*financiamiento", re.I),
        partes=["ColocacionDeCuotasEnCirculacion", "RescatesDeCuotasEnCirculacion", "Otros"]),
    # DistribucionDeBeneficios NO va como parte: es el mismo codigo del ERI/ECP y
    # tapaba un caso conocido de agregacion (distribuciones metidas en Otros del EFE).,
    # --- ESF ---
    "total_activo": dict(
        estado="ESF",
        codigo="TotalActivo", glosa=re.compile(r"totalactivos?(?!neto)", re.I),
        partes=["EfectivoYEfectivoEquivalente", "ActivosFinancierosAValorRazonableConEfectoEnResultados",
                "ActivosFinancierosAValorRazonableConEfectoEnResultadosEntregadosEnGarantia",
                "ActivosFinancierosACostoAmortizado", "CuentasPorCobrarAIntermediarios",
                "OtrasCuentasPorCobrar", "OtrosActivos"]),
    "total_pasivo": dict(
        estado="ESF",
        codigo="TotalPasivo", glosa=re.compile(r"totalpasivos?", re.I),
        partes=["PasivosFinancierosAValorRazonableConEfectoEnResultados", "CuentasPorAPagarIntermediarios",
                "RescatesPorPagar", "RemuneracionesSociedadAdministradora",
                "OtrosDocumentosYCuentasPorPagar", "OtrosPasivos"]),
    # --- ERI ---
    "total_ingresos": dict(
        estado="ERI",
        codigo="TotalIngresosPerdidasNetosDeLaOperacion", glosa=re.compile(r"otal,?(de)?\(?(p[eé]rdidas?\)?/?)?ingresos?", re.I),
        partes=["InteresesYReajustes", "IngresosPorDividendos",
                "DiferenciasDeCambioNetasSobreActivosFinancierosACostoAmortizado",
                "DiferenciasDeCambioNetasSobreEfectivoYEfectivoEquivalente",
                "CambiosNetosEnValorRazonableDeActivosYPasivosFinancierosAValorRazonableConEfectoEnResultados",
                "ResultadoEnVentaDeInstrumentosFinancieros", "OtrosEri"]),
    "total_gastos": dict(
        estado="ERI",
        codigo="TotalGastosDeOperacion", glosa=re.compile(r"totalgastos", re.I),
        partes=["ComisionDeAdministracion", "HonorariosPorCustodiaYAdministracion",
                "CostosDeTransaccion", "OtrosGastosDeOperacion"]),
}

# Las regex se aplican sobre el texto SIN espacios (norm): hay PDFs que se
# extraen pegados ("Flujonetoutilizadoenactividades...") y con \s+ no calzaban.
def norm(s):
    return re.sub(r"\s+", "", s).lower()

# Glosa de un subtotal o total sin cuenta propia ("Subtotal ajustes", "Subtotal efectivo utilizado
# en operaciones", "Aumento (disminucion) de activo neto..." en un EFE indirecto): corta los componentes.
RE_SUBTOTAL = re.compile(r"flujos?netos?|aumento|disminuci|saldo(inicial|final)|total")
METODO = {"ambos": "glosa_y_valor", "valor": "valor", "glosa": "solo_glosa"}
RE_AJENA = re.compile(r"activos?netos?atribuible")


def corrido_vecino(L, i, idx, x_tot):
    """El subtotal impreso no es el del XML pero la linea de al lado si lo trae: montos corridos
    una linea respecto de su glosa que el lector no pudo corregir. Un no-suma ahi es lectura."""
    if not x_tot or abs(abs(L[i][idx] or 0) - abs(x_tot)) <= TOL:
        return False
    return any(0 <= k < len(L) and L[k][idx] is not None and abs(abs(L[k][idx]) - abs(x_tot)) <= TOL
               for k in (i - 1, i + 1))


def lineas_estado(rs):
    """Renglones con montos de un estado (sin encabezados), en orden:
    (glosa, actual, anterior, glosa_ext, pagina, codigo, coincide, metodo)."""
    out = []
    for r in rs:
        if r["metodo"] == "encabezado" or (r["actual"] is None and r["anterior"] is None):
            continue
        out.append((r["glosa"], r["actual"] if r["actual"] is not None else 0, r["anterior"],
                    (r["previa"] + " " + r["glosa"]).strip(), r["pagina"], r["codigo"], r["coincide"],
                    r["metodo"]))
    return out


def componentes(lin, i_sub, cortes, fechas=frozenset(), partes=frozenset()):
    """Lineas con montos sobre el subtotal, dentro del estado, hasta el renglon de otro
    subtotal o identidad (cortes: sus codigos) o una linea "subtotal/total" sin cuenta propia.
    Esa linea se salta si esta justo encima y repite los montos del subtotal (o va en 0).
    fechas: anios del documento y dias de cierre; una linea sin cuenta cuyos montos son solo eso es
    un encabezado de fecha que el lector no marco ("31 | 2015", "2012") y no se suma."""
    propios = {abs(v) for v in lin[i_sub][1:3] if v}
    comp = []
    for j in range(i_sub - 1, -1, -1):
        glosa, a, b, _, _, cod, _, _ = lin[j]
        if cod in cortes:
            break
        # el activo neto atribuible no es parte de ningun subtotal del ESF/ERI/EFE: es una linea del
        # ECP (o del ESF) que quedo dentro del estado (pagina compartida sin titulo)
        if RE_AJENA.search(norm(glosa)):
            break
        # una linea "total/subtotal/flujo neto" que no es parte de este subtotal corta, aunque el
        # emparejador le haya dado otra cuenta ("Total activos" sobre el bloque del pasivo)
        if cod not in partes and RE_SUBTOTAL.search(norm(glosa)):
            nums = {abs(v) for v in (a, b) if v}
            if not comp and nums <= propios:
                continue
            break
        vals = {abs(v) for v in (a, b) if v}
        if not cod and vals and vals <= fechas:
            continue
        comp.append((glosa, a, b, lin[j][7]))
    return list(reversed(comp))


def buscar_agregacion(faltan_xml, sobran_pdf):
    """Cifras XML que son la suma de 2..MAX_PARTES lineas PDF sin par."""
    hallazgos = []
    sobran = [v for v in sobran_pdf if v]
    for v in faltan_xml:
        for k in range(2, MAX_PARTES_AGREGACION + 1):
            for combo in itertools.combinations(sobran, k):
                if abs(sum(combo) - v) <= TOL:
                    hallazgos.append(f"{v}={'+'.join(map(str, combo))}")
                    break
            else:
                continue
            break
    return hallazgos

# Identidades internas del EFE (entre flujos, no linea a linea). partes: subtotales del EFE ya
# ubicados o lineas sueltas (LINEAS_EFE). Se ubican como los subtotales: glosa y valor del XML;
# si el valor no calza, por glosa unica (un aumento neto mal impreso no debe quedar fuera).
IDENTIDADES_EFE = {
    "aumento_neto": dict(
        estado="EFE", codigo="AumentoNetoDeEfectivoYEfectivoEquivalente",
        glosa=re.compile(r"(aumento|disminuci).*efectivo", re.I), partes=["operacion", "financiamiento"]),
    "evolucion_efectivo": dict(
        estado="EFE", codigo="SaldoFinalDeEfectivoYEfectivoEquivalente",
        glosa=re.compile(r"saldofinal", re.I), partes=["saldo_inicial", "aumento_neto", "dif_cambio"]),
}
LINEAS_EFE = {
    "saldo_inicial": ("SaldoInicialDeEfectivoYEfectivoEquivalente", re.compile(r"saldoinicial", re.I)),
    "dif_cambio": ("DiferenciasDeCambioNetasSobreEfectivoYEfectivoEquivalente",
                   re.compile(r"diferencias?decambio.*efectivo", re.I)),
}


# Codigos que cortan los componentes, por estado: los subtotales del estado y, en el EFE, las
# lineas de las identidades. La diferencia de cambio sobre efectivo es parte del ERI (ingresos)
# y linea de identidad del EFE: con un solo conjunto cortaba los ingresos de la ERI.
CORTES = {est: {cfg["codigo"] for cfg in SUBTOTALES.values() if cfg["estado"] == est} for est in ("ESF", "ERI", "EFE")}
CORTES["EFE"] |= {cfg["codigo"] for cfg in IDENTIDADES_EFE.values()} | {v[0] for v in LINEAS_EFE.values()}


def analizar_fondo(renglones, xml, espaciadas, ocr, anio=None):
    """renglones: {estado: renglones del lector ya emparejados}; xml: (contexto, codigo) -> valor.
    espaciadas / ocr: paginas con letras sueltas / leidas por OCR (ahi un no-suma es lectura)."""
    lin = {est: lineas_estado(rs) for est, rs in renglones.items()}
    irregulares = []
    filas, ubic = [], {}
    for nombre, cfg in SUBTOTALES.items():
        x_act = xml.get(("PeriodoActual", cfg["codigo"]))
        x_ant = xml.get(("PeriodoAnterior", cfg["codigo"]))
        if x_act is None:
            continue
        L = lin.get(cfg["estado"], [])
        i = next((k for k, l in enumerate(L) if l[5] == cfg["codigo"]), None)
        if i is None:
            filas.append(dict(subtotal=nombre, ubicado=False))
            continue
        ubic[nombre] = i
        metodo = METODO[L[i][6]]
        _, s_act, s_ant, _, pag, _, _, met = L[i]
        fechas = ({anio, anio - 1, anio + 1, 28, 29, 30, 31} if anio else set())
        comp = componentes(L, i, CORTES[cfg["estado"]] - {cfg["codigo"]}, fechas, set(cfg["partes"]))
        # montos corridos que el lector corrigio en el bloque: un no-suma ahi es lectura
        corregido = met.startswith("corrido") or any(c[3].startswith("corrido") for c in comp)
        for col, x_tot, s_pdf, idx in (("actual", x_act, s_act, 1), ("anterior", x_ant, s_ant, 2)):
            if x_tot is None or s_pdf is None:
                continue
            ctx = "PeriodoActual" if col == "actual" else "PeriodoAnterior"
            vals_pdf = [c[idx] for c in comp if c[idx] is not None]
            suma = sum(vals_pdf)
            xml_partes = [xml.get((ctx, c), 0) or 0 for c in cfg["partes"]]
            # Convencion de presentacion: el PDF puede mostrar pagos sin parentesis
            # bajo un titulo "menos". Se repite la suma usando el signo del XML
            # para las lineas cuyo valor absoluto calza con una parte del XML.
            signo_xml = {abs(v): (1 if v >= 0 else -1) for v in xml_partes if v}
            suma_sx = sum(signo_xml.get(abs(v), 1 if v >= 0 else -1) * abs(v) for v in vals_pdf)
            s_sx = (1 if x_tot >= 0 else -1) * abs(s_pdf)
            nz_pdf = [abs(v) for v in vals_pdf if v]
            nz_xml = [abs(v) for v in xml_partes if v]
            faltan = [v for v in nz_xml if v not in nz_pdf]
            sobran = [v for v in nz_pdf if v not in nz_xml]
            # Marca por linea en el detalle: "~" = el valor es una parte del XML
            # pero de la OTRA columna; "?" = no es ninguna parte del XML;
            # "#" = difiere de una parte del XML faltante por un error de tipeo.
            ctx_otro = "PeriodoAnterior" if col == "actual" else "PeriodoActual"
            otra_col = {abs(xml.get((ctx_otro, c), 0) or 0) for c in cfg["partes"]} - {0}
            def marca(v):
                if not v or abs(v) in nz_xml:
                    return ""
                if any(es_typo(v, x) for x in faltan):
                    return "#"          # mismo largo que una cifra XML faltante, 1 digito distinto o 2 contiguos permutados
                return "~" if abs(v) in otra_col else "?"
            filas.append(dict(
                pagina_ocr=pag in ocr,
                subtotal=nombre, ubicado=True, columna=col, pagina=pag,
                pagina_espaciada=pag in espaciadas,
                corrido_vecino=corregido or corrido_vecino(L, i, idx, x_tot),
                glosa_esperada=metodo != "valor",   # False: ubicado por valor, rotulo distinto
                formato_irregular=" ".join(irregulares), metodo=metodo,
                subtotal_pdf=s_pdf, subtotal_xml=x_tot, suma_lineas_pdf=suma,
                pdf_suma=abs(suma - s_pdf) <= TOL,
                pdf_suma_signo_xml=abs(suma_sx - s_sx) <= TOL,
                igual_xml=abs(abs(s_pdf) - abs(x_tot)) <= TOL,
                n_lineas_pdf=len(nz_pdf), n_lineas_xml=len(nz_xml),
                faltan_xml=len(faltan), sobran_pdf=len(sobran),
                agregacion="; ".join(buscar_agregacion(faltan, sobran)),
                detalle=" | ".join(f"{c[0][:30]}={c[idx]}{marca(c[idx])}" for c in comp if c[idx] is not None)))
    filas += identidades_efe(lin.get("EFE", []), xml, ubic, espaciadas, ocr)
    return filas


def identidades_efe(L, xml, ubic, espaciadas, ocr):
    """Filas de estructura_efe para IDENTIDADES_EFE, con el mismo esquema que un subtotal:
    subtotal_pdf = total impreso, suma_lineas_pdf = suma de sus partes impresas. Cada parte es el
    renglon de su codigo (el emparejador ya resolvio glosas partidas, montos corridos y "una linea,
    una cuenta", que en la version anterior eran los parches v4-v7). Sin el EFE ubicado, no hay filas."""
    if "operacion" not in ubic and "financiamiento" not in ubic:
        return []
    pos = {k: v for k, v in ubic.items() if SUBTOTALES[k]["estado"] == "EFE"}
    de_codigo = {l[5]: k for k, l in enumerate(L) if l[5]}
    for nombre, (codigo, _) in LINEAS_EFE.items():
        if codigo in de_codigo:
            pos[nombre] = de_codigo[codigo]
    for nombre, cfg in IDENTIDADES_EFE.items():
        if cfg["codigo"] in de_codigo:
            pos[nombre] = de_codigo[cfg["codigo"]]
    codigo_de = {**{k: v["codigo"] for k, v in SUBTOTALES.items()},
                 **{k: v[0] for k, v in LINEAS_EFE.items()},
                 **{k: v["codigo"] for k, v in IDENTIDADES_EFE.items()}}
    filas = []
    for nombre, cfg in IDENTIDADES_EFE.items():
        if nombre not in pos or xml.get(("PeriodoActual", cfg["codigo"])) is None:
            filas.append(dict(subtotal=nombre, ubicado=False))
            continue
        i = pos[nombre]
        metodo, pag = METODO[L[i][6]], L[i][4]
        for col, idx, ctx in (("actual", 1, "PeriodoActual"), ("anterior", 2, "PeriodoAnterior")):
            x_tot, s_pdf = xml.get((ctx, cfg["codigo"])), L[i][idx]
            if x_tot is None or s_pdf is None:
                continue
            vals, det, falta = [], [], False
            for p in cfg["partes"]:
                x_crudo = xml.get((ctx, codigo_de[p]))
                x_p = x_crudo or 0
                if p in pos and L[pos[p]][idx] is not None:
                    v = L[pos[p]][idx]
                elif not x_p and (p == "dif_cambio" or x_crudo is not None):
                    # en cero en el XML (p.ej. saldo inicial de un fondo nuevo) -> 0; si el XML no
                    # trae la cuenta, solo la diferencia de cambio puede faltar
                    v = 0
                else:
                    # las demas partes son obligatorias aunque el XML no las traiga (plantilla sin
                    # "aumento neto": no se evalua el saldo final en vez de sumarla como 0)
                    falta = True
                    continue
                vals.append((p, v, x_p))
                det.append(f"{p}={v}" + ("" if not v or abs(abs(v) - abs(x_p)) <= TOL else "?"))
            if falta:
                continue
            suma = sum(v for _, v, _ in vals)
            sx = sum((1 if x_p >= 0 else -1) * abs(v) if x_p else v for _, v, x_p in vals)
            s_sx = (1 if x_tot >= 0 else -1) * abs(s_pdf)
            nz_pdf = [abs(v) for _, v, _ in vals if v]
            nz_xml = [abs(x) for _, _, x in vals if x]
            filas.append(dict(
                pagina_ocr=pag in ocr, subtotal=nombre, ubicado=True, columna=col,
                pagina=pag, pagina_espaciada=pag in espaciadas, corrido_vecino=corrido_vecino(L, i, idx, x_tot),
                glosa_esperada=metodo != "valor", formato_irregular="", metodo=metodo,
                subtotal_pdf=s_pdf, subtotal_xml=x_tot, suma_lineas_pdf=suma,
                pdf_suma=abs(suma - s_pdf) <= TOL, pdf_suma_signo_xml=abs(sx - s_sx) <= TOL,
                igual_xml=abs(abs(s_pdf) - abs(x_tot)) <= TOL,
                n_lineas_pdf=len(nz_pdf), n_lineas_xml=len(nz_xml),
                faltan_xml=len([v for v in nz_xml if v not in nz_pdf]),
                sobran_pdf=len([v for v in nz_pdf if v not in nz_xml]),
                agregacion="", detalle=" | ".join(det)))
    return filas


CASOS_CONOCIDOS = casos_conocidos("03b")      # privado: verificacion/casos_conocidos.csv


def es_typo(v, x):
    """v y x tienen el mismo numero de digitos y difieren en 1 digito o en 2
    digitos contiguos permutados. Un monto partido mal
    leido pierde digitos (largo distinto), asi que no califica."""
    a, b = str(abs(int(v))), str(abs(int(x)))
    if len(a) != len(b) or a == b:
        return False
    d = [k for k in range(len(a)) if a[k] != b[k]]
    return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])


def patron_dif(d):
    """Forma de la diferencia suma-impreso: un digito (d*10^k), transposicion
    (multiplo de 9), redondeo (<=10) u otra."""
    d = abs(int(d))
    if d <= 10:
        return "redondeo"
    if len(str(d).rstrip("0")) == 1:
        return "un_digito"
    if d % 9 == 0:
        return "transposicion"
    return "otra"


def clasificar(df):
    """Para cada subtotal-columna que no suma de ninguna forma:
      probable_lectura: alguna linea no es cifra del XML ('?' o '~') -- lo mas
        probable es que la hayamos leido mal; o el bloque esta vacio.
      revisar_linea_faltante: todas las lineas leidas son cifras del XML pero
        hay menos lineas que en el XML (puede faltar una que no capturamos).
      probable_error: todas las lineas son cifras del XML, estan todas, y aun
        asi no suman al subtotal impreso -> el PDF no suma.
    tasa_agf: % de no_suma de la AGF (prior: AGF con tasa baja -> mas creible)."""
    ub = df[df["ubicado"] == True].copy()
    ns = ~ub["pdf_suma"].astype(bool) & ~ub["pdf_suma_signo_xml"].astype(bool)
    tasa = ns.groupby(ub["nombre_agf"]).mean().mul(100).round(1)
    c = ub[ns].copy()
    det = c["detalle"].fillna("")
    vacio = det.eq("")
    ruido = det.str.contains(r"[?~](?: \||$)", regex=True)
    typo = det.str.contains(r"#(?: \||$)", regex=True)
    falta = c["n_lineas_pdf"] < c["n_lineas_xml"]
    c["clase"] = "probable_error"
    c.loc[falta, "clase"] = "revisar_linea_faltante"
    c.loc[ruido | vacio, "clase"] = "probable_lectura"
    # Linea con tipeo respecto del XML y sin otro ruido: el PDF difiere del XML
    # en esa linea y no suma (p.ej. una venta con un digito distinto).
    c.loc[typo & ~ruido & ~vacio, "clase"] = "probable_error_tipeo"
    # Linea impresa que no entra al subtotal: UNA sola linea fuera del XML, con
    # separador de miles (no es nota), y la diferencia es exactamente esa linea
    # (p.ej. dividendos que no corresponden impresos en el comparativo).
    def no_sumada(r):
        lineas = [x.rsplit("=", 1) for x in str(r.detalle).split(" | ") if "=" in x]
        # Solo "?" con glosa: "~" con subtotal 0 es un fondo en su primer anio
        # con un monto asignado a la columna anterior,
        # y una linea sin glosa es un monto suelto.
        if r.subtotal_pdf == 0 or any(v.endswith("~") for _, v in lineas):
            return False
        raras = [(g, v) for g, v in lineas if v.endswith("?")]
        if len(raras) != 1 or not raras[0][0].strip():
            return False
        v = abs(float(raras[0][1].rstrip("?~#")))
        return v >= 1000 and abs(abs(r.suma_lineas_pdf - r.subtotal_pdf) - v) <= TOL
    c.loc[c.apply(no_sumada, axis=1), "clase"] = "probable_error_linea_no_sumada"
    c["dif"] = (c["suma_lineas_pdf"] - c["subtotal_pdf"]).round(0)
    c["patron"] = c["dif"].map(patron_dif)
    c["tasa_agf_pct"] = c["nombre_agf"].map(tasa)
    # Linea distinta con total correcto: total impreso = XML y la suma de lineas difiere poco
    # (< 5% del total). Un error de lectura produce diferencias groseras (lineas que faltan,
    # digitos pegados); un error de digitacion en una linea, una diferencia chica.
    # Muestra v2 (35 casos lectura/linea faltante): separa 5/5 errores y 0/28 lecturas (en muestra).
    rel = (c["suma_lineas_pdf"] - c["subtotal_pdf"]).abs() / c["subtotal_pdf"].abs().clip(lower=1)
    linea = (c["clase"].isin(["probable_lectura", "revisar_linea_faltante"])
             & c["igual_xml"].fillna(False).astype(bool) & (rel < 0.05))
    c.loc[linea, "clase_detalle"] = c.loc[linea, "clase"]
    c.loc[linea, "clase"] = "probable_error_linea_distinta"
    # Bajo el umbral de materialidad: observacion, sin revision (la clase
    # original queda en clase_detalle).
    umbral = c["moneda"].map(umbral_materialidad)      # config.py
    c["clase_detalle"] = c["clase"]
    c.loc[c["dif"].abs() <= umbral, "clase"] = "observacion_inmaterial"
    cols = ["rut", "anio", "nombre_agf", "moneda", "subtotal", "columna", "clase", "clase_detalle", "patron", "dif",
            "subtotal_pdf", "suma_lineas_pdf", "subtotal_xml", "igual_xml", "tasa_agf_pct", "detalle"]
    if "pagina_espaciada" in c:
        baja = c["pagina_espaciada"].fillna(False).astype(bool) & c["clase"].str.startswith("probable_error")
        c.loc[baja, "clase_detalle"] = c.loc[baja, "clase"]       # se conserva la clase original
        c.loc[baja, "clase"] = "probable_lectura"
    # diferencia imposible (digitos de OCR pegados en una cifra): lectura
    absurda = c["dif"].abs() > 1e13
    c.loc[absurda, "clase_detalle"] = c.loc[absurda, "clase"]
    c.loc[absurda, "clase"] = "probable_lectura"
    if "corrido_vecino" in c:
        baja = c["corrido_vecino"].fillna(False).astype(bool) & c["clase"].str.startswith("probable_error")
        c.loc[baja, "clase_detalle"] = c.loc[baja, "clase"] + "/corrido_vecino"
        c.loc[baja, "clase"] = "probable_lectura"
    if "pagina_ocr" in c:
        baja = c["pagina_ocr"].fillna(False).astype(bool)
        c.loc[baja, "clase_detalle"] = c.loc[baja, "clase"]
        c.loc[baja, "clase"] = "probable_lectura_ocr"
    return c[cols].sort_values(["clase", "tasa_agf_pct", "rut", "anio"])




def main():
    res = pd.read_csv(DIR_PROC / "cruce_resumen.csv", dtype={"rut": str})
    enc = pd.read_csv(DIR_PROC / "encabezados.csv", dtype={"rut": str})
    enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "archivo", "moneda"]]
    # mismo universo que el lector: tambien los que el 03 no ubico por cifras (se leen por titulo)
    ok = (res[res["estado"].isin(["ok", "sin_texto", "sin_paginas_de_estados"]) & res["pdf"].notna()]
          .drop(columns=["moneda"], errors="ignore").merge(enc, on=["rut", "anio"]))

    # Todas las cuentas del archivo: el emparejador necesita el estado completo, no solo los subtotales
    cta = pd.read_csv(DIR_PROC / "cuentas.csv",
                      usecols=["archivo", "contexto", "codigo", "serie", "valor"], dtype={"serie": str})
    cta = cta[cta["archivo"].isin(ok["archivo"]) & cta["codigo"].notna() & cta["valor"].notna()]
    cta_de = dict(tuple(cta.groupby("archivo", sort=False)))

    filas, renglones_out, sin_coords = [], [], 0
    for r in ok.itertuples(index=False):
        coords = cargar_coords(r.rut, r.anio, r.pdf)
        if coords is None:
            sin_coords += 1         # sin cache del 03a (o PDF con error)
            continue
        c = cta_de.get(r.archivo)
        if c is None:
            continue
        c = c.copy()
        c["estado_fin"] = asignar_secciones(c["codigo"].tolist())     # orden del XML
        renglones, paginas = leer_y_emparejar(coords, r.paginas_estados, c)
        for est, rs in renglones.items():
            renglones_out += [dict(rut=r.rut, anio=r.anio, estado=est, pagina=q["pagina"], glosa=q["glosa"],
                                   actual=q["actual"], anterior=q["anterior"], codigo=q.get("codigo"),
                                   coincide=q.get("coincide"), metodo=q["metodo"], rotulo=q.get("rotulo"),
                                   glosa_de=q.get("glosa_de")) for q in rs]
        sx = c[c["serie"].isna()]
        xml = {(ctx, k): v for ctx, k, v in zip(sx["contexto"], sx["codigo"], sx["valor"])}
        # Pagina "espaciada": mas de la mitad de las palabras son de 1 caracter (letras y digitos
        # sueltos, a veces en capas superpuestas). Ahi un no-suma es lectura.
        espaciadas, ocr = set(), set()
        for p in paginas:
            pg = coords["paginas"].get(str(p), {})
            pal = pg.get("palabras", [])
            if pal and sum(len(w[0]) == 1 for w in pal) / len(pal) > 0.5:
                espaciadas.add(p)
            if pg.get("origen") == "ocr":
                ocr.add(p)
        for f in analizar_fondo(renglones, xml, espaciadas, ocr, int(r.anio)):
            filas.append({"rut": r.rut, "anio": r.anio, "nombre_agf": r.nombre_agf, "moneda": r.moneda, **f})

    df = pd.DataFrame(filas)
    df.to_csv(DIR_PROC / "estructura_efe.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(renglones_out).to_csv(DIR_PROC / "renglones_pdf.csv", index=False, encoding="utf-8-sig")
    cand = clasificar(df)
    cand.to_csv(DIR_PROC / "estructura_efe_no_suma.csv", index=False, encoding="utf-8-sig")

    # --- Consola ---
    if sin_coords:
        print(f"fondo-anio sin coordenadas (correr 03a_coordenadas.py): {sin_coords}")
    fondos = df[["rut", "anio"]].drop_duplicates()
    ub = df[df["ubicado"]]
    print(f"fondo-anio analizados: {len(fondos)}")
    print("subtotales ubicados en el PDF:")
    print(df.groupby("subtotal")["ubicado"].mean().mul(100).round(1).to_string(), "\n")
    if "glosa_esperada" in ub:
        rot = ub[ub["glosa_esperada"] == False][["rut", "anio", "subtotal"]].drop_duplicates()
        print(f"ubicados por valor con rotulo distinto al esperado: {len(rot)} "
              f"(ej: {', '.join(f'{r.rut}-{r.anio} {r.subtotal}' for r in rot.head(5).itertuples())})\n")
    print("de los ubicados, por columna:")
    print(ub.groupby(["subtotal", "columna"]).agg(
        n=("pdf_suma", "size"),
        pdf_no_suma=("pdf_suma", lambda s: int((~s.astype(bool)).sum())),
        no_suma_ni_con_signo_xml=("pdf_suma_signo_xml", lambda s: int((~s.astype(bool)).sum())),
        distinto_xml=("igual_xml", lambda s: int((~s.astype(bool)).sum())),
        con_agregacion=("agregacion", lambda s: int((s.fillna("") != "").sum()))).to_string(), "\n")

    print("monedas (umbral de materialidad):",
          ", ".join(f"{m}={umbral_materialidad(m)}" for m in df["moneda"].fillna("(vacia)").unique()))
    print("no suman, clasificados (estructura_efe_no_suma.csv):")
    print(pd.crosstab(cand["clase"], cand["patron"], margins=True).to_string(), "\n")
    pe = cand[cand["clase"].str.startswith("probable_error")]
    print(f"probable_error* ({len(pe)}), de menor a mayor tasa de la AGF:")
    for r in pe.sort_values("tasa_agf_pct").itertuples():
        print(f"  {r.rut} {r.anio} {r.subtotal:<14} {r.columna:<8} {r.clase[15:] or '-':<17} dif={r.dif:>14,.0f} {r.patron:<13} "
              f"igual_xml={r.igual_xml!s:<5} tasa_agf={r.tasa_agf_pct}%")
    print()
    print("validacion con casos conocidos:")
    for rut, anio, esperado in CASOS_CONOCIDOS:
        x = df[(df["rut"] == rut) & (df["anio"] == anio)]
        if x.empty:
            print(f"  {rut} {anio}: sin analizar  | esperado: {esperado}")
            continue
        for f in x.itertuples():
            if not f.ubicado:
                print(f"  {rut} {anio} {f.subtotal:<14}: no ubicado | esperado: {esperado}")
                continue
            print(f"  {rut} {anio} {f.subtotal:<14} {f.columna:<8} pdf_suma={f.pdf_suma!s:<5} "
                  f"con_signo_xml={f.pdf_suma_signo_xml!s:<5} "
                  f"igual_xml={f.igual_xml!s:<5} lineas {f.n_lineas_pdf}/{f.n_lineas_xml} "
                  f"{('agreg: ' + f.agregacion) if isinstance(f.agregacion, str) and f.agregacion else ''}")
        print(f"      esperado: {esperado}")
    print(f"\nsalida: {DIR_PROC / 'estructura_efe.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())