from officina.web.strade.impostazioni import _numero


def test_un_numero_sbagliato_non_rompe_le_impostazioni():
    assert _numero("abc", 150, 60, 600) == 150
    assert _numero(None, 640, 128, 2048) == 640
    assert _numero("999999", 640, 128, 2048) == 2048
    assert _numero("-5", 150, 60, 600) == 60
    assert _numero("220", 150, 60, 600) == 220
