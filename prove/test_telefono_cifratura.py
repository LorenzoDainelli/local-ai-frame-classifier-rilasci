from __future__ import annotations

import json
import os
import re

import pytest

from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.telefono import cifratura, formato

PASSWORD = "tre parole che ricordi"

SVELTI = dict(costo=2 ** 8, blocco=8, parallelo=1)
POSTO = "foto/ab/" + "ab" * 16


@pytest.fixture(autouse=True)
def svelti(monkeypatch):
    monkeypatch.setattr(cifratura, "COSTI_AMMESSI",
                        cifratura.COSTI_AMMESSI + (SVELTI["costo"],))


@pytest.fixture
def chiave() -> cifratura.Chiave:
    return cifratura.Chiave.dalla_password(
        PASSWORD, b"un sale qualsiasi", **SVELTI)


def _scrivi(cartella, nome: str, dati: bytes):
    percorso = cartella / nome
    percorso.write_bytes(dati)
    return percorso


@pytest.mark.parametrize("quanti", [
    0,
    1,
    1000,
    cifratura.BLOCCO - 1,
    cifratura.BLOCCO,
    cifratura.BLOCCO + 1,
    3 * cifratura.BLOCCO + 77,
])
def test_torna_fuori_identico(tmp_path, chiave, quanti):
    dati = os.urandom(quanti)
    dentro = _scrivi(tmp_path, "originale.heic", dati)
    chiuso = tmp_path / "pacchetto" / "foto.heic"

    scritto = chiave.cifra_file(dentro, chiuso, POSTO)
    assert scritto.dimensione == quanti
    assert scritto.peso == chiuso.stat().st_size

    assert chiave.leggi_tutto(chiuso, POSTO) == dati

    riaperto = tmp_path / "riaperto.heic"
    impronta = chiave.decifra_file(chiuso, riaperto, POSTO)
    assert riaperto.read_bytes() == dati
    assert impronta == scritto.impronta


def test_il_peso_si_sa_prima_di_scrivere(tmp_path, chiave):
    for quanti in (0, 1, 999, cifratura.BLOCCO, 2 * cifratura.BLOCCO + 3):
        dentro = _scrivi(tmp_path, f"f{quanti}.bin", os.urandom(quanti))
        chiuso = tmp_path / f"c{quanti}.bin"
        chiave.cifra_file(dentro, chiuso, POSTO)
        assert cifratura.peso_cifrato(quanti) == chiuso.stat().st_size


def test_i_byte_in_memoria_fanno_lo_stesso_formato(tmp_path, chiave):
    dati = b"un database finto" * 100_000
    percorso = tmp_path / "dati.db"
    percorso.write_bytes(chiave.cifra_byte(dati, POSTO))
    assert chiave.leggi_tutto(percorso, POSTO) == dati
    assert chiave.dimensione_in_chiaro(percorso) == len(dati)


def test_il_chiaro_non_si_vede_nel_cifrato(tmp_path, chiave):
    dati = b"MARIA AL MARE 2019" * 1000
    chiuso = tmp_path / "chiuso.bin"
    chiave.cifra_file(_scrivi(tmp_path, "chiaro.bin", dati), chiuso, POSTO)
    assert b"MARIA" not in chiuso.read_bytes()


def test_due_file_uguali_non_si_cifrano_uguale(tmp_path, chiave):
    dati = b"la stessa identica foto"
    uno = tmp_path / "uno.bin"
    due = tmp_path / "due.bin"
    chiave.cifra_file(_scrivi(tmp_path, "a.bin", dati), uno, POSTO)
    chiave.cifra_file(_scrivi(tmp_path, "b.bin", dati), due, POSTO)
    assert uno.read_bytes() != due.read_bytes()
    assert chiave.leggi_tutto(uno, POSTO) == chiave.leggi_tutto(due, POSTO) == dati


@pytest.mark.parametrize("da, quanti", [
    (0, 10),
    (5, 0),
    (cifratura.BLOCCO - 5, 10),
    (cifratura.BLOCCO, 100),
    (2 * cifratura.BLOCCO + 500, 4000),
    (3 * cifratura.BLOCCO, 999_999),
])
def test_si_legge_un_pezzo_qualsiasi(tmp_path, chiave, da, quanti):
    dati = os.urandom(3 * cifratura.BLOCCO + 4242)
    chiuso = tmp_path / "video.mov"
    chiave.cifra_file(_scrivi(tmp_path, "video-chiaro.mov", dati), chiuso, POSTO)
    assert chiave.leggi_pezzo(chiuso, da, quanti, POSTO) == dati[da:da + quanti]


def test_leggere_un_pezzo_non_legge_tutto(tmp_path, chiave, monkeypatch):
    dati = os.urandom(4 * cifratura.BLOCCO)
    chiuso = tmp_path / "video.mov"
    chiave.cifra_file(_scrivi(tmp_path, "chiaro.mov", dati), chiuso, POSTO)

    letti = []
    apri_vero = open

    class Contato:
        def __init__(self, dentro):
            self._dentro = dentro

        def read(self, quanti=-1):
            pezzo = self._dentro.read(quanti)
            letti.append(len(pezzo))
            return pezzo

        def __getattr__(self, nome):
            return getattr(self._dentro, nome)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return self._dentro.__exit__(*_)

    def apri_contando(percorso, modo="r", *resto, **chiavi):
        return Contato(apri_vero(percorso, modo, *resto, **chiavi))

    monkeypatch.setattr("builtins.open", apri_contando)
    pezzo = chiave.leggi_pezzo(chiuso, 3 * cifratura.BLOCCO + 10, 100, POSTO)
    monkeypatch.undo()

    assert pezzo == dati[3 * cifratura.BLOCCO + 10:3 * cifratura.BLOCCO + 110]
    assert sum(letti) < 2 * cifratura.BLOCCO


def test_la_password_sbagliata_lo_dice_prima_di_aprire_niente():
    sale = cifratura.sale_nuovo()
    giusta = cifratura.Chiave.dalla_password(PASSWORD, sale, **SVELTI)
    prova = giusta.prova()

    assert cifratura.controlla_la_password(
        PASSWORD, sale, prova, **SVELTI)._byte == giusta._byte

    with pytest.raises(PasswordSbagliata):
        cifratura.controlla_la_password("un'altra password", sale, prova,
                                        **SVELTI)


def test_una_chiave_diversa_non_apre_un_file(tmp_path, chiave):
    altra = cifratura.Chiave.dalla_password(PASSWORD, b"un sale diverso",
                                            **SVELTI)
    chiuso = tmp_path / "foto.heic"
    chiave.cifra_file(_scrivi(tmp_path, "chiaro.heic", b"contenuto"), chiuso, POSTO)
    with pytest.raises(cifratura.PacchettoRovinato):
        altra.leggi_tutto(chiuso, POSTO)


def test_un_file_tagliato_non_finisce_piu_corto(tmp_path, chiave):
    dati = os.urandom(2 * cifratura.BLOCCO + 100)
    chiuso = tmp_path / "foto.heic"
    chiave.cifra_file(_scrivi(tmp_path, "chiaro.heic", dati), chiuso, POSTO)

    grezzo = chiuso.read_bytes()
    chiuso.write_bytes(grezzo[:len(grezzo) - 5000])
    with pytest.raises(cifratura.PacchettoRovinato):
        chiave.leggi_tutto(chiuso, POSTO)


def test_un_byte_cambiato_si_vede(tmp_path, chiave):
    chiuso = tmp_path / "foto.heic"
    chiave.cifra_file(_scrivi(tmp_path, "chiaro.heic", os.urandom(5000)),
                      chiuso, POSTO)
    grezzo = bytearray(chiuso.read_bytes())
    grezzo[-40] ^= 0x01
    chiuso.write_bytes(bytes(grezzo))
    with pytest.raises(cifratura.PacchettoRovinato):
        chiave.leggi_tutto(chiuso, POSTO)


def test_i_blocchi_non_si_scambiano(tmp_path, chiave):
    dati = os.urandom(2 * cifratura.BLOCCO)
    chiuso = tmp_path / "foto.heic"
    chiave.cifra_file(_scrivi(tmp_path, "chiaro.heic", dati), chiuso, POSTO)

    grezzo = chiuso.read_bytes()
    inizio = len(grezzo) - 2 * (cifratura.BLOCCO + cifratura.SIGILLO)
    uno = grezzo[inizio:inizio + cifratura.BLOCCO + cifratura.SIGILLO]
    due = grezzo[inizio + cifratura.BLOCCO + cifratura.SIGILLO:]
    chiuso.write_bytes(grezzo[:inizio] + due + uno)

    with pytest.raises(cifratura.PacchettoRovinato):
        chiave.leggi_tutto(chiuso, POSTO)


def test_la_lunghezza_dichiarata_e_autenticata(tmp_path, chiave):
    chiuso = tmp_path / "foto.heic"
    chiave.cifra_file(_scrivi(tmp_path, "chiaro.heic", b"x" * 3000), chiuso, POSTO)

    grezzo = chiuso.read_bytes()
    quanto = int.from_bytes(grezzo[len(cifratura.FIRMA):len(cifratura.FIRMA) + 2],
                            "big")
    inizio = len(cifratura.FIRMA) + 2
    testa = json.loads(grezzo[inizio:inizio + quanto].decode("utf-8"))
    testa["dimensione"] = 2000
    nuova = json.dumps(testa, ensure_ascii=False, sort_keys=True).encode("utf-8")
    chiuso.write_bytes(cifratura.FIRMA + len(nuova).to_bytes(2, "big") + nuova
                       + grezzo[inizio + quanto:])

    with pytest.raises(cifratura.PacchettoRovinato):
        chiave.leggi_tutto(chiuso, POSTO)


def test_un_file_che_non_e_del_visore_lo_dice(tmp_path, chiave):
    finto = _scrivi(tmp_path, "qualcosa.bin", b"non sono un pacchetto")
    with pytest.raises(cifratura.PacchettoRovinato) as guaio:
        chiave.leggi_tutto(finto, POSTO)
    assert "pacchetto" in guaio.value.messaggio.lower()


def test_la_password_corta_non_si_accetta():
    with pytest.raises(ErroreOfficina):
        cifratura.Chiave.dalla_password("corta", b"sale", **SVELTI)


def _carta(**cambi) -> formato.Carta:
    sale = cifratura.sale_nuovo()
    chiave = cifratura.Chiave.dalla_password(PASSWORD, sale, **SVELTI)
    dati = dict(telefono="iPhone", archivio="abc123", sale=sale.hex(),
                prova=chiave.prova(), n=SVELTI["costo"], r=SVELTI["blocco"],
                p=SVELTI["parallelo"])
    dati.update(cambi)
    return formato.Carta(**dati)


def test_la_carta_va_e_torna(tmp_path):
    carta = _carta(quanti_scatti=28_740, peso=41 * 1024 ** 3,
                   dal_giorno="2007-03-01", al_giorno="2026-08-30")
    carta.scrivi(tmp_path)
    riletta = formato.Carta.leggi(tmp_path)
    assert riletta.quanti_scatti == 28_740
    assert riletta.telefono == "iPhone"
    assert not riletta.completa


def test_la_carta_apre_la_chiave_solo_con_la_sua_password(tmp_path):
    carta = _carta()
    assert carta.chiave(PASSWORD)
    with pytest.raises(PasswordSbagliata):
        carta.chiave("un'altra password lunga")


def test_la_carta_non_dice_niente_dell_archivio(tmp_path):
    carta = _carta()
    carta.scrivi(tmp_path)
    testo = (tmp_path / formato.CARTA).read_text(encoding="utf-8")
    dentro = json.loads(testo)
    ammessi = set(formato.Carta.__dataclass_fields__)
    assert set(dentro) <= ammessi
    assert dentro["note"] == []


def test_un_pacchetto_piu_nuovo_del_programma_si_ferma(tmp_path):
    carta = _carta(versione_formato=formato.VERSIONE_FORMATO + 1)
    with pytest.raises(ErroreOfficina) as guaio:
        carta.controlla_il_formato()
    assert guaio.value.codice == "formato_troppo_nuovo"


def test_un_pacchetto_piu_vecchio_si_apre_lo_stesso(tmp_path):
    carta = _carta(versione_formato=formato.VERSIONE_FORMATO - 1)
    carta.controlla_il_formato()
    assert carta.piu_vecchio_del_programma()


def test_dove_non_c_e_un_pacchetto_lo_dice(tmp_path):
    with pytest.raises(ErroreOfficina) as guaio:
        formato.Carta.leggi(tmp_path)
    assert guaio.value.codice == "pacchetto_assente"


def test_una_carta_rovinata_non_e_un_pacchetto_assente(tmp_path):
    (tmp_path / formato.CARTA).write_text("{ non è json", encoding="utf-8")
    with pytest.raises(ErroreOfficina) as guaio:
        formato.Carta.leggi(tmp_path)
    assert guaio.value.codice == "carta_rovinata"


def test_gli_accenti_restano_e_i_caratteri_vietati_no():
    assert formato.nome_utile("Nonnà è al mare.jpg") == "Nonnà è al mare.jpg"
    assert formato.nome_utile('foto:"strana"?.jpg') == "foto__strana__.jpg"
    assert formato.nome_utile("finisce con un punto.") == "finisce con un punto"


def test_il_nome_della_cartella_dice_per_chi_e():
    assert formato.nome_cartella("iPhone") == "Visore-iPhone"
    assert formato.nome_cartella("Redmi Note 11") == "Visore-Redmi Note 11"


def test_i_nomi_nel_pacchetto_sono_a_caso():
    uno = formato.posto_dell_originale()
    due = formato.posto_dell_originale()
    assert uno != due
    cartella, sotto, nome = uno.split("/")
    assert cartella == "foto" and sotto == nome[:2]
    assert re.fullmatch(r"[0-9a-f]{32}", nome)
    assert formato.e_a_caso(uno) and formato.e_a_caso(due)


def test_le_miniature_si_spargono_in_sottocartelle():
    posto = formato.posto_della_miniatura()
    cartella, sotto, nome = posto.split("/")
    assert cartella == "mini" and sotto == nome[:2]
    assert "." not in posto
    assert formato.e_a_caso(posto)


def test_i_volti_non_si_chiamano_ne_col_numero_ne_col_nome():
    posto = formato.posto_del_volto()
    assert re.fullmatch(r"volti/[0-9a-f]{32}", posto)
    assert formato.e_a_caso(posto)


@pytest.mark.parametrize("posto", ["foto/2019/07/IMG_1234.HEIC", "volti/12.jpg",
                                   "mini/a3/" + "a3" * 32 + ".jpg", "../fuori"])
def test_i_nomi_vecchi_non_sono_a_caso(posto):
    assert not formato.e_a_caso(posto)
