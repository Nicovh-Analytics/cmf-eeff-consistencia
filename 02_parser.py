"""
Parser de EEFF de Fondos Mutuos (XML CMF) -> tablas analizables
================================================================

Lee todos los XML FMEF*.xml que dejo el recolector en data/archivos/
y genera dos tablas en data/procesado/:

  encabezados.csv  -> 1 fila por archivo (fondo-anio-envio)
                      rut, AGF, moneda, auditor, fecha de envio, etc.
  cuentas.csv      -> formato largo: 1 fila por cifra
                      rut | anio | contexto | codigo | serie | nota | valor

No toca la red. Se puede correr las veces que quieras.

Formato del XML (verificado con un fondo, EEFF 2024):
  <IFRS>
    <Identificacion> rut fondo, rut y nombre AGF
    <DatosPeriodo>   moneda, periodo, auditor y su N de registro
    <Contextos>      fechas de PeriodoActual / PeriodoAnterior
    <Cuenta Context="PeriodoActual" CodigoCuenta="..." [Nota] [Serie]>valor</Cuenta>
  Montos en miles. Serie="" = total del fondo; codigos *PorSerie = desglose.

Por que formato largo y no una columna por cuenta:
  - todas las AGF usan los mismos CodigoCuenta, pero no todas reportan
    todas las cuentas ni las mismas series; el formato largo no necesita
    saber de antemano que columnas existen.
  - filtrar / pivotear despues es trivial en pandas o en Excel.
"""

import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from config import CMF_HOME

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DIR_ARCHIVOS = CMF_HOME / "archivos"
DIR_SALIDA = CMF_HOME / "procesado"

# Normalizacion de auditores: el NOMBRE es mas confiable que el numero de
# registro (verificado en la corrida completa: la misma firma aparece con
# varios numeros y un mismo numero con varias firmas). Orden importa.
FIRMAS = [
    (("KPMG", "KPGM"), "KPMG"),
    (("DELOITTE",), "Deloitte"),
    (("PRICE", "PWC"), "PwC"),
    (("ERNST", "ERNEST", "EYAUDIT"), "EY"),
    (("GRANT THORNTON",), "Grant Thornton"),
    (("SURLATINA",), "Surlatina"),
    (("HORWATH", "CROWE"), "Crowe"),     # Horwath HB paso a llamarse Crowe
    (("KRESTON",), "Kreston"),
]

RE_ENCODING = re.compile(rb'encoding\s*=\s*["\'][^"\']*["\']')

# FMEF{correlativo}_{YYYYMMDD}_{HHMMSS}_{rut}.xml
PATRON_NOMBRE = re.compile(r"FMEF(\d+)_(\d{8})_(\d{6})_(\d+)\.xml$", re.IGNORECASE)


def texto(nodo, ruta):
    """Texto de un subnodo, o '' si no existe. Evita cadenas de ifs."""
    hijo = nodo.find(ruta)
    return (hijo.text or "").strip() if hijo is not None else ""


def leer_xml(ruta: Path):
    """Parsea el XML. Si falla por encoding, lo repara y lo marca.

    Caso visto en la corrida completa: archivos declarados UTF-8 pero con
    tildes y enies en Latin-1 (ej. 'Compa\\xf1ia'), y un archivo con
    encoding="iso-<rut>-K" (el RUT del fondo pegado en la declaracion).
    Reparacion: decodificar como cp1252 (superconjunto practico de
    Latin-1), declarar UTF-8 y volver a parsear. No se descarta ningun dato:
    si tampoco asi parsea, el error se propaga y queda registrado.

    Devuelve (raiz, reparado: str)."""
    crudo = ruta.read_bytes()
    try:
        return ET.fromstring(crudo), ""
    except (ET.ParseError, LookupError):
        texto = crudo.decode("cp1252", errors="strict")
        arreglado = RE_ENCODING.sub(b'encoding="UTF-8"', texto.encode("utf-8"), count=1)
        return ET.fromstring(arreglado), "encoding_latin1"


def normalizar_auditor(nombre):
    """Nombre libre del XML -> firma canonica."""
    limpio = unicodedata.normalize("NFKD", nombre or "")
    limpio = "".join(c for c in limpio if not unicodedata.combining(c)).upper().strip()
    if len(limpio) <= 1:                      # vacio, "x"
        return "SIN_DATO"
    for claves, firma in FIRMAS:
        if any(k in limpio for k in claves):
            return firma
    if limpio == "EY" or limpio.startswith("EY "):
        return "EY"
    return "OTRA: " + limpio[:40]


def a_numero(valor):
    """Los montos vienen como enteros, pero por si alguna AGF manda
    decimales o basura, no reventamos: devolvemos None y se audita."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        try:
            return float(valor.replace(",", "."))
        except (AttributeError, ValueError):
            return None


def parsear_archivo(ruta: Path):
    """Devuelve (encabezado: dict, filas_cuentas: list[tuple])."""
    raiz, reparado = leer_xml(ruta)

    m = PATRON_NOMBRE.search(ruta.name)
    fecha_envio = (datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S")
                   if m else None)

    ident = raiz.find("Identificacion")
    datos = raiz.find("DatosPeriodo")

    rut = texto(ident, "RUTFondoInforma")
    anio = int(texto(datos, "PeriodoPresentacionEstadosFinancieros/Anio") or 0)

    encabezado = {
        "archivo": ruta.name,
        "rut": rut,
        "dv": texto(ident, "DVFondoInforma"),
        "nombre_fondo": texto(ident, "NombreEntidadInforma"),
        "rut_agf": texto(ident, "RUTAdministradora"),
        "nombre_agf": texto(ident, "NombreAdministradoraInforma"),
        "anio": anio,
        "mes": int(texto(datos, "PeriodoPresentacionEstadosFinancieros/Mes") or 0),
        "moneda": texto(datos, "MonedaPresentacionEstadosFinancieros"),
        # "03" y "3" son lo mismo: se normaliza quitando ceros a la izquierda.
        "auditor_num": texto(datos, "NumRegistroEmpresaAuditoriaExterna").lstrip("0"),
        "auditor": texto(datos, "NombreAuditoresExternos"),
        "auditor_firma": normalizar_auditor(texto(datos, "NombreAuditoresExternos")),
        "ultima_nota": texto(datos, "NumUltimaNotaInformada"),
        "correlativo": m.group(1) if m else "",
        "fecha_envio": fecha_envio,
        "reparado": reparado,
    }

    filas = []
    for c in raiz.iter("Cuenta"):
        crudo = (c.text or "").strip()
        filas.append((
            ruta.name,
            rut,
            anio,
            c.get("Context", ""),
            c.get("CodigoCuenta", ""),
            c.get("Serie", ""),       # "" = total del fondo
            c.get("Nota", ""),
            a_numero(crudo),
            crudo,                    # se guarda el original para auditar
        ))

    encabezado["n_cuentas"] = len(filas)
    return encabezado, filas


def main():
    archivos = sorted(DIR_ARCHIVOS.rglob("FMEF*.xml"))
    if not archivos:
        print(f"No hay XML en {DIR_ARCHIVOS}")
        return 1

    print(f"Parseando {len(archivos)} XML...")

    # Acumular en listas y crear el DataFrame UNA vez al final.
    # (Hacer pd.concat dentro del loop es cuadratico y con miles de
    # archivos se nota.)
    encabezados, cuentas, errores = [], [], []

    for ruta in archivos:
        try:
            enc, filas = parsear_archivo(ruta)
            encabezados.append(enc)
            cuentas.extend(filas)
        except ET.ParseError as e:
            errores.append((ruta.name, f"XML mal formado: {e}"))
        except Exception as e:  # noqa: BLE001 - registramos y seguimos
            errores.append((ruta.name, f"{type(e).__name__}: {e}"))

    df_enc = pd.DataFrame(encabezados)
    df_cta = pd.DataFrame(cuentas, columns=[
        "archivo", "rut", "anio", "contexto", "codigo",
        "serie", "nota", "valor", "valor_crudo",
    ])

    # --- Reenvios: mas de un XML para el mismo fondo-anio ---
    # Se conservan todos (son evidencia), pero se marca el vigente.
    df_enc = df_enc.sort_values(["rut", "anio", "fecha_envio"])
    df_enc["n_envios"] = df_enc.groupby(["rut", "anio"])["archivo"].transform("size")
    df_enc["es_ultimo_envio"] = ~df_enc.duplicated(["rut", "anio"], keep="last")

    # --- Auditor: el numero contradice al nombre? ---
    # Para cada numero de registro, la firma mas frecuente es "la suya";
    # las filas cuyo nombre apunta a otra firma quedan marcadas.
    firma_del_num = (df_enc[df_enc["auditor_firma"] != "SIN_DATO"]
                     .groupby("auditor_num")["auditor_firma"]
                     .agg(lambda x: x.mode().iat[0]))
    df_enc["auditor_num_inconsistente"] = (
        df_enc["auditor_num"].map(firma_del_num).fillna(df_enc["auditor_firma"])
        != df_enc["auditor_firma"])

    # --- Guardar ---
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: Excel en Windows reconoce los tildes sin pelear.
    df_enc.to_csv(DIR_SALIDA / "encabezados.csv", index=False, encoding="utf-8-sig")
    df_cta.to_csv(DIR_SALIDA / "cuentas.csv", index=False, encoding="utf-8-sig")

    # --- Resumen para revisar a ojo ---
    print(f"\n  archivos ok:      {len(df_enc)}")
    print(f"  archivos con error: {len(errores)}")
    for nombre, msg in errores:
        print(f"    ! {nombre}: {msg}")
    print(f"  filas de cuentas: {len(df_cta):,}")
    print(f"  codigos distintos: {df_cta['codigo'].nunique()}")
    print(f"  valores no numericos: {df_cta['valor'].isna().sum()}")
    print(f"  xml reparados por encoding: {(df_enc['reparado'] != '').sum()}")

    print("\n  monedas:")
    print(df_enc["moneda"].value_counts().to_string().replace("\n", "\n    ").join(["    ", ""]))

    print("\n  auditores (firma normalizada -> envios):")
    print(df_enc["auditor_firma"].value_counts().to_string().replace("\n", "\n    ").join(["    ", ""]))
    print(f"\n  envios con numero de auditor que contradice el nombre: "
          f"{df_enc['auditor_num_inconsistente'].sum()}")

    print(f"\n  salida: {DIR_SALIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())