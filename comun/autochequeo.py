"""Autochequeo de cobertura de una etapa: si evalua mucho menos que su universo, se detiene ANTES de
escribir sus salidas (no deja archivos a medias que las etapas siguientes tomen como buenos).

Lo motivo un error de programacion en el 03c que evaluo 1 fondo-anio de 4.400: la cadena siguio, el
03d y el 03g corrieron sobre eso y el 04 se cayo recien al final. La cobertura normal de cada etapa
esta sobre 95%; el minimo de 90% deja margen para cambios de lectura sin dejar pasar un colapso.
"""
import sys

MINIMO = 0.90


def exigir(etapa: str, evaluados: int, universo: int, que: str = "fondo-anio", minimo: float = MINIMO):
    if not universo:
        return
    f = evaluados / universo
    if f < minimo:
        sys.exit(f"{etapa}: AUTOCHEQUEO FALLIDO, {que} evaluados {evaluados:,} de {universo:,} ({f:.1%} < {minimo:.0%}). "
                 f"No se escribieron las salidas: revisar el cambio reciente o las etapas anteriores.")
    print(f"{etapa}: autochequeo ok, {que} evaluados {evaluados:,} de {universo:,} ({f:.1%})")
