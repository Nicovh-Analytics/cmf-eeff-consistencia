"""Integridad del catalogo y equivalencia con las etapas que todavia tienen reglas en el codigo.

El 07 (identidades y continuidad) y el 03b (subtotales) ya leen del catalogo: al migrarlos se
verifico que los diccionarios resultantes son identicos a los del codigo anterior (mismo contenido y
orden). Las pruebas de esas etapas protegen ahora el formato de compatibilidad; las de 03e, 04b y 04c
comparan contra los mapas que aun estan en el codigo.

    python -m pytest tests -q
"""
import importlib
import os

import pandas as pd
import pytest

import catalogo
from comun.secciones import ANCLAS, SECCION_DE


def test_reglas_reproducen_identidades_07():
    m07 = importlib.import_module("validaciones.continuidad.07_continuidad")
    assert m07.IDENTIDADES == catalogo.identidades_07()
    assert m07.ENTRE_COLUMNAS == catalogo.entre_columnas_07()
    r = catalogo.reglas()
    act = r[r["activa"] == "si"]
    assert len(m07.IDENTIDADES) + len(m07.ENTRE_COLUMNAS) == len(act) == 26


def test_ids_y_nombres_unicos():
    r = catalogo.reglas()
    assert r["id"].is_unique and r["nombre"].is_unique
    assert set(r["tipo"]) <= {"suma", "cruce", "continuidad"}


def test_terminos_existen_en_conceptos():
    c = catalogo.conceptos()
    hay = set(c["estado"] + ":" + c["codigo"])
    for _, r in catalogo.reglas().iterrows():
        for t in [r["total"]] + [x for _, x in catalogo.terminos(r["partes"])]:
            for alt in t.split("|"):
                assert alt in hay, f"{r['id']}: {alt} no esta en conceptos.csv"


def test_estados_igual_a_secciones():
    """conceptos.csv tiene el mismo estado y orden que comun/secciones.py (asignacion de estados)."""
    c = catalogo.conceptos()
    anclas = c[c["ancla"] == "si"]
    assert dict(zip(anclas["codigo"], anclas["estado"])) == SECCION_DE
    for est, txt in ANCLAS.items():
        a = anclas[anclas["estado"] == est].sort_values("orden", key=lambda s: s.astype(int))
        assert list(a["codigo"]) == txt.split()


def test_claves_cortas_unicas():
    c = catalogo.conceptos()
    cl = c[c["clave"] != ""]
    assert cl["clave"].is_unique


@pytest.mark.parametrize("clave", ["operacion", "financiamiento", "total_activo", "total_pasivo",
                                   "total_ingresos", "total_gastos"])
def test_subtotales_03b(clave):
    pytest.importorskip("pdfplumber")
    m03b = importlib.import_module("validaciones.estructura.03b_estructura")
    cfg = m03b.SUBTOTALES[clave]
    s = catalogo.subtotal_03b(clave)
    assert (s["estado"], s["codigo"], s["partes"]) == (cfg["estado"], cfg["codigo"], cfg["partes"])


def test_estado_de_claves_igual_a_etapas():
    """Los ESTADO = {...} copiados en 03e, 04b y 04c son un subconjunto del catalogo."""
    est = catalogo.estado_de_claves()
    for mod in ("validaciones.estructura.03e_comparativos", "consolidacion.04b_casos",
                "consolidacion.04c_casos_unicos"):
        try:
            m = importlib.import_module(mod)
        except ImportError as e:            # dependencias del PDF no instaladas
            pytest.skip(str(e))
        for k, v in m.ESTADO.items():
            if k == "evolucion_efectivo":   # nombre de la regla del saldo final, no un concepto
                assert v == "EFE"
                continue
            assert est.get(k) == v, f"{mod}: {k} -> {v}, catalogo dice {est.get(k)}"


OFICIAL = catalogo.DIR / "fm" / "oficial"


def test_codigos_igual_al_modelo_oficial():
    """Los codigos del catalogo son exactamente los del generador oficial (88 distintos)."""
    of = set(pd.read_csv(OFICIAL / "codigos.csv")["codigo"])
    cat = set(catalogo.conceptos()["codigo"])
    assert cat == of, f"fuera del modelo: {sorted(cat - of)}; faltan: {sorted(of - cat)}"


def test_identidades_oficiales_en_catalogo():
    """Cada formula de la planilla oficial (por columna) es una regla del catalogo: mismo total y
    mismas partes con el mismo signo (en cualquier orden; los codigos alternativos valen)."""
    def cods(t):
        return {x.split(":", 1)[1] for x in t.split("|")}
    reglas = [(cods(r["total"]), [(s, cods(p)) for s, p in catalogo.terminos(r["partes"])], r["id"])
              for _, r in catalogo.reglas().iterrows()]
    of = pd.read_csv(OFICIAL / "identidades.csv", dtype=str, keep_default_na=False)
    for o in of[of["alcance"] == "columna"].itertuples():
        partes = sorted((1 if p[0] == "+" else -1, p[1:]) for p in o.partes.split(";"))
        hit = [rid for tot, ps, rid in reglas
               if o.total in tot and len(ps) == len(partes)
               and all(any(s == s2 and c in c2 for s2, c2 in ps) for s, c in partes)]
        assert hit, f"identidad oficial sin regla: {o.total} = {o.partes}"
