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

Uso:
    python motor/hechos.py          reconstruye y resume
    from motor import hechos; h = hechos.xml()
"""
import sys

import pandas as pd

from comun.secciones import asignar_secciones
from config import CMF_HOME

P = CMF_HOME / "procesado"
RUTA_XML = P / "hechos_xml.parquet"
COLS = ["archivo", "rut", "anio", "contexto", "estado", "codigo", "serie", "valor", "nota"]


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


def _vigente() -> bool:
    if not RUTA_XML.exists():
        return False
    t = RUTA_XML.stat().st_mtime
    return all((P / f).stat().st_mtime <= t for f in ("cuentas.csv", "encabezados.csv"))


def xml(reconstruir: bool = False) -> pd.DataFrame:
    """Hechos del XML; reconstruye el parquet si falta o si sus fuentes cambiaron."""
    if reconstruir or not _vigente():
        h = construir_xml()
        h.to_parquet(RUTA_XML, index=False)
        return h
    return pd.read_parquet(RUTA_XML)


def main():
    h = xml(reconstruir=True)
    print(f"hechos XML: {len(h):,} cifras en {h['archivo'].nunique():,} archivos "
          f"({h[['rut', 'anio']].drop_duplicates().shape[0]:,} fondo-anio) -> {RUTA_XML}")
    print(h.groupby(["estado", "contexto"]).size().unstack().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
