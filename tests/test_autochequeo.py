"""El autochequeo detiene la etapa cuando evalua muy por debajo de su universo."""
import pytest

from comun.autochequeo import exigir


def test_pasa_con_cobertura_normal(capsys):
    exigir("03x", 4421, 4473)
    assert "autochequeo ok" in capsys.readouterr().out


def test_se_detiene_si_colapsa():
    with pytest.raises(SystemExit) as e:
        exigir("03c", 1, 4400)          # el error del 07: un fondo-anio de 4.400
    assert "AUTOCHEQUEO FALLIDO" in str(e.value)


def test_universo_vacio_no_detiene():
    exigir("03x", 0, 0)
