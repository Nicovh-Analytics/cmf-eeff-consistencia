"""
Continuidad entre periodos (XML t vs XML t-1)
=============================================

Pregunta: lo que el reporte del anio t presenta como "anio anterior"
(el comparativo), ¿es lo mismo que se reporto y audito el anio t-1?

Solo usa el XML (cuentas.csv): no lee PDF. Complementa al cruce espejo
(03/04), que compara XML y PDF de UN mismo envio y no ve un comparativo
modificado si XML y PDF se modificaron igual (ver H5 en docs/decisiones.md).

Dos chequeos por fondo, para cada par de anios consecutivos (t-1, t):
  A. Comparativo: XML t, contexto PeriodoAnterior  vs  XML t-1, PeriodoActual,
     cifra por cifra (codigo, serie). Lo normal es que sean identicos.
  B. Arrastre de saldos: inicio de t (ECP, por serie)  vs  cierre de t-1.

Y un chequeo interno de cada XML, sin comparar anios:
  C. Identidades contables (suma de lineas = total, activo - pasivo = activo
     neto, cruces entre estados), en PeriodoActual y en PeriodoAnterior por
     separado. Si una identidad no falla nunca en la columna actual y si en el
     comparativo, la validacion de la CMF la revisa solo en la actual (H6).
     Las listas de lineas son fijas: si una identidad falla tambien en la
     actual, puede ser que falte una linea en la lista; por eso lo que importa
     es la ASIMETRIA entre columnas, no la tasa absoluta.

Series renombradas entre anios (p.ej. EA-AM -> Z): se emparejan por monto
de cierre antes de comparar, y se informan aparte (no son error).

Clase de cada fondo-anio t (chequeo A):
  identico        todas las cifras iguales (cero en ambos lados = igual)
  dif_menor       diferencias de a lo mas MAX_DIF_MENOR (redondeo)
  modificado      alguna diferencia mayor, saldos clave iguales
                  (redistribucion/reclasificacion del comparativo)
  incompleto      sin cambios de valor, pero cifras informadas en un solo lado
                  o un estado completo en cero en el comparativo
  subtotal_vacio  los saldos clave que cambian vienen en 0 en el comparativo
                  con sus lineas informadas (no suma; total omitido)
  modificado_saldos  cambia algun saldo clave (activo neto, total activo,
                  resultado, cierre del ECP, saldo final de efectivo)

Lee:      data/procesado/encabezados.csv, cuentas.csv
Escribe:  data/procesado/continuidad_resumen.csv   1 fila por fondo-anio t
          data/procesado/continuidad_detalle.csv   cifras distintas (A y B)
          data/procesado/continuidad_por_agf.csv   tasas por AGF
          data/procesado/identidades_xml.csv       fallas de identidades (C)

Un comparativo modificado NO es por si solo un error: puede ser una
reclasificacion revelada (NIC 1.41). Lo que se marca es donde mirar.
"""

import importlib.util
import sys
from pathlib import Path
from config import CMF_HOME
from comun.secciones import asignar_secciones

import pandas as pd

from config import casos_conocidos

BASE_DIR = Path(__file__).resolve().parent
DIR_PROC = CMF_HOME / "procesado"

MAX_DIF_MENOR = 5      # en unidades del reporte (miles)
TOL_SERIE = 1          # tolerancia para emparejar series por cierre

COD_INICIO = "ActivoNetoAtribuibleALosParticipesAl01DeEneroPorSerie"
COD_CIERRE = "ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuotaPorSerie"

# Saldos que no deberian cambiar ni en una reclasificacion (serie vacia = total)
CODIGOS_CLAVE = {
    "TotalActivo",
    "ActivoNetoAtribuibleALosParticipes",
    "AumentoDisminucionDeActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionDespuesDeDistribucionDeBeneficios",
    "ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuota",
    "SaldoFinalDeEfectivoYEfectivoEquivalente",
}

# Casos conocidos de la verificacion manual (rut, anio t, que se espera).
# Sirven para validar el chequeo, igual que la muestra valido el 04.
CASOS_CONOCIDOS = casos_conocidos("07")       # privado: verificacion/casos_conocidos.csv


# Identidades (chequeo C). Cada codigo se escribe "ESTADO:Codigo" porque hay
# codigos que existen en dos estados. total = suma(con signo) de las partes.
def _t(txt):
    return txt.split()

IDENTIDADES = {
    "ESF suma activos = total activo": ("ESF:TotalActivo", [(1, "ESF:" + c) for c in _t(
        "EfectivoYEfectivoEquivalente ActivosFinancierosAValorRazonableConEfectoEnResultados "
        "ActivosFinancierosAValorRazonableConEfectoEnResultadosEntregadosEnGarantia "
        "ActivosFinancierosACostoAmortizado CuentasPorCobrarAIntermediarios "
        "OtrasCuentasPorCobrar OtrosActivos")]),
    "ESF suma pasivos = total pasivo": ("ESF:TotalPasivo", [(1, "ESF:" + c) for c in _t(
        "PasivosFinancierosAValorRazonableConEfectoEnResultados CuentasPorAPagarIntermediarios "
        "RescatesPorPagar RemuneracionesSociedadAdministradora "
        "OtrosDocumentosYCuentasPorPagar OtrosPasivos")]),
    "ESF activo - pasivo = activo neto": ("ESF:ActivoNetoAtribuibleALosParticipes",
                                          [(1, "ESF:TotalActivo"), (-1, "ESF:TotalPasivo")]),
    "ERI suma ingresos = total ingresos": ("ERI:TotalIngresosPerdidasNetosDeLaOperacion",
        [(1, "ERI:" + c) for c in _t(
        "InteresesYReajustes IngresosPorDividendos "
        "DiferenciasDeCambioNetasSobreActivosFinancierosACostoAmortizado "
        "DiferenciasDeCambioNetasSobreEfectivoYEfectivoEquivalente "
        "CambiosNetosEnValorRazonableDeActivosYPasivosFinancierosAValorRazonableConEfectoEnResultados "
        "ResultadoEnVentaDeInstrumentosFinancieros OtrosEri")]),
    "ERI suma gastos = total gastos": ("ERI:TotalGastosDeOperacion", [(1, "ERI:" + c) for c in _t(
        "ComisionDeAdministracion HonorariosPorCustodiaYAdministracion CostosDeTransaccion "
        "OtrosGastosDeOperacion")]),
    "ERI ingresos + gastos = utilidad": ("ERI:UtilidadPerdidaDeLaOperacionAntesDeImpuesto",
        [(1, "ERI:TotalIngresosPerdidasNetosDeLaOperacion"), (1, "ERI:TotalGastosDeOperacion")]),
    "ECP aportes + rescates = neto": ("ECP:AumentoNetoOriginadoPorTransaccionesDeCuotas",
        [(1, "ECP:AportesDeCuotas"), (1, "ECP:RescateDeCuotas")]),
    "ECP inicio + neto + resultado = cierre": ("ECP:ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuota",
        [(1, "ECP:ActivoNetoAtribuibleALosParticipesAl01DeEnero"),
         (1, "ECP:AumentoNetoOriginadoPorTransaccionesDeCuotas"),
         (1, "ECP:AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionDespuesDeDistribucionDeBeneficios")]),
    "EFE suma operacion = flujo operacion": ("EFE:FlujoNetoOriginadoPorActividadesDeLaOperacion",
        [(1, "EFE:" + c) for c in _t(
        "CompraDeActivosFinancieros VentaCobroDeActivosFinancieros "
        "InteresesDiferenciasDeCambioYReajustesRecibidos LiquidacionDeInstrumentosFinancierosDerivados "
        "DividendosRecibidos MontosPagadosASociedadAdministradoraEIntermediarios "
        "MontosRecibidosDeSociedadAdministradoraEIntermediarios OtrosIngresosDeOperacion "
        "OtrosGastosDeOperacionPagados")]),
    "EFE suma financiamiento = flujo financ.": ("EFE:FlujoNetoOriginadoPorActividadesDeFinanciamiento",
        [(1, "EFE:" + c) for c in _t("ColocacionDeCuotasEnCirculacion RescatesDeCuotasEnCirculacion Otros")]),
    "EFE operacion + financ. = aumento neto": (
        "EFE:AumentoNetoDeEfectivoYEfectivoEquivalente|EFE:AumentoDisminucionNetoDeEfectivoYEfectivoEquivalente",
        [(1, "EFE:FlujoNetoOriginadoPorActividadesDeLaOperacion|EFE:FlujoNetoUtilizadoEnActividadesDeLaOperacion"),
         (1, "EFE:FlujoNetoOriginadoPorActividadesDeFinanciamiento|EFE:FlujoNetoUtilizadoPorActividadesDeFinanciamiento")]),
    "EFE inicial + aumento + dif.cambio = final": ("EFE:SaldoFinalDeEfectivoYEfectivoEquivalente",
        [(1, "EFE:SaldoInicialDeEfectivoYEfectivoEquivalente"),
         # metodo directo | metodo indirecto (76 XML 2011-2015)
         (1, "EFE:AumentoNetoDeEfectivoYEfectivoEquivalente|EFE:AumentoDisminucionNetoDeEfectivoYEfectivoEquivalente"),
         (1, "EFE:DiferenciasDeCambioNetasSobreEfectivoYEfectivoEquivalente")]),
    "cruce ESF activo neto = ECP cierre": ("ESF:ActivoNetoAtribuibleALosParticipes",
        [(1, "ECP:ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuota")]),
    "cruce ESF efectivo = EFE saldo final": ("ESF:EfectivoYEfectivoEquivalente",
        [(1, "EFE:SaldoFinalDeEfectivoYEfectivoEquivalente")]),
    "cruce ERI resultado = ECP resultado": (
        "ERI:AumentoDisminucionDeActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionAntesDeDistribucionDeBeneficios",
        [(1, "ECP:AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionAntesDeDistribucionDeBeneficios")]),
}
TOL_IDENTIDAD = 1       # diferencias de 1 se toleran (redondeo de sumas)


def chequeo_identidades(cta):
    """C: identidades contables dentro de cada XML y contexto (totales del
    fondo), mas suma de series del cierre del ECP = total."""
    tot = cta[cta["serie"] == ""]
    w = tot.assign(col=tot["estado"] + ":" + tot["codigo"]).pivot_table(
        index=["archivo", "contexto"], columns="col", values="valor", aggfunc="first")
    filas = []
    def columna(cod):
        """'A|B' -> valor de A; si falta, el de B (codigos alternativos por plantilla)."""
        alts = [a for a in cod.split("|") if a in w]
        if not alts:
            return None
        v = w[alts[0]]
        for a in alts[1:]:
            v = v.fillna(w[a])
        return v

    for nombre, (total, partes) in IDENTIDADES.items():
        t = columna(total)
        if t is None:
            continue
        presentes = t.notna()                   # se evalua solo si el total esta informado
        rhs = 0
        for sg, c in partes:
            v = columna(c)
            rhs = rhs + (sg * v.fillna(0) if v is not None else 0)
        d = pd.DataFrame({"identidad": nombre, "total": t, "suma_partes": rhs})[presentes]
        filas.append(d)

    # Suma de series del cierre = cierre total (ECP)
    ser = cta[(cta["codigo"] == COD_CIERRE) & (cta["serie"] != "")] \
        .groupby(["archivo", "contexto"])["valor"].sum()
    totc = tot[tot["codigo"] == COD_CIERRE.replace("PorSerie", "")] \
        .drop_duplicates(["archivo", "contexto"]).set_index(["archivo", "contexto"])["valor"]
    comun = ser.index.intersection(totc.index)
    filas.append(pd.DataFrame({"identidad": "ECP suma series cierre = total",
                               "total": totc[comun], "suma_partes": ser[comun]}))

    idt = pd.concat(filas).reset_index()
    idt["dif"] = idt["total"] - idt["suma_partes"]
    idt["falla"] = idt["dif"].abs() > TOL_IDENTIDAD
    idt["falla_grande"] = idt["dif"].abs() > MAX_DIF_MENOR
    return idt


ENTRE_COLUMNAS = {
    # identidad: (codigo apertura en PeriodoActual, codigo cierre en PeriodoAnterior)
    "EFE inicial (act) = final (ant)": ("EFE:SaldoInicialDeEfectivoYEfectivoEquivalente",
                                        "EFE:SaldoFinalDeEfectivoYEfectivoEquivalente"),
    "ECP inicio total (act) = cierre (ant)": ("ECP:ActivoNetoAtribuibleALosParticipesAl01DeEnero",
                                              "ECP:ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuota"),
    "ECP inicio (act) = ESF activo neto (ant)": ("ECP:ActivoNetoAtribuibleALosParticipesAl01DeEnero",
                                                 "ESF:ActivoNetoAtribuibleALosParticipes"),
}


def chequeo_entre_columnas(cta):
    """C2: saldos que se arrastran DENTRO del mismo XML: la apertura del
    periodo actual tiene que ser el cierre del periodo anterior. La validacion
    por columna no lo ve (caso visto: EFE final anterior 2.434.815 vs
    inicial actual 2.414.815, cada columna cuadra por separado)."""
    tot = cta[cta["serie"] == ""]
    w = tot.assign(col=tot["estado"] + ":" + tot["codigo"]).pivot_table(
        index="archivo", columns=["contexto", "col"], values="valor", aggfunc="first")
    filas = []
    for nombre, (apertura, cierre) in ENTRE_COLUMNAS.items():
        a, c = ("PeriodoActual", apertura), ("PeriodoAnterior", cierre)
        if a not in w or c not in w:
            continue
        ambos = w[a].notna() & w[c].notna()
        filas.append(pd.DataFrame({"identidad": nombre, "total": w.loc[ambos, a],
                                   "suma_partes": w.loc[ambos, c]}))
    # Por serie: cada serie del ECP, mismo nombre en ambas columnas del archivo.
    ser = cta[(cta["serie"] != "") & cta["codigo"].isin([COD_INICIO, COD_CIERRE])]
    ini = ser[(ser["contexto"] == "PeriodoActual") & (ser["codigo"] == COD_INICIO)]
    cie = ser[(ser["contexto"] == "PeriodoAnterior") & (ser["codigo"] == COD_CIERRE)]
    p = ini.merge(cie, on=["archivo", "serie"], suffixes=("_i", "_c"))
    p = p.assign(d=(p["valor_i"] - p["valor_c"]).abs())
    peor = p.sort_values("d").groupby("archivo").last()   # la serie que peor cuadra
    filas.append(pd.DataFrame({"identidad": "ECP inicio por serie (act) = cierre (ant)",
                               "total": peor["valor_i"], "suma_partes": peor["valor_c"]}))
    x = pd.concat(filas).reset_index()
    x["dif"] = x["total"] - x["suma_partes"]
    x["falla"] = x["dif"].abs() > TOL_IDENTIDAD
    x["falla_grande"] = x["dif"].abs() > MAX_DIF_MENOR
    x["contexto"] = "entre_columnas"
    return x


def mapa_identidades(idt):
    """Tabla identidad x columna: evaluados, fallas y fallas > MAX_DIF_MENOR."""
    t = idt.groupby(["identidad", "contexto"]).agg(
        n=("falla", "size"), fallas=("falla", "sum"), grandes=("falla_grande", "sum")).unstack()
    t.columns = [f"{a}_{'act' if b == 'PeriodoActual' else 'ant'}" for a, b in t.columns]
    orden = ["n_act", "fallas_act", "grandes_act", "n_ant", "fallas_ant", "grandes_ant"]
    t = t.reindex(columns=orden).fillna(0).astype(int)
    t["lectura"] = "ok en ambas"
    t.loc[(t["grandes_act"] == 0) & (t["grandes_ant"] > 0), "lectura"] = "solo falla comparativo"
    t.loc[(t["grandes_act"] > 0), "lectura"] = "falla en ambas (revisar lista o no se valida)"
    return t


def identidades_por_anio(idt, enc):
    """Fallas grandes por anio de reporte, solo identidades que fallan alguna vez.
    Sirve para ver si la validacion de la CMF cambio en el tiempo: una
    identidad que deja de fallar desde cierto anio sugiere una regla nueva."""
    x = idt.merge(enc[["archivo", "anio"]], on="archivo")
    con_fallas = x.loc[x["falla_grande"], "identidad"].unique()
    x = x[x["identidad"].isin(con_fallas)]
    x["col"] = x["contexto"].map({"PeriodoActual": "act", "PeriodoAnterior": "ant"})
    t = x.groupby(["identidad", "col", "anio"])["falla_grande"].sum().unstack("anio", fill_value=0)
    n = x.groupby("anio")["archivo"].nunique()
    t.loc[("(XML en el anio)", ""), :] = n
    return t.astype(int)


def leer():
    enc = pd.read_csv(DIR_PROC / "encabezados.csv",
                      dtype={"rut": str, "rut_agf": str})
    enc = enc[enc["es_ultimo_envio"]][
        ["archivo", "rut", "anio", "rut_agf", "nombre_agf", "nombre_fondo"]]

    cta = pd.read_csv(DIR_PROC / "cuentas.csv",
                      usecols=["archivo", "contexto", "codigo", "serie", "valor"],
                      dtype={"serie": str})
    cta = cta[cta["contexto"].isin(["PeriodoActual", "PeriodoAnterior"])
              & cta["archivo"].isin(enc["archivo"])]

    # Estado financiero por orden de aparicion dentro de cada archivo-contexto.
    asignar = asignar_secciones
    cta["estado"] = cta.groupby(["archivo", "contexto"], sort=False)["codigo"] \
                       .transform(lambda s: asignar(list(s)))

    cta["serie"] = cta["serie"].fillna("")
    cta["valor"] = cta["valor"].fillna(0)
    cta = cta.merge(enc[["archivo", "rut", "anio"]], on="archivo")
    # Algunos codigos existen en dos estados (DiferenciasDeCambioNetasSobreEfectivo...
    # en ERI y EFE; DistribucionDeBeneficios en ERI y ECP): el estado los separa.
    # Si aun asi se repite (codigo, serie, estado), se queda el primero.
    n0 = len(cta)
    cta = cta.drop_duplicates(["archivo", "contexto", "estado", "codigo", "serie"])
    if n0 - len(cta):
        print(f"aviso: {n0 - len(cta)} cifras duplicadas (codigo, serie) descartadas")
    return enc, cta


def emparejar_series(comp, orig):
    """Para cada fondo-anio de referencia, series que estan en un lado y no
    en el otro se emparejan si su cierre coincide (+-TOL_SERIE).
    Devuelve dict (rut, anio_ref) -> {serie_en_comp: serie_en_orig}."""
    ser_c = comp[comp["serie"] != ""].groupby(["rut", "anio_ref"])["serie"].agg(set)
    ser_o = orig[orig["serie"] != ""].groupby(["rut", "anio_ref"])["serie"].agg(set)
    cierre_c = comp[comp["codigo"] == COD_CIERRE].set_index(["rut", "anio_ref", "serie"])["valor"]
    cierre_o = orig[orig["codigo"] == COD_CIERRE].set_index(["rut", "anio_ref", "serie"])["valor"]

    mapas = {}
    for k in ser_c.index.intersection(ser_o.index):
        solo_c, solo_o = ser_c[k] - ser_o[k], ser_o[k] - ser_c[k]
        if not solo_c or not solo_o:
            continue
        m = {}
        for sc in solo_c:
            vc = cierre_c.get(k + (sc,))
            if vc is None or vc == 0:
                continue
            for so in solo_o - set(m.values()):
                vo = cierre_o.get(k + (so,))
                if vo is not None and abs(vc - vo) <= TOL_SERIE:
                    m[sc] = so
                    break
        if m:
            mapas[k] = m
    return mapas


def chequeo_comparativo(cta):
    """A: XML t (PeriodoAnterior) vs XML t-1 (PeriodoActual)."""
    comp = cta[cta["contexto"] == "PeriodoAnterior"].copy()
    comp["anio_ref"] = comp["anio"] - 1           # el anio al que se refiere
    orig = cta[cta["contexto"] == "PeriodoActual"].copy()
    orig["anio_ref"] = orig["anio"]

    # Solo pares de anios donde existen ambos reportes.
    pares = (comp[["rut", "anio_ref"]].drop_duplicates()
             .merge(orig[["rut", "anio_ref"]].drop_duplicates()))
    comp = comp.merge(pares)
    orig = orig.merge(pares)

    mapas = emparejar_series(comp, orig)
    if mapas:
        mask = [(r, a) in mapas for r, a in zip(comp["rut"], comp["anio_ref"])]
        comp.loc[mask, "serie"] = [mapas[(r, a)].get(s, s) for r, a, s in
                                   comp.loc[mask, ["rut", "anio_ref", "serie"]].itertuples(index=False)]

    claves = ["rut", "anio_ref", "estado", "codigo", "serie"]
    m = comp[claves + ["valor"]].merge(
        orig[claves + ["valor"]], on=claves, how="outer",
        suffixes=("_comp", "_orig"), indicator=True)
    # Ausente y cero son lo mismo para este chequeo (el XML a veces omite ceros).
    m["valor_comp"] = m["valor_comp"].fillna(0)
    m["valor_orig"] = m["valor_orig"].fillna(0)
    m["dif"] = m["valor_comp"] - m["valor_orig"]
    m["anio"] = m["anio_ref"] + 1                 # el reporte que trae el comparativo
    m["clave"] = (m["serie"] == "") & m["codigo"].isin(CODIGOS_CLAVE)
    # Cifra informada en un solo lado: es omision (incompleto), no cambio de valor.
    m["omision"] = (m["_merge"] != "both") & (m["dif"] != 0)
    # Estado completo en cero (o +-1) en el comparativo con el original informado:
    # el comparativo no se lleno; tambien es omision. Se evalua por estado y no
    # por cifra, para no tapar reclasificaciones reales donde un lado es 0
    # (ej. (52) que pasa de otros gastos a otros ingresos).
    vacio = (m.assign(c=m["valor_comp"].abs() <= 1, o=m["valor_orig"] != 0)
             .groupby(["rut", "anio_ref", "estado"])
             .agg(todo_cero=("c", "all"), hay_orig=("o", "any")))
    vacio = vacio[vacio["todo_cero"] & vacio["hay_orig"]].index
    en_vacio = pd.MultiIndex.from_frame(m[["rut", "anio_ref", "estado"]]).isin(vacio)
    m.loc[en_vacio & (m["dif"] != 0), "omision"] = True
    renombradas = {k: ", ".join(f"{a}->{b}" for a, b in v.items()) for k, v in mapas.items()}
    return m, pares, renombradas


def chequeo_arrastre(cta):
    """B: inicio de t (ECP por serie) vs cierre de t-1 (ECP por serie).
    Empareja series renombradas por monto igual que en A."""
    # Por serie y total del fondo (fondos de una serie a veces solo traen el total).
    cods_ini = {COD_INICIO, COD_INICIO.replace("PorSerie", "")}
    cods_cie = {COD_CIERRE, COD_CIERRE.replace("PorSerie", "")}
    ini = cta[(cta["contexto"] == "PeriodoActual") & cta["codigo"].isin(cods_ini)]
    cie = cta[(cta["contexto"] == "PeriodoActual") & cta["codigo"].isin(cods_cie)].copy()
    cie["anio"] = cie["anio"] + 1                 # el cierre de t-1 es el inicio de t
    b = ini[["rut", "anio", "serie", "valor"]].merge(
        cie[["rut", "anio", "serie", "valor"]], on=["rut", "anio", "serie"],
        how="outer", suffixes=("_inicio", "_cierre_ant"))
    # Solo anios con ambos reportes
    con_ambos = set(zip(ini["rut"], ini["anio"])) & set(zip(cie["rut"], cie["anio"]))
    b = b[[k in con_ambos for k in zip(b["rut"], b["anio"])]]
    b = b.fillna({"valor_inicio": 0, "valor_cierre_ant": 0})
    b["dif"] = b["valor_inicio"] - b["valor_cierre_ant"]

    # Una serie que "desaparece" y otra que "aparece" con el mismo monto es un
    # cambio de nombre: se descuenta.
    explicadas = []
    for (r, a), g in b[b["dif"].abs() > MAX_DIF_MENOR].groupby(["rut", "anio"]):
        nuevas = g[(g["valor_cierre_ant"] == 0) & (g["valor_inicio"] != 0)]
        viejas = g[(g["valor_inicio"] == 0) & (g["valor_cierre_ant"] != 0)]
        usadas = set()
        for i, n in nuevas.iterrows():
            for j, v in viejas.iterrows():
                if j not in usadas and abs(n["valor_inicio"] - v["valor_cierre_ant"]) <= TOL_SERIE:
                    explicadas += [i, j]
                    usadas.add(j)
                    break
    b["renombre"] = b.index.isin(explicadas)
    return b


def resumir(m, pares, renombradas, b, enc, fallas_internas=None):
    cambios = m[(m["dif"] != 0) & ~m["omision"]]
    grandes = cambios[cambios["dif"].abs() > MAX_DIF_MENOR]

    res = pares.rename(columns={"anio_ref": "anio_ant"})
    res["anio"] = res["anio_ant"] + 1
    k = ["rut", "anio"]
    agg = m.groupby(k).agg(cifras=("dif", "size"), omitidas=("omision", "sum"))
    res = res.merge(agg, on=k, how="left")
    agg = cambios.groupby(k).agg(distintas=("dif", "size"),
                                 max_abs_dif=("dif", lambda s: s.abs().max()))
    res = res.merge(agg, on=k, how="left").fillna({"distintas": 0, "max_abs_dif": 0})
    res = res.merge(grandes.groupby(k).agg(
        estados_dif=("estado", lambda s: ",".join(sorted(s.dropna().unique()))),
        cambia_saldos=("clave", "any")), on=k, how="left")
    res["cambia_saldos"] = res["cambia_saldos"].fillna(False).astype(bool)
    res["estados_dif"] = res["estados_dif"].fillna("")
    res["series_renombradas"] = [renombradas.get((r, a - 1), "") for r, a in zip(res["rut"], res["anio"])]

    quiebres = b[(b["dif"].abs() > MAX_DIF_MENOR) & ~b["renombre"]].groupby(k).size()
    res["quiebres_arrastre"] = [int(quiebres.get((r, a), 0)) for r, a in zip(res["rut"], res["anio"])]
    ren = b[b["renombre"]].groupby(k).size() // 2       # cada renombre es un par de filas
    res["renombres_arrastre"] = [int(ren.get((r, a), 0)) for r, a in zip(res["rut"], res["anio"])]

    res["clase"] = "identico"
    res.loc[res["omitidas"] > 0, "clase"] = "incompleto"      # solo omisiones
    res.loc[res["distintas"] > 0, "clase"] = "dif_menor"
    res.loc[res["max_abs_dif"] > MAX_DIF_MENOR, "clase"] = "modificado"
    res.loc[res["cambia_saldos"], "clase"] = "modificado_saldos"

    # subtotal_vacio: todos los saldos clave que cambian vienen en 0 (o +-1) en
    # el comparativo, con el original informado y las lineas presentes
    # (caso visto: total activo 0 con efectivo y costo amortizado informados).
    clv = grandes[grandes["clave"]]
    vacio = clv.assign(v=clv["valor_comp"].abs() <= 1).groupby(k)["v"].all()
    vacio = set(vacio[vacio].index)
    es_vacio = [(r, a) in vacio for r, a in zip(res["rut"], res["anio"])]
    res.loc[res["cambia_saldos"] & pd.Series(es_vacio, index=res.index), "clase"] = "subtotal_vacio"

    # Identidades que fallan DENTRO del XML del anio t (chequeos C y C2):
    # numero de identidades con falla grande. Independiente de la clase.
    fi = fallas_internas if fallas_internas is not None else {}
    res["descuadre_interno"] = [int(fi.get((r, a), 0)) for r, a in zip(res["rut"], res["anio"])]

    res = res.merge(enc[["rut", "anio", "rut_agf", "nombre_agf", "nombre_fondo"]],
                    on=k, how="left")
    cols = ["rut", "anio", "nombre_fondo", "nombre_agf", "rut_agf", "clase", "cifras",
            "distintas", "omitidas", "max_abs_dif", "estados_dif", "cambia_saldos",
            "quiebres_arrastre", "renombres_arrastre", "series_renombradas", "descuadre_interno"]
    return res[cols].sort_values(["clase", "max_abs_dif"], ascending=[True, False])

UMBRAL_REPITE = 0.75   # observado: 4.026/4.080 repiten < 10%; los casos reales, >= 76%

def xml_repite_anterior(cuentas):
    """Fondo-anio cuyo XML trae en la columna actual las mismas cifras que el XML del
    anio anterior (cuentas distintas de cero, por codigo y serie)."""
    c = cuentas[(cuentas.contexto == "PeriodoActual") & (cuentas.valor.fillna(0) != 0)].copy()
    c["serie"] = c["serie"].fillna("")
    v = c.drop_duplicates(["rut", "anio", "codigo", "serie"]).set_index(["rut", "anio", "codigo", "serie"]).valor
    t1 = v.copy()
    t1.index = pd.MultiIndex.from_arrays([t1.index.get_level_values(0), t1.index.get_level_values(1) + 1,
                                          t1.index.get_level_values(2), t1.index.get_level_values(3)])
    j = pd.concat([v.rename("t"), t1.rename("t1")], axis=1, join="inner")
    r = (j.t == j.t1).groupby(level=[0, 1]).agg(n_iguales="sum", n_cuentas="size").reset_index()
    r["pct_iguales"] = r.n_iguales / r.n_cuentas
    return r[(r.n_cuentas >= 10) & (r.pct_iguales >= UMBRAL_REPITE)]


def main():
    enc, cta = leer()
    m, pares, renombradas = chequeo_comparativo(cta)
    b = chequeo_arrastre(cta)
    idt = chequeo_identidades(cta)
    entre = chequeo_entre_columnas(cta)
    fallas = (pd.concat([idt, entre])[lambda z: z["falla_grande"]]
              .merge(enc[["archivo", "rut", "anio"]], on="archivo")
              .groupby(["rut", "anio"]).size().to_dict())
    res = resumir(m, pares, renombradas, b, enc, fallas)
    pd.concat([idt, entre])[lambda z: z["falla"]] \
        .merge(enc[["archivo", "rut", "anio", "nombre_agf"]], on="archivo") \
        .to_csv(DIR_PROC / "identidades_xml.csv", index=False, encoding="utf-8-sig")

    res.to_csv(DIR_PROC / "continuidad_resumen.csv", index=False, encoding="utf-8-sig")
    det_a = m[m["dif"] != 0][["rut", "anio", "estado", "codigo", "serie",
                              "valor_comp", "valor_orig", "dif", "clave", "_merge"]]
    det_a = det_a.assign(chequeo="A_comparativo").rename(columns={"_merge": "presente_en"})
    det_a["presente_en"] = det_a["presente_en"].map(
        {"both": "ambos", "left_only": "solo_comparativo", "right_only": "solo_original"})
    det_b = b[b["dif"] != 0].assign(chequeo="B_arrastre", estado="ECP", codigo=COD_INICIO)
    pd.concat([det_a, det_b], ignore_index=True).to_csv(
        DIR_PROC / "continuidad_detalle.csv", index=False, encoding="utf-8-sig")

    nombre = res.groupby("rut_agf")["nombre_agf"].agg(lambda s: s.value_counts().index[0])
    por_agf = res.groupby("rut_agf")["clase"].value_counts().unstack(fill_value=0)
    por_agf["evaluados"] = por_agf.sum(axis=1)
    for c in ("modificado", "modificado_saldos", "subtotal_vacio"):
        if c not in por_agf:
            por_agf[c] = 0
    por_agf["tasa_modificado_pct"] = (100 * (por_agf["modificado"] + por_agf["modificado_saldos"]
                                             + por_agf["subtotal_vacio"])
                                      / por_agf["evaluados"]).round(1)
    por_agf.insert(0, "agf", nombre)
    por_agf.sort_values("tasa_modificado_pct", ascending=False).to_csv(
        DIR_PROC / "continuidad_por_agf.csv", encoding="utf-8-sig")

    # --- Consola ---
    print(f"pares de anios comparados (fondo, t-1 -> t): {len(res)}")
    print(res["clase"].value_counts().to_string(), "\n")
    print(f"fondo-anio con alguna identidad interna rota (C/C2): "
          f"{int((res['descuadre_interno'] > 0).sum())}\n")
    mod = res[res["clase"].str.startswith("modificado")]
    if len(mod):
        print("modificados por estado con diferencias > "
              f"{MAX_DIF_MENOR}:")
        print(mod["estados_dif"].value_counts().head(8).to_string(), "\n")
    print(f"arrastre inicio t vs cierre t-1: {int((res['quiebres_arrastre'] > 0).sum())} "
          f"fondo-anio con quiebres; con series renombradas: "
          f"{int((res['renombres_arrastre'] > 0).sum())} (arrastre), "
          f"{int((res['series_renombradas'] != '').sum())} (comparativo)\n")
    print("AGF con mayor tasa de comparativos modificados (min. 20 evaluados):")
    print(por_agf[por_agf["evaluados"] >= 20][["agf", "evaluados", "tasa_modificado_pct"]]
          .sort_values("tasa_modificado_pct", ascending=False).head(8).to_string(), "\n")

    print(f"identidades contables por columna (falla: |dif| > {TOL_IDENTIDAD}; "
          f"grandes: > {MAX_DIF_MENOR}):")
    with pd.option_context("display.width", 200):
        print(mapa_identidades(idt).to_string(), "\n")
        print("identidades entre columnas del mismo XML (apertura actual = cierre anterior):")
        e = entre.merge(enc[["archivo", "anio"]], on="archivo")
        print(e.groupby("identidad").agg(n=("falla", "size"), fallas=("falla", "sum"),
                                          grandes=("falla_grande", "sum")).to_string(), "\n")
        print(e[e["falla_grande"]].groupby(["identidad", "anio"]).size()
              .unstack("anio", fill_value=0).to_string(), "\n")
        print("fallas grandes por anio de reporte (act = columna actual, ant = comparativo):")
        print(identidades_por_anio(idt, enc).to_string(), "\n")

    cuentas_t = pd.read_csv(DIR_PROC / "cuentas.csv", dtype={"rut": str, "serie": str},
                            usecols=["rut", "anio", "contexto", "codigo", "serie", "valor"])
    rep = xml_repite_anterior(cuentas_t)
    rep.to_csv(DIR_PROC / "xml_repite_anterior.csv", index=False)
    print(f"\nXML que repiten las cifras del anio anterior (>= {UMBRAL_REPITE:.0%} de cuentas iguales): {len(rep)}")
    if len(rep):
        print(rep.to_string(index=False))

    print("validacion con casos conocidos:")
    idx = res.set_index(["rut", "anio"])
    for rut, anio, esperado in CASOS_CONOCIDOS:
        if (rut, anio) in idx.index:
            f = idx.loc[(rut, anio)]
            print(f"  {rut} {anio}: {f['clase']:<18} (max dif {f['max_abs_dif']:,.0f}; "
                  f"{f['estados_dif'] or '-'})  esperado -> {esperado}")
        else:
            print(f"  {rut} {anio}: sin par de anios  esperado -> {esperado}")
    print(f"\nsalida: {DIR_PROC / 'continuidad_resumen.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())