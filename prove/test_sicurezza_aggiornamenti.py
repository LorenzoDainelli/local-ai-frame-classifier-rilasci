from __future__ import annotations

import base64
import hashlib
import io

import pytest

from officina.programma import aggiornamenti, carta, firma


def _chiave():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate()


def _pubblica(privata) -> str:
    from cryptography.hazmat.primitives import serialization

    return base64.b64encode(privata.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


NOSTRA = _chiave()
ESTRANEA = _chiave()


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    monkeypatch.setattr(firma, "CHIAVI_PUBBLICHE", (_pubblica(NOSTRA),))
    return tmp_path / "casa"


def _firma(privata, versione, nome, sha256) -> str:
    return base64.b64encode(privata.sign(firma.messaggio(versione, nome, sha256))).decode()


def _rilascio(tag, sha256="a" * 64, firma_testo=None):
    nome = f"local-ai-frame-classifier-{tag.lstrip('v')}.exe"
    risorse = [{"name": nome, "size": 10, "digest": f"sha256:{sha256}",
                "browser_download_url": f"https://github.com/x/{tag}/{nome}"}]
    if firma_testo is not None:
        risorse.append({"name": f"{nome}.firma",
                        "browser_download_url": f"https://github.com/x/{tag}/{nome}.firma"})
    return {"tag_name": tag, "draft": False, "body": "", "published_at": "", "assets": risorse}, \
        firma_testo


def _scegli(coppie, attuale="2.0.0-beta.1"):
    dati = [c[0] for c in coppie]
    testi = {}
    for rilascio, testo in coppie:
        for risorsa in rilascio["assets"]:
            if risorsa["name"].endswith(".firma"):
                testi[risorsa["browser_download_url"]] = testo
    rilasci = aggiornamenti.rilasci_da(dati, lambda _: None)
    return aggiornamenti.il_piu_nuovo(rilasci, aggiornamenti.BETA, attuale, testi.get)


def test_il_messaggio_firmato_e_quello_che_scrive_github():
    atteso = ("local-ai-frame-classifier aggiornamento 1\n"
              "versione 2.0.0-beta.5\n"
              "file local-ai-frame-classifier-2.0.0-beta.5.exe\n"
              f"sha256 {'a' * 64}\n").encode()
    assert firma.messaggio("2.0.0-beta.5", "local-ai-frame-classifier-2.0.0-beta.5.exe",
                           "A" * 64) == atteso


def test_un_rilascio_firmato_si_prende():
    nome = "local-ai-frame-classifier-2.0.0-beta.5.exe"
    scelto = _scegli([_rilascio("v2.0.0-beta.5", firma_testo=_firma(NOSTRA, "2.0.0-beta.5", nome,
                                                                   "a" * 64))])
    assert scelto is not None and scelto.versione == "2.0.0-beta.5" and scelto.firmato


def test_senza_firma_non_si_prende_e_resta_il_firmato_piu_vecchio():
    nome = "local-ai-frame-classifier-2.0.0-beta.5.exe"
    scelto = _scegli([
        _rilascio("v2.0.0-beta.5", firma_testo=_firma(NOSTRA, "2.0.0-beta.5", nome, "a" * 64)),
        _rilascio("v2.0.0-beta.9"),
    ])
    assert scelto.versione == "2.0.0-beta.5"


def test_una_firma_di_un_altra_chiave_non_basta():
    nome = "local-ai-frame-classifier-2.0.0-beta.5.exe"
    assert _scegli([_rilascio("v2.0.0-beta.5",
                              firma_testo=_firma(ESTRANEA, "2.0.0-beta.5", nome, "a" * 64))]) is None


def test_un_vecchio_installatore_firmato_non_passa_per_uno_nuovo():
    vecchio = _firma(NOSTRA, "2.0.0-beta.2", "local-ai-frame-classifier-2.0.0-beta.2.exe", "a" * 64)
    assert _scegli([_rilascio("v2.0.0-beta.9", firma_testo=vecchio)]) is None


def test_la_firma_vale_solo_per_quell_impronta():
    nome = "local-ai-frame-classifier-2.0.0-beta.5.exe"
    giusta = _firma(NOSTRA, "2.0.0-beta.5", nome, "a" * 64)
    assert _scegli([_rilascio("v2.0.0-beta.5", sha256="b" * 64, firma_testo=giusta)]) is None


def test_una_firma_rovinata_non_ferma_niente():
    for testo in ("", "non è base64!", base64.b64encode(b"corta").decode(), "A" * 5000):
        assert _scegli([_rilascio("v2.0.0-beta.5", firma_testo=testo)]) is None


def test_senza_chiavi_pubbliche_non_si_aggiorna(monkeypatch):
    monkeypatch.setattr(firma, "CHIAVI_PUBBLICHE", ())
    nome = "local-ai-frame-classifier-2.0.0-beta.5.exe"
    assert _scegli([_rilascio("v2.0.0-beta.5",
                              firma_testo=_firma(NOSTRA, "2.0.0-beta.5", nome, "a" * 64))]) is None


class _Risposta(io.BytesIO):

    def __init__(self, dati):
        super().__init__(dati)
        self.headers = {"Content-Length": str(len(dati))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _pronto(contenuto, firma_testo):
    nome = "local-ai-frame-classifier-2.0.0-beta.9.exe"
    return aggiornamenti.Rilascio(
        versione="2.0.0-beta.9", indirizzo="https://github.com/x/i.exe", nome_file=nome,
        peso=len(contenuto), sha256=hashlib.sha256(contenuto).hexdigest(), note="",
        pubblicato="", firma=firma_testo)


def test_lo_scaricamento_rifiuta_un_aggiornamento_senza_firma(casa):
    contenuto = b"installatore"
    with pytest.raises(aggiornamenti.ImprontaSbagliata):
        aggiornamenti.scarica(_pronto(contenuto, None), apri=lambda *a, **k: _Risposta(contenuto))
    assert not carta.cartella_scaricati().exists() or not list(carta.cartella_scaricati().glob("*"))


def test_prima_di_installare_la_firma_si_ricontrolla(casa, monkeypatch):
    contenuto = b"installatore"
    impronta = hashlib.sha256(contenuto).hexdigest()
    nome = "local-ai-frame-classifier-2.0.0-beta.9.exe"
    rilascio = _pronto(contenuto, _firma(NOSTRA, "2.0.0-beta.9", nome, impronta))
    file = aggiornamenti.scarica(rilascio, apri=lambda *a, **k: _Risposta(contenuto))
    assert aggiornamenti.pronto_da_installare(attuale="2.0.0-beta.1")[1] == file
    monkeypatch.setattr(firma, "CHIAVI_PUBBLICHE", (_pubblica(ESTRANEA),))
    assert aggiornamenti.pronto_da_installare(attuale="2.0.0-beta.1") is None
    assert not file.exists()
