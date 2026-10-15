"""
Candidatos a hallazgo (espejo XML <-> PDF)
==========================================

Toma la salida del cruce y arma la lista de fondo-anio a verificar A MANO.

Candidato = fondo-anio con al menos un "par": una cifra del XML no
encontrada en el PDF Y un monto del PDF sin par en el XML (huerfano).
Es la firma de una cifra que esta, pero con otro valor (ver H1 en
docs/decisiones.md). Se busca en TODO el universo, no solo bajo 90%:
H1 estaba en 94%.

Lo que NO es candidato:
  - "verificacion parcial": faltan cifras pero casi no hay huerfanos
    (el cruce no pudo leer alguna pagina; ver D20).
  - fondos sin cruce (sin_texto, no_es_pdf, sin_paginas_de_estados).

Para cada candidato:
  - a que estado (ESF/ERI/ECP/EFE, aproximado por el codigo) y a que
    periodo (actual/anterior) pertenecen las cifras faltantes;
  - materialidad: la mayor cifra faltante como % del activo neto.

Lee:      data/procesado/cruce_resumen.csv, cruce_detalle.csv,
          cruce_huerfanos.csv, encabezados.csv, cuentas.csv
Escribe:  data/procesado/candidatos.csv
          data/procesado/candidatos_por_agf.csv

Reglas posteriores a la muestra (ver D22/H5 en docs/decisiones.md):
  - Signo distinto solo se tolera en lineas con convencion de presentacion
    (rescates, gastos, compras...). En el resto es signo invertido: un
    espejo_ok con signo invertido pasa a candidato, tipo signo_invertido.
  - Huerfanos de "saldo acumulado" en el ECP (= inicio + neto de una
    serie): son una fila propia del formato de la AGF, no diferencias.
    Se marcan y no se usan para clasificar el par.
  - subtipo_probable: PISTA automatica para la verificacion, no veredicto.
    redistribucion_series / agregacion_xml / rotulo_incorrecto / dif_menor.
  - Materialidad n/a en redistribuciones (la diferencia neta es cero).
  - Si existe verificacion/muestra_verificacion.xlsx, compara el subtipo
    manual con el probable (precision de las reglas).
  - Materialidad absoluta por moneda (config.py, igual que el 03b): si la
    diferencia principal no supera el umbral, el candidato queda como
    observacion_inmaterial y no entra a la revision manual.

Un candidato NO es un hallazgo: es un lugar donde mirar. Ningun caso se
reporta con nombre sin verificacion manual del PDF.
"""

import sys
from pathlib import Path

import pandas as pd

from config import umbral_materialidad

BASE_DIR = Path(__file__).resolve().parent
DIR_PROC = BASE_DIR / "data" / "procesado"

# Un fondo es candidato si los huerfanos son al menos esta fraccion de las
# cifras no encontradas (en un par perfecto, 1 a 1).
MIN_RATIO_PARES = 0.5

CODIGOS_ACTIVO_NETO = ["ActivoNetoAtribuibleALosParticipes", "TotalActivo"]

# Emparejamiento cifra faltante <-> huerfano (ver D21 en docs/decisiones.md)
MAX_DIF_RELATIVA_PAR = 0.01   # un par es "cercano" si difiere <= 1%...
MIN_MONTO_PAR = 1000          # ...y el monto es >= 1.000 (en cifras chicas, 1%
                              # o un par de unidades calzan por azar)
MAX_DELTA_REDONDEO = 5        # diferencias chicas: posible redondeo acumulado
TOL_MONTO = 1                 # tolerancia al comparar montos reconstruidos

# Signo distinto (la cifra esta en el PDF, pero con el signo cambiado):
# se tolera solo en lineas donde hay convencion de presentacion (salidas y
# gastos que el PDF muestra sin parentesis bajo un titulo "gastos"/"rescates").
# En el resto (resultados, netos, flujos, totales) no hay convencion posible:
# es un signo invertido y el fondo-anio pasa a candidato (tipo signo_invertido).
# Codigos que son subtotales o totales (para "subtotal unico invertido", H7).
RE_SUBTOTAL_XML = r"^(Total|FlujoNeto|AumentoNeto|Utilidad|AumentoDisminucion|ActivoNetoAtribuible)"

CONVENCION_SIGNO = ("Rescate|Compra|Comision|MontosPagados|Gastos|Honorarios|"
                    "CostosDeTransaccion|Remuneraciones|CuentasPorPagar")

# Codigos del ECP usados por las reglas (el XML agrega "PorSerie" por serie)
CODS_ECP = {
    "inicio": "ActivoNetoAtribuibleALosParticipesAl01DeEnero",
    "neto": "AumentoNetoOriginadoPorTransaccionesDeCuotas",
    "cierre": "ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuota",
}


def clasificar_pares(faltantes, huerfanos):
    """faltantes, huerfanos: listas de montos con signo (de un fondo-anio).

    Firmas de una discrepancia REAL:
      - redistribucion: la suma de lo faltante = la suma de lo huerfano
        (caso H1: series redistribuidas, el total cuadra).
      - discrepancia_consistente: la misma diferencia aparece en 2+ cifras
        distintas: un numero distinto en una linea, arrastrado a los
        subtotales (un caso: 12.237 en compras, flujo neto y
        aumento neto de efectivo).
    Si no: par_aislado (un par cercano) o sin_par_plausible (lectura).

    Se trabaja sobre montos UNICOS: la misma cifra repetida en el PDF
    (p.ej. filas 'antes' y 'despues' de distribucion) no cuenta dos veces.
    Devuelve (tipo, delta_principal, n_pares_cercanos)."""
    falt = sorted(set(faltantes), key=abs)
    huer = sorted(set(huerfanos), key=abs)
    if not falt or not huer:
        return "sin_par_plausible", 0, 0

    def distancia(v):
        return min(abs(abs(x) - abs(v)) for x in huer)

    if len(falt) >= 2 and abs(sum(falt) - sum(huer)) <= len(falt):
        # Tamano: la cifra peor asignada (distancia a su huerfano mas cercano).
        return "redistribucion", max(distancia(v) for v in falt), 0

    deltas, cercanos = [], 0
    for v in falt:
        delta = distancia(v)
        if abs(v) >= MIN_MONTO_PAR and delta <= MAX_DIF_RELATIVA_PAR * abs(v):
            cercanos += 1
        if delta:
            deltas.append(delta)

    repetidos = [d for d in set(deltas) if deltas.count(d) >= 2]
    if repetidos:
        return "discrepancia_consistente", max(repetidos), cercanos
    if cercanos:
        cerc = [distancia(v) for v in falt
                if abs(v) >= MIN_MONTO_PAR and distancia(v) <= MAX_DIF_RELATIVA_PAR * abs(v)]
        return "par_aislado", max(cerc), cercanos
    return "sin_par_plausible", 0, 0


def unir(serie: pd.Series) -> str:
    """Valores distintos, ordenados y separados por coma, ignorando nulos."""
    return ",".join(sorted(serie.dropna().astype(str).unique()))


def estado_financiero(codigo: str) -> str:
    """Clasificacion APROXIMADA por palabras clave del codigo de cuenta."""
    c = str(codigo).lower()
    if "porserie" in c or "cuotas" in c or "al01deenero" in c or "distribucion" in c:
        return "ECP"
    if any(k in c for k in ("flujo", "compra", "ventacobro", "saldo", "pagados",
                            "recibidos", "aumentonetodeefectivo")):
        return "EFE"
    if any(k in c for k in ("total", "cuentas", "efectivoyefectivo", "activos",
                            "pasivos", "remuneraciones", "rescates")):
        return "ESF"
    return "ERI"


def leer_cuentas(archivos) -> pd.DataFrame:
    """Una sola lectura de cuentas.csv: activo neto + codigos del ECP,
    solo para los archivos indicados."""
    cods = set(CODIGOS_ACTIVO_NETO) | {c + s for c in CODS_ECP.values()
                                        for s in ("", "PorSerie")}
    cta = pd.read_csv(DIR_PROC / "cuentas.csv",
                      usecols=["archivo", "contexto", "codigo", "serie", "valor"],
                      dtype={"serie": str})
    return cta[cta["archivo"].isin(set(archivos)) & cta["codigo"].isin(cods)]


def activo_neto_por_fondo(cta: pd.DataFrame) -> pd.Series:
    """Activo neto (o total activo) del periodo actual, por archivo XML."""
    an = cta[(cta["contexto"] == "PeriodoActual") & cta["serie"].isna()
             & cta["codigo"].isin(CODIGOS_ACTIVO_NETO)].copy()
    # Preferir activo neto; si no existe, total activo.
    an["orden"] = an["codigo"].map({c: i for i, c in enumerate(CODIGOS_ACTIVO_NETO)})
    return (an.sort_values("orden").drop_duplicates("archivo")
            .set_index("archivo")["valor"].abs())


def tablas_ecp(cta: pd.DataFrame) -> dict:
    """archivo -> DataFrame indexado por (contexto, serie) con columnas
    inicio, neto, cierre. El total del fondo queda como serie 'TOTAL'."""
    base = cta["codigo"].str.replace("PorSerie", "", regex=False)
    e = cta[base.isin(CODS_ECP.values())].copy()
    e["campo"] = base[e.index].map({v: k for k, v in CODS_ECP.items()})
    e["serie"] = e["serie"].fillna("TOTAL")
    t = e.pivot_table(index=["archivo", "contexto", "serie"], columns="campo",
                      values="valor", aggfunc="first")
    return {a: g.droplevel(0) for a, g in t.groupby(level=0)}


def cerca(v, conjunto, tol=TOL_MONTO) -> bool:
    return any(abs(v - x) <= tol for x in conjunto)


def sumas_saldo_acumulado(ecp) -> set:
    """inicio + neto de cada serie y del total, en ambos periodos. Un huerfano
    con ese valor es la fila de 'saldo' que algunas AGF agregan al ECP."""
    if ecp is None:
        return set()
    g = ecp.dropna(subset=["inicio", "neto"])
    return set((g["inicio"] + g["neto"]).round())


def firma_series_por_posicion(huerfanos, ecp) -> bool:
    """Huella del caso H1: el XML carga inicio y neto por posicion
    de columna, con el cierre en la serie correcta. Entonces el resultado que
    imprime el PDF para la serie u es cierre(u) - inicio(t) - neto(t) con t
    otra serie del XML. Se exige que 2+ huerfanos calcen con esa forma."""
    if ecp is None:
        return False
    calzan = set()
    for _, g in ecp.groupby(level=0):              # por contexto
        g = g.droplevel(0).drop("TOTAL", errors="ignore")
        g = g.dropna(subset=["inicio", "neto", "cierre"])
        s = list(g.index)
        if len(s) < 2:
            continue
        # La serie t "presta" su inicio y neto: si son casi cero, el combo es
        # practicamente el cierre de u y calza con cualquier cierre redondeado
        # (falso positivo visto en un fondo con series nuevas: inicio 0, neto -1).
        donantes = [t for t in s
                    if abs(g.at[t, "inicio"]) + abs(g.at[t, "neto"]) >= MIN_MONTO_PAR]
        combos = {g.at[u, "cierre"] - g.at[t, "inicio"] - g.at[t, "neto"]
                  for u in s for t in donantes if u != t}
        calzan |= {h for h in huerfanos if cerca(h, combos)}
    return len(calzan) >= 2


def suma_de_dos_huerfanos(faltantes, huer_por_pagina) -> bool:
    """El XML agrega en un codigo dos lineas del PDF (p.ej. venta/cobro en
    dos lineas, 'liquidacion de instrumentos', un gasto positivo llevado a
    otros ingresos): la cifra XML faltante es la suma de dos huerfanos de la
    misma pagina."""
    falt = set(faltantes)
    for hs in huer_por_pagina.values():
        hs = sorted(set(hs))
        sumas = {a + b for i, a in enumerate(hs) for b in hs[i + 1:]}
        if any(cerca(f, sumas) for f in falt):
            return True
    return False


def subtipo_probable(tipo, delta, falt_vals, falt_cods, huer, huer_pag, n_saldo, ecp) -> str:
    """Pista para la verificacion manual. El orden importa: de la firma mas
    especifica a la mas generica."""
    # Series por posicion: se evalua en todo tipo de par (un caso puede quedar
    # como discrepancia consistente si ademas hay redondeos).
    if firma_series_por_posicion(huer, ecp):
        return "redistribucion_series"
    # Agregacion: el XML junta en un codigo dos lineas del PDF. Incluye la
    # linea sin codigo en la taxonomia y la reclasificacion de una linea con
    # codigo hacia otra (muestra: 9/9). Cual de las dos es, se ve a mano.
    if suma_de_dos_huerfanos(falt_vals, huer_pag):
        return "agregacion_xml"
    if n_saldo and any(str(c).startswith(CODS_ECP["neto"]) for c in falt_cods):
        return "rotulo_incorrecto"
    if delta <= MAX_DELTA_REDONDEO:
        # No se llama "redondeo": un delta chico tambien puede ser un PDF
        # que no suma (muestra id 7, delta 2, gravedad 3).
        return "dif_menor"
    return ""


def validar_contra_muestra(cand: pd.DataFrame) -> None:
    """Si existe la planilla de verificacion, cruza subtipo manual vs probable."""
    ruta = BASE_DIR / "verificacion" / "muestra_verificacion.xlsx"
    if not ruta.exists():
        return
    try:
        m = pd.read_excel(ruta, sheet_name="Muestra", dtype={"rut": str})
    except Exception as e:  # noqa: BLE001  (planilla abierta, hoja renombrada...)
        print(f"aviso: no se pudo leer la muestra ({e})")
        return
    m = m[["rut", "anio", "subtipo"]].dropna(subset=["subtipo"])
    m["subtipo"] = m["subtipo"].replace({"linea_sin_cod": "linea_sin_codigo"})
    v = m.merge(cand[["rut", "anio", "subtipo_probable"]], on=["rut", "anio"], how="left")
    v["subtipo_probable"] = v["subtipo_probable"].fillna("(no candidato)").replace("", "(sin regla)")
    print("validacion contra la muestra (filas: manual, columnas: regla):")
    print(pd.crosstab(v["subtipo"], v["subtipo_probable"]).to_string(), "\n")


def main():
    res = pd.read_csv(DIR_PROC / "cruce_resumen.csv", dtype={"rut": str})
    det = pd.read_csv(DIR_PROC / "cruce_detalle.csv", dtype={"rut": str, "serie": str})
    enc = pd.read_csv(DIR_PROC / "encabezados.csv", dtype={"rut": str, "rut_agf": str})
    enc_vig = enc[enc["es_ultimo_envio"]]

    ok = res[res["estado"] == "ok"].merge(
        enc_vig[["rut", "anio", "archivo", "rut_agf"]], on=["rut", "anio"], how="left")

    # --- Clasificacion de cada fondo-anio evaluado ---
    hay_faltantes = ok["no_encontrado"] > 0
    hay_pares = ok["huerfanos_pdf"] >= MIN_RATIO_PARES * ok["no_encontrado"]
    ok["clase"] = "espejo_ok"
    ok.loc[hay_faltantes & hay_pares & (ok["huerfanos_pdf"] > 0), "clase"] = "candidato"
    ok.loc[hay_faltantes & ~hay_pares, "clase"] = "verificacion_parcial"

    # --- Signo invertido fuera de convencion ---
    sig = det[(det["estado"] == "signo_distinto")
              & ~det["codigo"].str.contains(CONVENCION_SIGNO, na=False)].copy()
    n_sig = sig.groupby(["rut", "anio"]).size().rename("signo_invertido").reset_index()
    ok = ok.merge(n_sig, on=["rut", "anio"], how="left")
    ok["signo_invertido"] = ok["signo_invertido"].fillna(0).astype(int)
    # Un espejo_ok con signo invertido ya no es espejo: pasa a candidato.
    solo_signo = (ok["clase"] == "espejo_ok") & (ok["signo_invertido"] > 0)
    ok.loc[solo_signo, "clase"] = "candidato"

    cand = ok[ok["clase"] == "candidato"].copy()

    # --- Detalle de las cifras faltantes de cada candidato ---
    falt = det[det["estado"] == "no_encontrado"].merge(
        cand[["rut", "anio"]], on=["rut", "anio"])
    falt["estado_fin"] = falt["codigo"].map(estado_financiero)
    # Contextos fuera de los dos esperados conservan su nombre (o quedan como
    # "sin_contexto"): no se descartan, porque son informacion en si mismos.
    falt["periodo"] = (falt["contexto"]
                       .map({"PeriodoActual": "actual", "PeriodoAnterior": "anterior"})
                       .fillna(falt["contexto"]).fillna("sin_contexto"))

    agg = falt.groupby(["rut", "anio"]).agg(
        max_faltante=("valor_xml", lambda s: s.abs().max()),
        estados=("estado_fin", unir),
        periodos=("periodo", unir),
        solo_por_serie=("serie", lambda s: s.notna().all()),
    ).reset_index()
    cand = cand.merge(agg, on=["rut", "anio"], how="left")

    # Para los que son candidatos SOLO por signo, estado/periodo/monto salen de
    # las cifras con signo invertido (no tienen cifras faltantes).
    sig["estado_fin"] = sig["codigo"].map(estado_financiero)
    sig["periodo"] = sig["contexto"].map({"PeriodoActual": "actual", "PeriodoAnterior": "anterior"})
    agg_sig = sig.groupby(["rut", "anio"]).agg(
        sig_max=("valor_xml", lambda s: s.abs().max()),
        sig_n=("codigo", "size"),
        sig_subtotal=("codigo", lambda s: s.str.match(RE_SUBTOTAL_XML).all()),
        sig_estados=("estado_fin", unir), sig_periodos=("periodo", unir)).reset_index()
    cand = cand.merge(agg_sig, on=["rut", "anio"], how="left")
    sin_falt = cand["max_faltante"].isna() & cand["sig_max"].notna()
    cand.loc[sin_falt, "max_faltante"] = cand.loc[sin_falt, "sig_max"]
    cand.loc[sin_falt, "estados"] = cand.loc[sin_falt, "sig_estados"]
    cand.loc[sin_falt, "periodos"] = cand.loc[sin_falt, "sig_periodos"]

    # --- Datos del XML necesarios para las reglas (una sola lectura) ---
    cta = leer_cuentas(cand["archivo"].dropna())
    ecp_por_archivo = tablas_ecp(cta)

    # --- Huerfanos: separar la fila de saldo acumulado del ECP ---
    hue = pd.read_csv(DIR_PROC / "cruce_huerfanos.csv", dtype={"rut": str})
    hue = hue.merge(cand[["rut", "anio", "archivo"]], on=["rut", "anio"])
    saldos = {a: sumas_saldo_acumulado(ecp_por_archivo.get(a)) for a in hue["archivo"].unique()}
    hue["saldo_acumulado"] = [cerca(m, saldos[a]) for m, a in zip(hue["monto_pdf"], hue["archivo"])]

    claves = list(zip(cand["rut"], cand["anio"]))
    hue_todos = hue.groupby(["rut", "anio"])["monto_pdf"].apply(list).to_dict()
    hue_utiles = hue[~hue["saldo_acumulado"]].groupby(["rut", "anio"])["monto_pdf"].apply(list).to_dict()
    hue_pag = (hue[~hue["saldo_acumulado"]].groupby(["rut", "anio", "pagina"])["monto_pdf"]
               .apply(list))
    hue_pag = {k: g.droplevel([0, 1]).to_dict() for k, g in hue_pag.groupby(level=[0, 1])}
    n_saldo = hue[hue["saldo_acumulado"]].groupby(["rut", "anio"]).size().to_dict()
    falt_vals = falt.groupby(["rut", "anio"])["valor_xml"].apply(list).to_dict()
    falt_cods = falt.groupby(["rut", "anio"])["codigo"].apply(set).to_dict()

    # --- Emparejamiento real: que tipo de par es? ---
    # Con los huerfanos utiles; si la fila de saldo era todo lo que habia,
    # se usa el total (no se pierde el candidato por la exclusion).
    tipos = [clasificar_pares(falt_vals.get(k, []), hue_utiles.get(k) or hue_todos.get(k, []))
             for k in claves]
    cand["tipo"] = [t[0] for t in tipos]
    cand["delta_principal"] = [t[1] for t in tipos]
    cand["pares_cercanos"] = [t[2] for t in tipos]
    cand["posible_redondeo_acumulado"] = cand["tipo"].isin(
        ["discrepancia_consistente", "par_aislado"]) & (cand["delta_principal"] <= MAX_DELTA_REDONDEO)
    cand["huerfanos_saldo_acumulado"] = [n_saldo.get(k, 0) for k in claves]

    # Candidatos solo por signo: tipo propio. Delta = 2 x |cifra| (de v a -v).
    cand.loc[sin_falt, "tipo"] = "signo_invertido"
    cand.loc[sin_falt, "delta_principal"] = 2 * cand.loc[sin_falt, "sig_max"]

    cand["subtipo_probable"] = [
        subtipo_probable(tipo, delta, falt_vals.get(k, []), falt_cods.get(k, set()),
                         hue_utiles.get(k, []), hue_pag.get(k, {}), n_saldo.get(k, 0),
                         ecp_por_archivo.get(a))
        for k, a, tipo, delta in zip(claves, cand["archivo"], cand["tipo"], cand["delta_principal"])]
    cand.loc[sin_falt, "subtipo_probable"] = "error_signo"

    # --- Gravedad automatica: solo donde la regla la DEMUESTRA (ver D22) ---
    # 3: subtotal unico invertido en un fondo que por lo demas cuadra (H7: si
    #    las lineas coinciden en signo y el XML suma, el PDF no puede sumar);
    #    series cargadas por posicion (H1: resultados forzados).
    # 2: rotulo incorrecto (cambia un subtotal relevante, saldo final igual).
    # 1: agregacion en el XML (dentro de un subtotal).
    # Vacio: requiere revision manual (incluye dif_menor: un delta chico
    #    tambien puede ser un PDF que no suma, muestra id 7).
    cand["gravedad_auto"] = pd.Series(pd.NA, index=cand.index, dtype="Int64")
    unico = sin_falt & (cand["sig_n"] == 1) & cand["sig_subtotal"].fillna(False).astype(bool)
    cand.loc[unico, "gravedad_auto"] = 3
    cand.loc[cand["subtipo_probable"] == "redistribucion_series", "gravedad_auto"] = 3
    cand.loc[cand["subtipo_probable"] == "rotulo_incorrecto", "gravedad_auto"] = 2
    cand.loc[cand["subtipo_probable"] == "agregacion_xml", "gravedad_auto"] = 1

    # Los "sin par plausible" no son candidatos: son problemas de lectura.
    sin_par = cand["tipo"] == "sin_par_plausible"
    ok.loc[ok.set_index(["rut", "anio"]).index.isin(
        cand.loc[sin_par].set_index(["rut", "anio"]).index), "clase"] = "verificacion_parcial"

    # --- Materialidad ---
    an = activo_neto_por_fondo(cta)
    cand["activo_neto"] = cand["archivo"].map(an)
    # Materialidad sobre la DIFERENCIA, no sobre el tamano de la linea.
    # En una redistribucion la diferencia neta es cero: el delta_principal es
    # el monto movido entre lineas, no un error. Se deja n/a (vacio).
    cand["materialidad_pct"] = (100 * cand["delta_principal"] / cand["activo_neto"]).round(4)
    cand.loc[cand["tipo"] == "redistribucion", "materialidad_pct"] = float("nan")
    # Umbral absoluto por moneda (config.py). Decide si el caso se revisa a mano:
    #   observacion_inmaterial: diferencia <= umbral (se registra, no se revisa)
    #   gravedad_auto: la regla ya demuestra la gravedad
    #   revision_manual: el resto
    cand["umbral_materialidad"] = cand["moneda"].map(umbral_materialidad)
    cand["revision"] = "revision_manual"
    cand.loc[cand["gravedad_auto"].notna(), "revision"] = "gravedad_auto"
    cand.loc[cand["delta_principal"].abs() <= cand["umbral_materialidad"], "revision"] = "observacion_inmaterial"

    columnas = ["rut", "anio", "nombre_fondo", "nombre_agf", "rut_agf", "auditor_firma",
                "moneda", "tipo", "subtipo_probable", "gravedad_auto", "revision", "umbral_materialidad",
                "delta_principal", "posible_redondeo_acumulado",
                "pares_cercanos", "huerfanos_saldo_acumulado", "signo_invertido", "pct_tolerante", "no_encontrado", "huerfanos_pdf",
                "estados", "periodos", "solo_por_serie", "max_faltante",
                "activo_neto", "materialidad_pct", "paginas_sin_tabla", "reparado", "pdf"]
    cand = cand[~sin_par].sort_values(["tipo", "materialidad_pct"], ascending=[True, False])
    cand[columnas].to_csv(DIR_PROC / "candidatos.csv", index=False, encoding="utf-8-sig")

    # --- Por AGF, como tasa ---
    nombre = ok.groupby("rut_agf")["nombre_agf"].agg(lambda s: s.value_counts().index[0])
    por_agf = ok.groupby("rut_agf")["clase"].value_counts().unstack(fill_value=0)
    por_agf["evaluados"] = por_agf.sum(axis=1)
    por_agf["tasa_candidatos_pct"] = (100 * por_agf.get("candidato", 0)
                                      / por_agf["evaluados"]).round(1)
    por_agf.insert(0, "agf", nombre)
    por_agf = por_agf.sort_values("tasa_candidatos_pct", ascending=False)
    por_agf.to_csv(DIR_PROC / "candidatos_por_agf.csv", encoding="utf-8-sig")

    # --- Resumen en consola ---
    raros = det[~det["contexto"].isin(["PeriodoActual", "PeriodoAnterior"])]
    if len(raros):
        print(f"aviso: {len(raros)} cifras con contexto no estandar en el detalle:")
        print(raros["contexto"].fillna("(vacio)").value_counts().head(5).to_string(), "\n")
    print(f"fondo-anio evaluados: {len(ok)}")
    print(ok["clase"].value_counts().to_string(), "\n")
    if len(cand):
        print("candidatos por tipo de par:")
        print(cand["tipo"].value_counts().to_string())
        print(f"  (consistentes o aislados con diferencia <= {MAX_DELTA_REDONDEO}, posible redondeo: "
              f"{cand['posible_redondeo_acumulado'].sum()})\n")
        print("subtipo probable (pista, no veredicto):")
        print(cand["subtipo_probable"].replace("", "(sin regla)").value_counts().to_string(), "\n")
        print("gravedad automatica (solo donde la regla la demuestra):")
        print(cand["gravedad_auto"].astype("string").fillna("revision manual").value_counts().to_string(), "\n")
        print("revision (materialidad por moneda, config.py):")
        print(cand["revision"].value_counts().to_string(), "\n")
        print("candidatos por estado y periodo de las cifras faltantes:")
        print(cand.groupby(["estados", "periodos"]).size()
              .sort_values(ascending=False).head(10).to_string(), "\n")
        print("materialidad (diferencia / activo neto; n/a en redistribuciones):")
        print(pd.cut(cand["materialidad_pct"], [0, 0.01, 0.1, 1, 10, float("inf")],
                     labels=["<0,01%", "0,01-0,1%", "0,1-1%", "1-10%", ">10%"])
              .value_counts().sort_index().to_string(), "\n")
        print("AGF con mayor tasa de candidatos (min. 20 fondo-anio evaluados):")
        print(por_agf[por_agf["evaluados"] >= 20][["agf", "evaluados", "tasa_candidatos_pct"]]
              .head(8).to_string())
    validar_contra_muestra(cand)
    print(f"salida: {DIR_PROC / 'candidatos.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())