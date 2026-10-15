"""
Parametros compartidos del pipeline
===================================

Una sola definicion para todos los scripts que la necesitan (03b, 04).
"""

# Materialidad: diferencias iguales o menores al umbral se registran como
# observacion y no se revisan a mano. Se aplica sobre la diferencia absoluta,
# en la unidad en que reporta el fondo:
#   "$$"  moneda nacional, montos en miles de pesos (M$) -> 100
#   otra  (PROM, EUR, ...), montos en miles de la moneda   -> 1
UMBRAL_MATERIALIDAD = {"$$": 100}
UMBRAL_OTRA_MONEDA = 1


def umbral_materialidad(moneda) -> int:
    """Umbral para la moneda del fondo. Moneda desconocida o vacia: el umbral
    mas bajo (conservador: se revisa de mas antes que de menos)."""
    return UMBRAL_MATERIALIDAD.get(str(moneda).strip(), UMBRAL_OTRA_MONEDA)


# Casos conocidos (verificados a mano) para validar cada etapa. Identifican
# fondos, por eso viven fuera del repo: verificacion/casos_conocidos.csv
# (columnas: etapa, rut, anio, esperado). Sin el archivo, la validacion se omite.
def casos_conocidos(etapa: str) -> list:
    from pathlib import Path
    import csv
    ruta = Path(__file__).resolve().parent / "verificacion" / "casos_conocidos.csv"
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8") as f:
        return [(r["rut"], int(r["anio"]), r["esperado"]) for r in csv.DictReader(f) if r["etapa"] == etapa]