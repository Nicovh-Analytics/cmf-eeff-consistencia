"""
Cruce XML -> PDF (v2: extraccion en paralelo con cache)
=======================================================

Premisa: el XML es la referencia; se audita si el PDF auditado (lo que
lee el publico) representa fielmente esas cifras en los estados
financieros principales.

El script tiene DOS etapas separadas a proposito:

  ETAPA 1 - Extraccion (cara, se hace UNA vez, en paralelo)
    Lee el texto de las primeras paginas de cada PDF y lo guarda en
    data/texto_pdf/{rut}/{anio}/{pdf}.json, junto con los metadatos del
    PDF (fecha de creacion / modificacion). Si el JSON ya existe, se
    salta. Usa varios procesos: cada PDF es independiente.

  ETAPA 2 - Cruce (barata, se repite cada vez que ajustes la logica)
    Lee los JSON, ubica las paginas de estados y compara contra el XML.
    Como no relee PDFs, toma segundos/minutos sobre todo el universo.

  Si cambias algo de la ETAPA 2 (umbrales, deteccion de paginas, signos),
  solo vuelve a correr el script: la etapa 1 sale entera desde cache.
  Si cambias algo de la ETAPA 1 (p.ej. MAX_PAGINAS), borra data/texto_pdf.

Lee:      data/procesado/encabezados.csv, cuentas.csv  (02_parser)
          data/archivos/{rut}/{anio}/FMNO*.pdf          (01_recolector)
Escribe:  data/texto_pdf/...                            (cache etapa 1)
          data/procesado/cruce_resumen.csv              1 fila por fondo-anio
          data/procesado/cruce_detalle.csv              cifras XML que NO calzan
          data/procesado/cruce_huerfanos.csv            montos PDF sin par en XML
"""

import json
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DIR_ARCHIVOS = BASE_DIR / "data" / "archivos"
DIR_PROC = BASE_DIR / "data" / "procesado"
DIR_TEXTO = BASE_DIR / "data" / "texto_pdf"

# --- Etapa 1 ---
MAX_PAGINAS = 25          # los estados estan al inicio; las notas no se cachean
N_PROCESOS = max(1, (os.cpu_count() or 2) - 2)   # deja dos nucleos libres

# Texto espaciado (ej. "2 .5 6 1 .2 9 8"): algunas tablas tienen las letras
# mas separadas que el umbral por defecto de pdfplumber (3 pt). Esas paginas
# se re-extraen con una tolerancia mayor. Probado en un caso real: falla
# con 3, funciona de 4 a 8 sin pegar columnas. Se usa 5 por margen.
# v3: algunas paginas siguen espaciadas con 5: se guardan
# varias tolerancias y el cruce elige la mejor por pagina.
TOLS_ALT = (5, 8, 12)
TOL_ALT = TOLS_ALT[0]        # compatibilidad con mensajes
# Version del detector/re-extraccion. Si cambia, la etapa 1b vuelve a revisar
# todos los JSON. v2: numeros con digitos separados (un monto por linea).
# v3: varias tolerancias por pagina.
ALT_VERSION = 3
RE_NUM_ESPACIADO = re.compile(r"\d \.\d|\d \d \d")

# --- Etapa 2 ---
MIN_ACIERTOS_PAGINA = 3      # una pagina "es de estados" si calza >= 3 cifras
UMBRAL_MATCH_DEBIL = 1000    # en miles de pesos
TOLERANCIA_REDONDEO = 1      # diferencia maxima para "ok_redondeo" (miles)
MIN_CARACTERES_TEXTO = 200   # menos que esto = PDF escaneado / sin capa de texto
# Escaneados con algo de texto (portada, pie de pagina): ~900 caracteres en
# 25 paginas pasaban el umbral total y caian en sin_paginas_de_estados.
# Una pagina de estados con texto real tiene miles de caracteres.
MIN_CARACTERES_POR_PAGINA = 100   # promedio sobre las paginas extraidas

RE_MONTO = re.compile(
    r"(?<![\d.,])"
    r"(\(\s?)?([-\u2212\u2013])?(\d{1,3}(?:\.\d{3})+|\d+)(\s?\))?"
    r"(?![\d,]|\.\d)"
)
# Titulos de los 4 estados principales. Sirven para detectar paginas de
# estados SIN tabla legible (ej. un EFE publicado como imagen;
# la pagina solo tiene el encabezado de texto).
RE_TITULO_ESTADO = re.compile(
    r"estados?\s+de\s+(situaci[oó]n\s+financiera|resultados?\s+integral"
    r"|cambios?\s+en\s+el\s+activo\s+neto|flujos?\s+de\s+efectivo)", re.I)
RE_INDICE = re.compile(r"\b(contenido|[íi]ndice)\b", re.I)
MAX_CARACTERES_SIN_TABLA = 500

# Monto partido por un espacio tras el/los primer(os) digito(s):
#   "6 .526" -> 6.526 | "8 6.389.311" -> 86.389.311 | "3 50.354" -> 350.354
# (caso observado). Solo se usa como CANDIDATO: cuenta si coincide
# exactamente con una cifra del XML, porque "15 5.233.424" (nota 15 + monto)
# tambien encaja en el patron y no debe unirse.
RE_PARTIDO = re.compile(
    r"(?<![\d.,])(\()?(\d{1,2}) (\d{0,2}\.\d{3}(?:\.\d{3})*)(\))?(?![\d,]|\.\d)")
RE_FORMATO_CL = re.compile(r"^\d{1,3}(?:\.\d{3})+$")

RE_INICIO_NOTAS = re.compile(r"NOTAS\s+A\s+LOS\s+ESTADOS\s+FINANCIEROS", re.I)
RE_TIMESTAMP = re.compile(r"_(\d{8}_\d{6})_")


# ===========================================================================
# ETAPA 1 - EXTRACCION
# ===========================================================================

def ruta_cache(ruta_pdf: Path) -> Path:
    rel = ruta_pdf.relative_to(DIR_ARCHIVOS)
    return DIR_TEXTO / rel.with_suffix(".json")


def extraer_pdf(ruta_pdf_str: str) -> str:
    """Corre en un proceso aparte. Extrae y guarda el JSON; devuelve un
    estado corto para el contador de progreso.

    Tiene que ser una funcion de nivel superior (no anidada) para que
    Windows pueda enviarla a otro proceso."""
    import pdfplumber  # se importa en cada proceso hijo

    ruta_pdf = Path(ruta_pdf_str)
    destino = ruta_cache(ruta_pdf)
    salida = {"pdf": ruta_pdf.name, "error": None, "n_paginas": 0,
              "metadata": {}, "paginas": []}

    try:
        with open(ruta_pdf, "rb") as f:
            cabecera = f.read(1024)
        # Un PDF real empieza con %PDF (a veces tras unos bytes de basura).
        if b"%PDF" not in cabecera:
            salida["error"] = "no_es_pdf"
            salida["cabecera"] = cabecera[:200].decode("latin-1", errors="replace")
        else:
            with pdfplumber.open(ruta_pdf) as pdf:
                salida["n_paginas"] = len(pdf.pages)
                salida["metadata"] = {k: str(v) for k, v in (pdf.metadata or {}).items()
                                      if k in ("CreationDate", "ModDate", "Producer", "Creator")}
                salida["paginas"] = [(p.extract_text() or "")
                                     for p in pdf.pages[:MAX_PAGINAS]]
    except Exception as e:  # noqa: BLE001 - se registra y se sigue
        salida["error"] = f"error_pdf: {type(e).__name__}: {e}"[:300]

    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".json.part")
    temporal.write_text(json.dumps(salida, ensure_ascii=False), encoding="utf-8")
    temporal.replace(destino)       # escritura atomica: nunca queda un JSON a medias
    return "error" if salida["error"] else "ok"


def linea_espaciada(linea):
    tok = linea.split()
    return len(tok) >= 10 and sum(len(t) == 1 for t in tok) / len(tok) > 0.6


def pagina_espaciada(texto):
    """Dos formas del mismo problema:
    - plantilla 1: muchas letras sueltas en una misma linea.
    - plantilla 2: extraccion por columnas, un monto por linea ('5 6 .1 3 5 .9 6 1')."""
    return (sum(linea_espaciada(l) for l in texto.splitlines()) >= 3
            or len(RE_NUM_ESPACIADO.findall(texto)) >= 5)


def reextraer_espaciadas(ruta_pdf_str: str) -> int:
    """Corre en un proceso aparte. Re-extrae con TOL_ALT las paginas que
    parecen espaciadas y las guarda en el JSON como 'paginas_alt'.
    Devuelve cuantas paginas re-extrajo. Marca 'tol_alt' para no repetir."""
    import pdfplumber

    destino = ruta_cache(Path(ruta_pdf_str))
    datos = json.loads(destino.read_text(encoding="utf-8"))
    if datos["error"] or datos.get("alt_version") == ALT_VERSION:
        return 0

    marcadas = [i for i, t in enumerate(datos["paginas"]) if pagina_espaciada(t)]
    alt = {}
    if marcadas:
        try:
            with pdfplumber.open(ruta_pdf_str) as pdf:
                for i in marcadas:
                    alt[str(i + 1)] = [pdf.pages[i].extract_text(x_tolerance=tol) or ""
                                       for tol in TOLS_ALT]
        except Exception:  # noqa: BLE001 - sin alternativa, se usa la original
            alt = {}

    datos["paginas_alt"] = alt
    datos["tol_alt"] = list(TOLS_ALT)
    datos["alt_version"] = ALT_VERSION
    temporal = destino.with_suffix(".json.part")
    temporal.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    temporal.replace(destino)
    return len(alt)


def etapa_reextraccion(pdfs):
    """Pasada 1b: solo toca PDFs con paginas espaciadas. Los JSON ya
    revisados (tol_alt = TOL_ALT) se saltan rapido dentro de cada proceso."""
    con_cache = [p for p in pdfs if ruta_cache(p).exists()]
    print(f"[1b]  Re-extraccion de paginas espaciadas (x_tolerance={TOLS_ALT})")
    inicio, hechos, paginas = time.time(), 0, 0
    with ProcessPoolExecutor(max_workers=N_PROCESOS) as ex:
        for fut in as_completed([ex.submit(reextraer_espaciadas, str(p)) for p in con_cache]):
            hechos += 1
            paginas += fut.result()
            if hechos % 500 == 0 or hechos == len(con_cache):
                print(f"      {hechos}/{len(con_cache)} | paginas re-extraidas {paginas} "
                      f"| {(time.time() - inicio) / 60:.1f} min")


def etapa_extraccion(pdfs):
    # Pendiente = sin cache, o PDF modificado despues de su cache (p.ej. un
    # PDF reemplazado a mano: los 13 recuperados de H8). Solo se usa stat().
    def pendiente(p):
        c = ruta_cache(p)
        return not c.exists() or p.stat().st_mtime > c.stat().st_mtime
    pendientes = [p for p in pdfs if pendiente(p)]
    print(f"[1/2] Extraccion: {len(pdfs)} PDF, {len(pendientes)} pendientes, "
          f"{N_PROCESOS} procesos")
    if not pendientes:
        return

    inicio, hechos, errores = time.time(), 0, 0
    with ProcessPoolExecutor(max_workers=N_PROCESOS) as ex:
        futuros = [ex.submit(extraer_pdf, str(p)) for p in pendientes]
        for fut in as_completed(futuros):
            hechos += 1
            if fut.result() == "error":
                errores += 1
            if hechos % 100 == 0 or hechos == len(pendientes):
                seg = time.time() - inicio
                resta = seg / hechos * (len(pendientes) - hechos)
                print(f"      {hechos}/{len(pendientes)} | errores {errores} "
                      f"| {seg / 60:.1f} min | faltan ~{resta / 60:.1f} min")


# ===========================================================================
# ETAPA 2 - CRUCE
# ===========================================================================

def montos_de_texto(texto):
    """Lista de (monto con signo, tiene_separador_de_miles)."""
    salida = []
    for abre, menos, num, cierra in RE_MONTO.findall(texto):
        valor = int(num.replace(".", ""))
        if (abre and cierra) or menos:
            valor = -valor
        salida.append((valor, "." in num))
    return salida


def montos_unidos(texto):
    """Candidatos de montos partidos. Devuelve lista de
    (monto_unido con signo, fragmento_derecho con signo)."""
    salida = []
    for abre, izq, der, cierra in RE_PARTIDO.findall(texto):
        unido = izq + der
        if not RE_FORMATO_CL.match(unido):
            continue
        signo = -1 if (abre and cierra) else 1
        salida.append((signo * int(unido.replace(".", "")),
                       signo * int(der.replace(".", "") or 0)))
    return salida


def paginas_de_estados(textos, valores_xml_abs, alternativas=None):
    """Ubica paginas de estados por CONTENIDO (>= N cifras del XML),
    deteniendose al empezar las notas.

    Si una pagina tiene version alternativa (re-extraida con otra
    tolerancia), se queda con la que encuentra mas cifras del XML.
    Devuelve (paginas: dict n -> montos, usadas_alt: list de n)."""
    alternativas = alternativas or {}
    paginas, usadas_alt, sin_tabla = {}, [], []

    # Encabezado corrido: algunas plantillas (una AGF, 2011-2015) ponen
    # "NOTAS A LOS ESTADOS FINANCIEROS" en el encabezado de TODAS las paginas,
    # incluidas las de estados. Ahi la frase no marca el inicio de las notas:
    # se reemplaza por "termina en la primera pagina sin cifras despues de
    # haber encontrado estados".
    # Se reconoce porque la PRIMERA pagina con cifras del XML ya trae la frase
    # en el encabezado y ademas el titulo de un estado en sus primeras lineas.
    # (En una plantilla normal, la primera pagina con cifras es un estado sin
    # la frase; si los estados fueran imagen, la primera con cifras seria una
    # nota, sin titulo de estado arriba: no se activa.)
    def encabezado_de(t, n=3):
        return "\n".join(t.splitlines()[:n])
    def calces(t):
        return sum(1 for m, _ in montos_de_texto(t) if abs(m) in valores_xml_abs)
    primera = next((t for i, t in enumerate(textos, 1)
                    if i > 2 and calces(t) >= MIN_ACIERTOS_PAGINA), None)
    encabezado_corrido = bool(primera
                              and RE_INICIO_NOTAS.search(encabezado_de(primera))
                              and RE_TITULO_ESTADO.search(encabezado_de(primera, 8)))

    for i, texto in enumerate(textos, 1):
        # La frase tiene que ser ENCABEZADO de la pagina (primeras lineas).
        # Si esta mas abajo, puede ser un indice que solo la menciona
        # (caso observado: indice en la pag. 4 que lista las notas).
        encabezado = encabezado_de(texto)
        if not encabezado_corrido and i > 2 and RE_INICIO_NOTAS.search(encabezado):
            break

        # Pagina de UN estado (titulo en el encabezado) pero casi sin texto:
        # la tabla es una imagen o trazos. Los indices se excluyen porque
        # mencionan VARIOS titulos y dicen "Contenido"/"Indice".
        if (len(texto) < MAX_CARACTERES_SIN_TABLA
                and RE_TITULO_ESTADO.search(encabezado)
                and len(RE_TITULO_ESTADO.findall(texto)) == 1
                and not RE_INDICE.search(texto)):
            sin_tabla.append(i)
        def evaluar(t):
            """Puntaje = (aciertos en montos >= 1.000, aciertos totales).
            Los montos chicos no deciden: un texto espaciado ('2 .5 6 1')
            genera muchos digitos sueltos que calzan por azar con cifras
            chicas del XML y le ganarian en cantidad a la version buena
            (caso observado)."""
            montos = montos_de_texto(t)
            unidos = [(u, f) for u, f in montos_unidos(t) if abs(u) in valores_xml_abs]
            calzan = [abs(m) for m, _ in montos if abs(m) in valores_xml_abs] + \
                     [abs(u) for u, _ in unidos]
            fuertes = sum(1 for a in calzan if a >= UMBRAL_MATCH_DEBIL)
            return montos, unidos, len(calzan), (fuertes, len(calzan))

        montos, unidos, aciertos, puntaje = evaluar(texto)
        versiones = alternativas.get(str(i), [])
        if isinstance(versiones, str):          # cache v2: una sola alternativa
            versiones = [versiones]
        for t_alt in versiones:
            m_a, u_a, a_a, p_a = evaluar(t_alt)
            if p_a > puntaje:
                montos, unidos, aciertos, puntaje = m_a, u_a, a_a, p_a
                if i not in usadas_alt:
                    usadas_alt.append(i)

        if aciertos >= MIN_ACIERTOS_PAGINA:
            paginas[i] = (montos, unidos)
        elif encabezado_corrido and paginas:
            break               # fin del bloque de estados
    return paginas, [n for n in usadas_alt if n in paginas], sin_tabla


def buscar_pdf(rut, anio, archivo_xml):
    """XML y PDF de un mismo envio comparten el timestamp del nombre."""
    candidatos = sorted((DIR_ARCHIVOS / str(rut) / str(anio)).glob("FMNO*.pdf"))
    if not candidatos:
        return None
    m = RE_TIMESTAMP.search(archivo_xml)
    if m:
        exacto = [p for p in candidatos if m.group(1) in p.name]
        if exacto:
            return exacto[0]
    return candidatos[-1]


def cruzar_fondo(enc, cifras):
    rut, anio = enc["rut"], enc["anio"]
    base = {"rut": rut, "anio": anio, "nombre_fondo": enc["nombre_fondo"],
            "nombre_agf": enc["nombre_agf"], "auditor_firma": enc.get("auditor_firma"),
            "moneda": enc.get("moneda"), "reparado": enc.get("reparado")}

    ruta_pdf = buscar_pdf(rut, anio, enc["archivo"])
    if ruta_pdf is None:
        return {**base, "estado": "sin_pdf"}, [], []

    cache = ruta_cache(ruta_pdf)
    if not cache.exists():
        return {**base, "pdf": ruta_pdf.name, "estado": "sin_extraer"}, [], []
    datos = json.loads(cache.read_text(encoding="utf-8"))

    meta = datos.get("metadata", {})
    base.update({"pdf": ruta_pdf.name, "pdf_paginas": datos.get("n_paginas"),
                 "pdf_creado": meta.get("CreationDate"),
                 "pdf_modificado": meta.get("ModDate"),
                 "pdf_producer": meta.get("Producer")})

    if datos["error"]:
        # La CMF a veces devuelve un texto en vez del PDF (ver H8).
        if "ACCION NO PERMITIDA" in datos.get("cabecera", "").upper():
            return {**base, "estado": "pdf_no_disponible_cmf"}, [], []
        return {**base, "estado": datos["error"]}, [], []
    total_chars = sum(len(t) for t in datos["paginas"])
    if (total_chars < MIN_CARACTERES_TEXTO
            or total_chars / max(len(datos["paginas"]), 1) < MIN_CARACTERES_POR_PAGINA):
        return {**base, "estado": "sin_texto"}, [], []

    cifras = cifras[cifras["valor"].fillna(0) != 0]
    valores_xml_abs = set(cifras["valor"].abs().astype("int64"))

    paginas, usadas_alt, sin_tabla = paginas_de_estados(
        datos["paginas"], valores_xml_abs, datos.get("paginas_alt"))
    base["paginas_sin_tabla"] = ",".join(map(str, sin_tabla))
    if not paginas:
        return {**base, "estado": "sin_paginas_de_estados"}, [], []

    signos, donde = {}, {}
    signos_union = {}            # montos que solo aparecen unidos
    fragmentos_usados = set()    # parte derecha de un monto unido: no es huerfano
    for n, (montos, unidos) in paginas.items():
        for m, _ in montos:
            signos.setdefault(abs(m), set()).add(m >= 0)
            donde.setdefault(abs(m), set()).add(n)
        for u, frag in unidos:
            signos_union.setdefault(abs(u), set()).add(u >= 0)
            donde.setdefault(abs(u), set()).add(n)
            fragmentos_usados.add(abs(frag))

    def cerca(a):
        """Hay en el PDF un monto a +-TOLERANCIA_REDONDEO? (solo montos grandes:
        en cifras chicas un +-1 puede ser coincidencia)."""
        return a >= UMBRAL_MATCH_DEBIL and any(
            (a + k) in signos for k in range(-TOLERANCIA_REDONDEO, TOLERANCIA_REDONDEO + 1) if k)

    # Ida: XML -> PDF
    detalle = []
    conteo = {"ok": 0, "ok_debil": 0, "ok_union": 0, "signo_distinto": 0,
              "ok_redondeo": 0, "no_encontrado": 0}
    for c in cifras.itertuples(index=False):
        v = int(c.valor)
        a = abs(v)
        if a not in signos and a in signos_union:
            estado = "ok_union" if (v >= 0) in signos_union[a] else "signo_distinto"
        elif a not in signos:
            estado = "ok_redondeo" if cerca(a) else "no_encontrado"
        elif (v >= 0) in signos[a]:
            estado = "ok_debil" if a < UMBRAL_MATCH_DEBIL else "ok"
        else:
            estado = "signo_distinto"
        conteo[estado] += 1
        if estado != "ok":                       # solo se guarda lo que no calza
            detalle.append({"rut": rut, "anio": anio, "contexto": c.contexto,
                            "codigo": c.codigo, "serie": c.serie, "valor_xml": v,
                            "estado": estado,
                            "paginas": ",".join(map(str, sorted(donde.get(a, []))))})

    # Vuelta: PDF -> XML (solo montos con separador de miles)
    # Un monto a +-1 de una cifra XML ya quedo como ok_redondeo: no es huerfano.
    def en_xml(a):
        return any((a + k) in valores_xml_abs
                   for k in range(-TOLERANCIA_REDONDEO, TOLERANCIA_REDONDEO + 1))

    huerfanos = [{"rut": rut, "anio": anio, "pagina": n, "monto_pdf": m}
                 for n, (montos, _) in paginas.items()
                 for m, con_sep in montos
                 if con_sep and not en_xml(abs(m)) and abs(m) not in fragmentos_usados]

    total = sum(conteo.values())
    encontrados = conteo["ok"] + conteo["ok_debil"] + conteo["ok_union"]
    resumen = {**base, "estado": "ok", "paginas_estados": ",".join(map(str, paginas)),
               "paginas_alt_usadas": ",".join(map(str, usadas_alt)),
               "cifras_xml": total, **conteo, "huerfanos_pdf": len(huerfanos),
               # signo exacto
               "pct_encontrado": round(100 * encontrados / max(total, 1), 1),
               # el monto esta, aunque con otro signo (ej. una AGF muestra
               # gastos en positivo). Los signos siguen visibles en su columna.
               "pct_valor_abs": round(100 * (encontrados + conteo["signo_distinto"])
                                      / max(total, 1), 1),
               # ademas tolera diferencias de redondeo de +-1 (miles)
               "pct_tolerante": round(100 * (encontrados + conteo["signo_distinto"]
                                             + conteo["ok_redondeo"]) / max(total, 1), 1)}
    return resumen, detalle, huerfanos


def etapa_cruce():
    enc = pd.read_csv(DIR_PROC / "encabezados.csv", dtype={"rut": str})
    cta = pd.read_csv(DIR_PROC / "cuentas.csv", dtype={"rut": str, "serie": str})
    enc = enc[enc["es_ultimo_envio"]].fillna({"reparado": ""})
    cuentas_por_archivo = dict(tuple(cta.groupby("archivo")))
    vacio = cta.iloc[0:0]

    print(f"[2/2] Cruce: {len(enc)} fondo-anio")
    resumenes, detalles, huerfanos = [], [], []
    for fila in enc.to_dict("records"):
        r, d, h = cruzar_fondo(fila, cuentas_por_archivo.get(fila["archivo"], vacio))
        resumenes.append(r)
        detalles.extend(d)
        huerfanos.extend(h)

    df_res = pd.DataFrame(resumenes)
    df_res.to_csv(DIR_PROC / "cruce_resumen.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(detalles, columns=["rut", "anio", "contexto", "codigo", "serie",
                                    "valor_xml", "estado", "paginas"]
                 ).to_csv(DIR_PROC / "cruce_detalle.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(huerfanos, columns=["rut", "anio", "pagina", "monto_pdf"]
                 ).to_csv(DIR_PROC / "cruce_huerfanos.csv", index=False, encoding="utf-8-sig")

    print("\n  estados:")
    print(df_res["estado"].str.split(":").str[0].value_counts()
          .to_string().replace("\n", "\n    ").join(["    ", ""]))
    ok = df_res[df_res["estado"] == "ok"]
    if len(ok):
        print(f"\n  de los 'ok': {(ok['pct_encontrado'] == 100).sum()} al 100% "
              f"| {(ok['pct_encontrado'] < 90).sum()} bajo 90%")
        print(f"  ignorando signo: {(ok['pct_valor_abs'] == 100).sum()} al 100% "
              f"| {(ok['pct_valor_abs'] < 90).sum()} bajo 90%")
        print(f"  tolerando signo y redondeo: {(ok['pct_tolerante'] == 100).sum()} al 100% "
              f"| {(ok['pct_tolerante'] < 90).sum()} bajo 90%")
        print(f"  fondos con algun estado sin tabla legible (imagen): "
              f"{(df_res['paginas_sin_tabla'].fillna('') != '').sum()}")
        print(f"  fondos que usaron paginas re-extraidas: {(ok['paginas_alt_usadas'].fillna('') != '').sum()}")
    print(f"\n  salida: {DIR_PROC}")


def main():
    pdfs = sorted(DIR_ARCHIVOS.rglob("FMNO*.pdf"))
    etapa_extraccion(pdfs)
    etapa_reextraccion(pdfs)
    etapa_cruce()
    return 0


if __name__ == "__main__":   # obligatorio en Windows para usar procesos
    sys.exit(main())