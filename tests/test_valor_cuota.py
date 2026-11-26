"""Lector del Excel de valores cuota de la CMF."""
import importlib

import pandas as pd

from comun import cmf_valor_cuota

m = importlib.import_module("validaciones.testigos.03i_testigo_cmf")


def test_filas():
    d = pd.DataFrame([["Fondo Mutuo : X"] + [None] * 13,
                      ["", "RUN", "Tipo", "Adm", "Serie", "Moneda", "Patrimonio", None, None, None, "Participes", None, None, "Valor cuota"],
                      ["DICIEMBRE/2023", "9084-0", 3, None, "a ", "PESOS", 26391.491117, 0, 0, 1.2, 1940, 0, 0, 1387.1344],
                      ["(1) Cifras en millones", None] + [None] * 12])
    f = cmf_valor_cuota.filas(d)
    assert f.to_dict("records") == [dict(rut="9084", anio=2023, mes=12, serie="A", moneda="PESOS",
                                         patrimonio_mm=26391.491117, participes=1940, valor_cuota=1387.1344)]


def test_escala():
    assert m.escala(26391491.117, 26391491117.0) == -3          # EEFF en miles
    assert m.escala(26391491117.0, 26391491117.0) == 0
    assert m.escala(5.0, 26391491117.0) is None


def test_cartola(tmp_path):
    from comun import cmf_cartola
    cab = ("RUN_ADM;NOM_ADM;RUN_FM;FECHA_INF;ACTIVO_TOT;MONEDA;PARTICIPES_INST;INVERSION_EN_FONDOS;SERIE;"
           "CUOTAS_APORTADAS;CUOTAS_RESCATADAS;CUOTAS_EN_CIRCULACION;VALOR_CUOTA;PATRIMONIO_NETO;NUM_PARTICIPES;"
           "NUM_PARTICIPES_INST;FONDO_PEN;REM_FIJA;REM_VARIABLE;GASTOS_AFECTOS;GASTOS_NO_AFECTOS;"
           "COMISION_INVERSION;COMISION_RESCATE;FACTOR DE AJUSTE;FACTOR DE REPARTO")
    fila = "91999000;AGF X;8011;20251231;192872199613;$$;S;1;b;0;0;3875057.2745;1755.6367;6803192766;1207;0;N;242314.1;0;1;2;0;0;;"
    (tmp_path / "c.txt").write_text(cab + "\n" + fila + "\n", encoding="latin1")
    v = cmf_cartola.cargar(tmp_path)
    r = v.iloc[0]
    assert (r["rut"], r["anio"], r["serie"], r["patrimonio"], r["activo_tot"]) == ("8011", 2025, "B", 6803192766, 192872199613)
