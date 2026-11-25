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


def test_signo_oficial_en_partes():
    """Gastos impresos sin parentesis: con el signo oficial ("(-)" en el modelo) la utilidad cuadra."""
    h = hechos([
        ("p", "PeriodoActual", "ERI", "TotalIngresosPerdidasNetosDeLaOperacion", "", 100.0),
        ("p", "PeriodoActual", "ERI", "TotalGastosDeOperacion", "", 30.0),           # impreso positivo
        ("p", "PeriodoActual", "ERI", "UtilidadPerdidaDeLaOperacionAntesDeImpuesto", "", 70.0),
    ])
    idt = {"u": ("ERI:UtilidadPerdidaDeLaOperacionAntesDeImpuesto",
                 [(1, "ERI:TotalIngresosPerdidasNetosDeLaOperacion"), (1, "ERI:TotalGastosDeOperacion")])}
    impreso = reglas.por_columna(h, identidades=idt).iloc[0]
    oficial = reglas.por_columna(h, identidades=idt, signo_oficial=True).iloc[0]
    assert impreso["suma_partes"] == 130 and oficial["suma_partes"] == 70


def test_evaluar_igual_a_las_formulas_del_03c():
    """motor.reglas.evaluar reproduce las formulas que el 03c tenia escritas a mano (dif y laxa)."""
    import itertools
    import random
    import catalogo
    formulas = {
        "esf_activo_neto": (["total_activo", "total_pasivo", "activo_neto"],
                            lambda a, p, n: abs(a) - abs(p) - n,
                            lambda a, p, n: min(abs(abs(a) - abs(p) - n), abs(abs(a) - abs(p) + n))),
        "eri_utilidad": (["total_ingresos", "total_gastos", "utilidad_operacion"],
                         lambda i, g, u: i - abs(g) - u,
                         lambda i, g, u: min(abs(i - abs(g) - u), abs(i - abs(g) + u), abs(-i - abs(g) - u))),
        "cruce_efectivo_efe": (["efectivo", "saldo_final"],
                               lambda e, s: abs(e) - abs(s), lambda e, s: abs(abs(e) - abs(s))),
    }
    random.seed(0)
    for rid, (terms, fd, fl) in formulas.items():
        cods = [f"{catalogo.estado(k)}:{catalogo.codigo(k)}" for k in terms]
        casos = list(itertools.product([0, 3, -3, 1e9, -1e9], repeat=len(terms)))
        casos += [tuple(random.uniform(-1e6, 1e6) for _ in terms) for _ in range(500)]
        for c in casos:
            d, l = reglas.evaluar(rid, dict(zip(cods, c)))
            assert abs(d - fd(*c)) < 1e-6 and abs(l - fl(*c)) < 1e-6, (rid, c)
