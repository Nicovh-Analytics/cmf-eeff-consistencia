"""
Hechos del XML: una fila por cifra (ultimo envio de cada fondo-anio), con su estado financiero.

    archivo, rut, anio, contexto (PeriodoActual | PeriodoAnterior), estado, codigo, serie ('' = total),
    valor, nota

El estado se asigna por el orden de los codigos dentro de cada archivo y contexto (comun/secciones.py):
hay codigos que existen en dos estados (diferencias de cambio sobre efectivo en ERI y EFE; distribucion
de beneficios en ERI y ECP). Si aun asi se repite (estado, codigo, serie) en un archivo-contexto, se
queda la primera cifra.

Se guarda en procesado/hechos_xml.parquet y se reconstruye solo si cuentas.csv o encabezados.csv son
mas nuevos: las etapas leen el parquet (segundos) en vez de cuentas.csv (140 MB) cada una.

Hechos del PDF (hechos_pdf.parquet), desde los renglones que deja el lector del 03b: cada renglon con
codigo asignado por el emparejador da hasta dos cifras (actual y anterior), con el signo como se imprimio,
la pagina, el metodo de lectura y como coincidio la glosa. archivo = "rut_anio" (un PDF por fondo-anio).

Uso:
    python motor/hechos.py          reconstruye y resume
    from motor import hechos; h = hechos.xml(); p = hechos.pdf()
"""
import sys

import pandas as pd

from comun.secciones import asignar_secciones
from config import CMF_HOME

P = CMF_HOME / "procesado"
RUTA_XML = P / "hechos_xml.parquet"
RUTA_PDF = P / "hechos_pdf.parquet"
COLS = ["archivo", "rut", "anio", "contexto", "estado", "codigo", "serie", "valor", "nota"]
COLS_PDF = COLS[:-1] + ["pagina", "coincide", "metodo", "glosa"]


def ultimo_envio() -> pd.DataFrame:
    enc = pd.read_csv(P / "encabezados.csv", dtype={"rut": str, "rut_agf": str})
    return enc[enc["es_ultimo_envio"]]


def construir_xml(enc: pd.DataFrame | None = None, avisar=True) -> pd.DataFrame:
    enc = ultimo_envio() if enc is None else enc
    cta = pd.read_csv(P / "cuentas.csv", usecols=["archivo", "contexto", "codigo", "serie", "nota", "valor"],
                      dtype={"serie": str, "nota": str})
    cta = cta[cta["contexto"].isin(["PeriodoActual", "PeriodoAnterior"]) & cta["archivo"].isin(enc["archivo"])]
    cta["estado"] = cta.groupby(["archivo", "contexto"], sort=False)["codigo"] \
                       .transform(lambda s: asignar_secciones(list(s)))
    cta["serie"] = cta["serie"].fillna("")
    cta["valor"] = cta["valor"].fillna(0)
    cta = cta.merge(enc[["archivo", "rut", "anio"]], on="archivo")
    n0 = len(cta)
    cta = cta.drop_duplicates(["archivo", "contexto", "estado", "codigo", "serie"])
    if avisar and n0 - len(cta):
        print(f"aviso: {n0 - len(cta)} cifras duplicadas (codigo, serie) descartadas")
    return cta[COLS].reset_index(drop=True)


def construir_pdf(avisar=True) -> pd.DataFrame:
    r = pd.read_csv(P / "renglones_pdf.csv", dtype={"rut": str, "codigo": str}, low_memory=False,
                    usecols=["rut", "anio", "estado", "pagina", "glosa", "actual", "anterior", "codigo",
                             "coincide", "metodo"])
    r = r[r["codigo"].notna() & (r["metodo"] != "encabezado")]
    h = r.melt(id_vars=["rut", "anio", "estado", "pagina", "glosa", "codigo", "coincide", "metodo"],
               value_vars=["actual", "anterior"], var_name="columna", value_name="valor")
    h = h[h["valor"].notna()]
    h["contexto"] = h["columna"].map({"actual": "PeriodoActual", "anterior": "PeriodoAnterior"})
    h["archivo"] = h["rut"] + "_" + h["anio"].astype(str)
    h["serie"] = ""
    n0 = len(h)
    h = h.drop_duplicates(["archivo", "contexto", "estado", "codigo"])     # el primer renglon con ese codigo
    if avisar and n0 - len(h):
        print(f"aviso PDF: {n0 - len(h)} cifras con el codigo repetido en el mismo estado y columna descartadas")
    return h[COLS_PDF].reset_index(drop=True)


def _vigente(ruta, fuentes) -> bool:
    if not ruta.exists():
        return False
    t = ruta.stat().st_mtime
    return all((P / f).stat().st_mtime <= t for f in fuentes)


def xml(reconstruir: bool = False) -> pd.DataFrame:
    """Hechos del XML; reconstruye el parquet si falta o si sus fuentes cambiaron."""
    if reconstruir or not _vigente(RUTA_XML, ("cuentas.csv", "encabezados.csv")):
        h = construir_xml()
        h.to_parquet(RUTA_XML, index=False)
        return h
    return pd.read_parquet(RUTA_XML)


def pdf(reconstruir: bool = False) -> pd.DataFrame:
    """Hechos del PDF (renglones del lector); reconstruye si renglones_pdf.csv cambio."""
    if reconstruir or not _vigente(RUTA_PDF, ("renglones_pdf.csv",)):
        h = construir_pdf()
        h.to_parquet(RUTA_PDF, index=False)
        return h
    return pd.read_parquet(RUTA_PDF)


def main():
    h = xml(reconstruir=True)
    print(f"hechos XML: {len(h):,} cifras en {h['archivo'].nunique():,} archivos "
          f"({h[['rut', 'anio']].drop_duplicates().shape[0]:,} fondo-anio) -> {RUTA_XML}")
    print(h.groupby(["estado", "contexto"]).size().unstack().to_string())
    if (P / "renglones_pdf.csv").exists():
        p = pdf(reconstruir=True)
        print(f"\nhechos PDF: {len(p):,} cifras en {p['archivo'].nunique():,} PDF -> {RUTA_PDF}")
        print(p.groupby(["estado", "contexto"]).size().unstack().to_string())
        print("coincidencia de la glosa:", p["coincide"].value_counts(dropna=False).to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
