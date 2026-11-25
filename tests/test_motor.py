"""Motor de reglas sobre hechos de juguete: el resultado se puede calcular a mano."""
import pandas as pd

from motor import reglas


def hechos(filas):
    return pd.DataFrame(filas, columns=["archivo", "contexto", "estado", "codigo", "serie", "valor"])


def test_suma_con_alternativos_y_parte_ausente():
    h = hechos([
        ("a", "PeriodoActual", "ESF", "TotalActivo", "", 100.0),
        ("a", "PeriodoActual", "ESF", "TotalPasivo", "", 30.0),
        ("a", "PeriodoActual", "ESF", "Neto", "", 71.0),
        ("a", "PeriodoActual", "EFE", "AumentoB", "", 5.0),       # solo el codigo alternativo
        ("a", "PeriodoActual", "EFE", "Op", "", 5.0),
        ("a", "PeriodoAnterior", "ESF", "TotalActivo", "", 10.0),  # neto ausente: no se evalua la regla
        ("a", "PeriodoActual", "ESF", "TotalActivo", "S1", 999.0), # serie: no entra a los totales
    ])
    idt = {"neto": ("ESF:Neto", [(1, "ESF:TotalActivo"), (-1, "ESF:TotalPasivo")]),
           "aumento": ("EFE:AumentoA|EFE:AumentoB", [(1, "EFE:Op"), (1, "EFE:Fin")])}  # Fin ausente = 0
    r = reglas.por_columna(h, identidades=idt).reset_index()
    neto = r[r["identidad"] == "neto"]
    assert len(neto) == 1 and neto.iloc[0]["contexto"] == "PeriodoActual"
    assert neto.iloc[0]["total"] - neto.iloc[0]["suma_partes"] == 1          # 71 vs 100 - 30
    aum = r[r["identidad"] == "aumento"].iloc[0]
    assert (aum["total"], aum["suma_partes"]) == (5.0, 5.0)


def test_entre_columnas():
    h = hechos([
        ("a", "PeriodoActual", "EFE", "Inicial", "", 50.0),
        ("a", "PeriodoAnterior", "EFE", "Final", "", 48.0),
        ("b", "PeriodoActual", "EFE", "Inicial", "", 7.0),        # sin cierre anterior: no se evalua
    ])
    r = reglas.entre_columnas(h, pares={"cont": ("EFE:Inicial", "EFE:Final")}).reset_index()
    assert list(r["archivo"]) == ["a"] and (r["total"] - r["suma_partes"]).iloc[0] == 2
