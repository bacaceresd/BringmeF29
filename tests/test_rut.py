import pytest

from bringmef29.rut import Rut, RutInvalido, digito_verificador, es_valido


@pytest.mark.parametrize(
    "cuerpo,dv",
    [(76086428, "5"), (77222333, "1"), (12345678, "5"), (6, "K"), (11111111, "1")],
)
def test_digito_verificador(cuerpo, dv):
    assert digito_verificador(cuerpo) == dv


@pytest.mark.parametrize(
    "entrada", ["76.086.428-5", "760864285", "76086428-5", " 76.086.428 - 5 "]
)
def test_parsea_cualquier_formato(entrada):
    rut = Rut.parsear(entrada)
    assert rut.cuerpo == 76086428
    assert rut.dv == "5"


def test_formatos_de_salida():
    rut = Rut.parsear("76086428-5")
    assert rut.sin_formato == "760864285"
    assert rut.con_guion == "76086428-5"
    assert rut.formateado == "76.086.428-5"


def test_dv_k_en_minuscula_se_normaliza():
    assert Rut.parsear("6-k").dv == "K"


@pytest.mark.parametrize("entrada", ["76086428-9", "1", "abc-1", "", "76.086.428-K"])
def test_rechaza_ruts_invalidos(entrada):
    assert not es_valido(entrada)
    with pytest.raises(RutInvalido):
        Rut.parsear(entrada)


def test_ruts_iguales_son_equivalentes():
    assert Rut.parsear("76.086.428-5") == Rut.parsear("760864285")
