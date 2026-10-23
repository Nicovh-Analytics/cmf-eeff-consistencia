"""
Pasada estructural del PDF: Estado de Flujos de Efectivo
========================================================

Complementa al cruce por numeros (03/04). Aquel busca si cada cifra del XML
APARECE en el PDF; tiene un punto ciego: si el valor equivocado del PDF
coincide con otra cifra del XML, no queda huerfano y el error no forma par.

Aqui se lee el EFE por lineas (lector_espacial: posicion, sin XML) y se
revisa la estructura de cada subtotal (flujo de operacion y de financiamiento):
  1. Ubicar el subtotal: glosa esperada y al menos UNA columna igual al XML
     (+-2); si la glosa no aparece, por valor (ambas columnas) -> rotulo distinto.
  2. Componentes = lineas con montos entre el encabezado de la seccion (o el
     subtotal anterior) y el subtotal.
  3. Por columna:
       pdf_suma   = el subtotal impreso es la suma de sus lineas?
       igual_xml  = el subtotal impreso es igual al del XML?
       n lineas   = lineas distintas de cero en PDF vs codigos en XML
       agregacion = cifra del XML que es la suma de 2-3 lineas del PDF sin par
  4. Clasificacion de los que no suman: probable_error / _tipeo /
     _linea_no_sumada, probable_lectura, revisar_linea_faltante.

Lee:      data/procesado/cruce_resumen.csv, encabezados.csv, cuentas.csv
          data/coords_pdf/...                  (03a_coordenadas.py)
Escribe:  data/procesado/estructura_efe.csv          1 fila por fondo-anio-subtotal-columna
          data/procesado/estructura_efe_no_suma.csv  los que no suman, clasificados
"""

import itertools
import re
import sys
from pathlib import Path

import pandas as pd

from config import casos_conocidos, umbral_materialidad, CMF_HOME
from comun.lector_espacial import cargar_coords, filas_espaciales

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

# Una linea que marca el inicio de una seccion (no es componente).
RE_ENCABEZADO = re.compile(r"flujos?deefectivo|actividadesde(la)?(operaci|financ|inversi)|^notas?"
                           r"|^(activos?|pasivos?)(notas?|m\$|mus\$)*$|^ingresos(/?p[eé]rdidas|dela)"
                           r"|^gastos(deoperaci[oó]n)?$|expresad|milesde|m\$|us\$")
# Linea de fecha/columnas: "Al 31 de diciembre de 2015 2014", "Notas 2023 2022"
RE_FECHA = re.compile(r"diciembre|^al\d|^al$|^notas?")
RE_SUBTOTAL = re.compile(r"flujos?netos?|aumento|disminuci|saldo(inicial|final)|total")


def ubicar_subtotal(lineas, glosa_re, x_act, x_ant):
    """Indice de la linea del subtotal: glosa esperada y al menos una
    columna igual (en valor absoluto) al XML."""
    for i, (glosa, a, b, linea) in enumerate(lineas):
        # La glosa puede venir partida en la linea anterior, salvo que esa linea
        # sea el encabezado de seccion ("Flujos de efectivo ... financiamiento"):
        # ahi el primer componente se tomaba como subtotal cuando era la unica
        # linea (fondo nuevo con una sola linea de financiamiento).
        previa = lineas[i - 1][3] if i > 0 and lineas[i - 1][1] is None else ""
        if re.search(r"flujos?deefectivo", norm(previa)) and "neto" not in norm(previa):
            previa = ""
        # Sobre el texto sin espacios: hay PDFs con letras separadas
        # ("F lu jo n e to o r ig in a d o") que en crudo no calzaban.
        if a is None or not glosa_re.search(norm(previa + " " + linea)):
            continue
        # Solo cuentan coincidencias en valores DISTINTOS de cero: con la columna
        # anterior vacia (fondo nuevo, o linea de una sola columna) un 0 calzaba
        # con cualquier linea que tuviera la glosa, y se tomaba la linea equivocada.
        # Con tolerancia de redondeo: hay AGF cuyo XML difiere en 1-2 del PDF
        # (diferencias de redondeo de +-1); con igualdad exacta no se ubicaban.
        ok_a = bool(x_act) and abs(abs(a) - abs(x_act)) <= TOL
        ok_b = bool(x_ant) and isinstance(b, int) and abs(abs(b) - abs(x_ant)) <= TOL
        if ok_a or ok_b:
            return i
    return None


RE_FLUJO_NETO = re.compile(r"flujos?netos?")


def ubicar_por_valor(lineas, x_act, x_ant, excluir=()):
    """Respaldo cuando la glosa esperada no aparece: linea con glosa de "flujo
    neto" (cualquier seccion) y AMBAS columnas iguales al XML (una sola si el
    XML no trae anterior). Mas estricto porque la glosa no confirma: plantilla
    una plantilla rotula el subtotal de financiamiento como "...de la operacion"."""
    for i, (glosa, a, b, linea) in enumerate(lineas):
        if a is None or i in excluir or not RE_FLUJO_NETO.search(norm(linea)):
            continue
        ok_a = bool(x_act) and abs(abs(a) - abs(x_act)) <= TOL
        ok_b = (not x_ant) or (isinstance(b, int) and abs(abs(b) - abs(x_ant)) <= TOL)
        if ok_a and ok_b:
            return i
    return None


def componentes(lineas, i_sub, cortes=frozenset(), valores=frozenset()):
    """Lineas con montos sobre el subtotal, hasta un encabezado de seccion u
    otro subtotal. Las lineas sin montos (glosa partida en dos lineas) se saltan.
    cortes: valores absolutos de los OTROS subtotales del XML; una linea con
    uno de esos valores es el subtotal de la seccion anterior aunque su glosa
    no se reconozca (glosa en la linea previa, "OPERACION", texto pegado).
    valores: valores absolutos del XML (para reconocer encabezados con numeros)."""
    propios = {abs(v) for v in lineas[i_sub][1:3] if isinstance(v, int)}
    j = i_sub - 1
    # Las lineas sin montos justo encima del subtotal son su propia glosa
    # partida ("Flujo neto ... actividades de" / "financiamiento" / valores).
    while j >= 0 and lineas[j][1] is None:
        j -= 1
    comp = []
    for j in range(j, -1, -1):
        glosa, a, b, linea = lineas[j]
        if a is None:
            # Un encabezado corta el bloque: "Al 31 de diciembre de 2015". Un
            # subtotal vacio sin montos ("Flujo neto ... operacion (+)") no.
            n = norm(linea)
            if (RE_ENCABEZADO.search(n) or RE_FECHA.search(n)) and not RE_SUBTOTAL.search(n):
                break
            continue
        g = norm(glosa)
        nums = [v for v in (a, b) if isinstance(v, int)]
        chicos = all(abs(v) <= 2100 for v in nums)
        # Subtotal repetido o vacio inmediatamente sobre el subtotal ("Subtotal
        # efectivo utilizado en operaciones" con el mismo valor, "Flujo neto ... - -"):
        # se salta en vez de cortar.
        if RE_SUBTOTAL.search(g) and not comp and \
                (not any(nums) or {abs(v) for v in nums if v} <= propios):
            continue
        # Encabezado con numeros: corta si los numeros son "chicos" (anio, dia,
        # nota) o si ninguno es cifra del XML ("Flujos de efectivo ... 12 201",
        # "Al 2014").
        if (RE_ENCABEZADO.search(g) or RE_FECHA.search(g)) and \
                (chicos or not any(abs(v) in valores for v in nums if v)):
            break
                # Linea de encabezado de columnas: los montos son anios ("2018 2017", "M$ 2018 2017"),
        # tenga o no glosa. Antes solo cortaba sin glosa, y en el ESF/ERI se sumaba como partida.
        anios = [abs(v) for v in nums if v]
        if anios and all(1990 <= v <= 2100 for v in anios) and \
                ((len(anios) == 2 and anios[0] - anios[1] == 1) or not g):
            break
        # Sin glosa: solo corta si los valores son anios ("2011 2010"). Con
        # "numeros chicos" a secas cortaba fondos diminutos (montos de 1-4
        # digitos con la glosa en la linea anterior).
        if not g and any(nums) and all(1990 <= abs(v) <= 2100 for v in nums if v):
            break
        # Subtotal anterior: por glosa (incluida la linea previa sin montos,
        # si la glosa vino partida) o por valor de otro subtotal del XML.
        previa = lineas[j - 1][3] if j > 0 and lineas[j - 1][1] is None else ""
        if RE_SUBTOTAL.search(g) or RE_SUBTOTAL.search(norm(previa) + g) \
                or (any(nums) and all(abs(v) in cortes for v in nums if v)):
            break
        comp.append((glosa, a, b))
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


def analizar_fondo(paginas, xml, coords):
    """paginas: paginas de estados; xml: dict (contexto, codigo) -> valor;
    coords: cache del 03a. La lectura del PDF no usa el XML; el XML solo se
    usa para ubicar el subtotal y para comparar."""
    valores = {abs(v) for v in xml.values() if v}
    lineas, irregulares = [], []
    # Pagina "espaciada": mas de la mitad de las palabras son de 1 caracter (plantilla con
    # letras y digitos sueltos, a veces en capas superpuestas). Ahi un no-suma es lectura.
    espaciadas = set()
    for p in paginas:
        pal = coords["paginas"].get(str(p), {}).get("palabras", [])
        if pal and sum(len(w[0]) == 1 for w in pal) / len(pal) > 0.5:
            espaciadas.add(p)
    for p in paginas:
        if str(p) in coords["paginas"]:
            filas_p, irr = filas_espaciales(coords["paginas"][str(p)])
            lineas += [(g, a, b, l, p) for g, a, b, l in filas_p]
            irregulares += irr
    planas = [(g, a, b, l) for g, a, b, l, _ in lineas]

    filas = []
    usados = set()          # lineas ya tomadas como subtotal (no reutilizar)
    for nombre, cfg in SUBTOTALES.items():
        x_act = xml.get(("PeriodoActual", cfg["codigo"]))
        x_ant = xml.get(("PeriodoAnterior", cfg["codigo"]))
        if x_act is None:
            continue
        i = ubicar_subtotal(planas, cfg["glosa"], x_act, x_ant)
        glosa_ok = i is not None
        metodo = "glosa_y_valor" if i is not None else None
        if i is None:
            i = ubicar_por_valor(planas, x_act, x_ant, excluir=usados)
            if i is not None:
                metodo = "valor"
        if i is None:
            # Respaldo 2: la glosa calza en UNA sola linea con montos, aunque el valor
            # difiera del XML (subtotal mal impreso en el PDF: no debe quedar fuera).
            cand = [k for k, (_, a, _, l) in enumerate(planas)
                    if a is not None and k not in usados and cfg["glosa"].search(norm(l))]
            if len(cand) == 1:
                i, glosa_ok, metodo = cand[0], True, "solo_glosa"
        if i is None:
            filas.append(dict(subtotal=nombre, ubicado=False))
            continue
        usados.add(i)
        _, s_act, s_ant, _ = planas[i]
        cortes = {abs(xml.get((c, otro["codigo"])) or 0) for otro in SUBTOTALES.values()
            if otro is not cfg and otro["estado"] == cfg["estado"]
            for c in ("PeriodoActual", "PeriodoAnterior")} - {0}
        comp = componentes(planas, i, cortes, valores)
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
                subtotal=nombre, ubicado=True, columna=col, pagina=lineas[i][4],
                pagina_espaciada=lineas[i][4] in espaciadas,
                glosa_esperada=glosa_ok,   # False: ubicado por valor, rotulo distinto
                formato_irregular=" ".join(irregulares), metodo = metodo,
                subtotal_pdf=s_pdf, subtotal_xml=x_tot, suma_lineas_pdf=suma,
                pdf_suma=abs(suma - s_pdf) <= TOL,
                pdf_suma_signo_xml=abs(suma_sx - s_sx) <= TOL,
                igual_xml=abs(abs(s_pdf) - abs(x_tot)) <= TOL,
                n_lineas_pdf=len(nz_pdf), n_lineas_xml=len(nz_xml),
                faltan_xml=len(faltan), sobran_pdf=len(sobran),
                agregacion="; ".join(buscar_agregacion(faltan, sobran)),
                detalle=" | ".join(f"{c[0][:30]}={c[idx]}{marca(c[idx])}" for c in comp if c[idx] is not None)))
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
    return c[cols].sort_values(["clase", "tasa_agf_pct", "rut", "anio"])


def main():
    res = pd.read_csv(DIR_PROC / "cruce_resumen.csv", dtype={"rut": str})
    enc = pd.read_csv(DIR_PROC / "encabezados.csv", dtype={"rut": str})
    enc = enc[enc["es_ultimo_envio"]][["rut", "anio", "archivo", "moneda"]]
    ok = res[res["estado"] == "ok"].drop(columns=["moneda"], errors="ignore").merge(enc, on=["rut", "anio"])

    codigos = {cfg["codigo"] for cfg in SUBTOTALES.values()} | {c for cfg in SUBTOTALES.values() for c in cfg["partes"]}
    cta = pd.read_csv(DIR_PROC / "cuentas.csv",
                      usecols=["archivo", "contexto", "codigo", "serie", "valor"], dtype={"serie": str})
    cta = cta[cta["serie"].isna() & cta["codigo"].isin(codigos) & cta["archivo"].isin(ok["archivo"])]
    xml_por_archivo = {a: {(c, k): v for c, k, v in zip(g["contexto"], g["codigo"], g["valor"].fillna(0))}
                       for a, g in cta.groupby("archivo")}

    filas, sin_coords = [], 0
    for r in ok.itertuples(index=False):
        coords = cargar_coords(r.rut, r.anio, r.pdf)
        if coords is None:
            sin_coords += 1         # sin cache del 03a (o PDF con error)
            continue
        paginas = [int(p) for p in str(r.paginas_estados).split(",") if p.strip().isdigit()]
        for f in analizar_fondo(paginas, xml_por_archivo.get(r.archivo, {}), coords):
            filas.append({"rut": r.rut, "anio": r.anio, "nombre_agf": r.nombre_agf, "moneda": r.moneda, **f})

    df = pd.DataFrame(filas)
    df.to_csv(DIR_PROC / "estructura_efe.csv", index=False, encoding="utf-8-sig")
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