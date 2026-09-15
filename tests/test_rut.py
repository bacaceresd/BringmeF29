import pytest

from bringmef29.rut import Rut, RutInvalido, digito_verificador, es_valido


@pytest.mark.parametrize(
    "cuerpo,dv",
    [(11111111, "1"), (22222222, "2"), (12345678, "5"), (6, "K"), (33333333, "3")],
)
def test_digito_verificador(cuerpo, dv):
    assert digito_verificador(cuerpo) == dv


@pytest.mark.parametrize(
    "entrada", ["11.111.111-1", "111111111", "11111111-1", " 11.111.111 - 1 "]
)
def test_parsea_cualquier_formato(entrada):
    rut = Rut.parsear(entrada)
    assert rut.cuerpo == 11111111
    assert rut.dv == "1"


def test_formatos_de_salida():
    rut = Rut.parsear("11111111-1")
    assert rut.sin_formato == "111111111"
    assert rut.con_guion == "11111111-1"
    assert rut.formateado == "11.111.111-1"


def test_dv_k_en_minuscula_se_normaliza():
    assert Rut.parsear("6-k").dv == "K"


@pytest.mark.parametrize("entrada", ["11111111-9", "1", "abc-1", "", "11.111.111-K"])
def test_rechaza_ruts_invalidos(entrada):
    assert not es_valido(entrada)
    with pytest.raises(RutInvalido):
        Rut.parsear(entrada)


def test_ruts_iguales_son_equivalentes():
    assert Rut.parsear("11.111.111-1") == Rut.parsear("111111111")
