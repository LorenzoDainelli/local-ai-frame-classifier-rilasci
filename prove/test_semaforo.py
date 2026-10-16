from officina.web import stato_a_parole


def test_verde_senza_problemi():
    assert stato_a_parole.semaforo([])["colore"] == "verde"


def test_giallo_con_problemi_piccoli():
    luce = stato_a_parole.semaforo([{"titolo": "Un file non si trova più sul disco"}])
    assert luce["colore"] == "giallo"
    assert luce["testo"] == "Un file non si trova più sul disco."


def test_rosso_vince_su_tutto():
    luce = stato_a_parole.semaforo([{"titolo": "piccolo"},
                                    {"titolo": "Lo scaricamento si è fermato", "grave": True}])
    assert luce["colore"] == "rosso"
    assert luce["testo"] == "Lo scaricamento si è fermato, e un'altra cosa."
