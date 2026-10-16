from __future__ import annotations

import pytest

from officina.errori import OperazioneNonPermessa
from officina.misura import banco, rapporto as resoconto
from officina.modello import nodi


def test_la_misura_gira_e_confronta_qualcosa(archivio_misurabile):
    misurato = banco.misura(archivio_misurabile)
    assert misurato.scatti > 0
    assert misurato.gruppi > 0
    assert misurato.righe, "non ha confrontato niente"
    inquadrature = {riga.inquadratura for riga in misurato.righe}
    assert {"intera", "persona", "stretto"} <= inquadrature
    assert "tutte e tre" in inquadrature


def test_ogni_confronto_usa_gli_stessi_esempi(archivio_misurabile):
    misurato = banco.misura(archivio_misurabile)
    con_voto = [riga for riga in misurato.righe if riga.voti]
    assert con_voto
    nodi_visti = {tuple(sorted(riga.voti)) for riga in con_voto}
    assert len(nodi_visti) == 1, "righe diverse hanno guardato nodi diversi"


def test_il_rapporto_non_contiene_nessun_nome(archivio_misurabile):
    nomi_veri = ["Magliette Tommy", "Vacanze in Irlanda", "Persona A"]
    with archivio_misurabile.scrittura() as connessione:
        for nome in nomi_veri:
            nodi.crea(connessione, nome, None,
                      criterio=f"qui dentro va solo {nome.lower()}")

    misurato = banco.misura(archivio_misurabile)
    testo = resoconto.come_testo(misurato)

    for nome in nomi_veri:
        assert nome not in testo
        assert nome.lower() not in testo.lower()
    with archivio_misurabile.lettura() as connessione:
        assert resoconto.controlla(testo, connessione) == []


def test_il_controllo_si_accorge_di_una_fuga(archivio_misurabile):
    with archivio_misurabile.scrittura() as connessione:
        nodi.crea(connessione, "Maglietta gialla", None)
    sporco = "il nodo Maglietta gialla prende il 78% su 40 esempi"
    with archivio_misurabile.lettura() as connessione:
        trovati = resoconto.controlla(sporco, connessione)
    assert trovati and "Maglietta gialla" in trovati[0]


def test_i_percorsi_non_passano(archivio_misurabile):
    with archivio_misurabile.lettura() as connessione:
        assert resoconto.controlla(r"tutto bene C:\Users\x\Foto\IMG_1.HEIC",
                                   connessione)
        assert resoconto.controlla("cartella /home/qualcuno/foto", connessione)


def test_un_rapporto_sporco_non_si_scrive(archivio_misurabile, tmp_path):
    misurato = banco.misura(archivio_misurabile)
    with archivio_misurabile.scrittura() as connessione:
        nodi.crea(connessione, "descrittore", None)
    with archivio_misurabile.lettura() as connessione:
        with pytest.raises(OperazioneNonPermessa):
            resoconto.scrivi(misurato, connessione, tmp_path / "misura.txt")
    assert not (tmp_path / "misura.txt").exists()


def test_i_nomi_astratti_non_fanno_scattare_l_allarme(archivio_misurabile):
    misurato = banco.misura(archivio_misurabile)
    testo = resoconto.come_testo(misurato)
    assert "nodo_1" in testo
    with archivio_misurabile.lettura() as connessione:
        assert resoconto.controlla(testo, connessione) == []


def test_le_conclusioni_vengono_dai_numeri(archivio_misurabile):
    misurato = banco.misura(archivio_misurabile)
    frasi = resoconto.conclusioni(misurato)
    assert frasi
    migliore = misurato.migliore()
    if migliore is not None and migliore.azzecca is not None:
        assert f"{migliore.azzecca * 100:.0f}%" in " ".join(frasi)


def test_senza_esempi_lo_dice_invece_di_inventare(archivio_pieno):
    with pytest.raises(banco.NienteDaMisurare) as errore:
        banco.misura(archivio_pieno)
    assert "regola 105" in str(errore.value) or "Misura" in str(errore.value)


def test_il_rapporto_si_puo_rileggere_come_numeri(archivio_misurabile):
    import json

    misurato = banco.misura(archivio_misurabile)
    dati = json.loads(resoconto.come_json(misurato))
    assert dati["scatti"] == misurato.scatti
    assert len(dati["righe"]) == len(misurato.righe)
    assert dati["conclusioni"]


def test_anche_i_numeri_si_controllano(archivio_misurabile, tmp_path):
    misurato = banco.misura(archivio_misurabile)
    with archivio_misurabile.lettura() as connessione:
        resoconto.scrivi(misurato, connessione, tmp_path / "misura.txt")
        assert (tmp_path / "misura.txt").exists()
        assert (tmp_path / "misura.json").exists()
        assert resoconto.controlla(
            (tmp_path / "misura.json").read_text(encoding="utf-8"), connessione) == []


def _metti_le_caselle(archivio):
    import random

    from officina.archivio.database import tutti
    from officina.descrittori import vettori
    from officina.modello import impronte

    caso = random.Random(7)
    with archivio.scrittura() as connessione:
        righe = tutti(connessione, "SELECT scatto_id, file_id, descrittore, versione, "
                                   "valori FROM impronte WHERE inquadratura = 'intera'")
        for riga in righe:
            base = vettori.matrice([riga["valori"]])[0].tolist()
            for casella in ("griglia_r00c00", "griglia_r00c01"):
                rumore = [v + caso.gauss(0, 0.05) for v in base]
                impronte.scrivi(connessione, riga["scatto_id"], riga["file_id"],
                                riga["descrittore"], riga["versione"], casella,
                                "griglia", None, rumore)


def test_massimo_e_media_delle_caselle_si_misurano(archivio_misurabile):
    _metti_le_caselle(archivio_misurabile)
    misurato = banco.misura(archivio_misurabile)
    inquadrature = {riga.inquadratura for riga in misurato.righe}
    assert {"caselle · massimo", "caselle · media"} <= inquadrature
    testo = " ".join(resoconto.conclusioni(misurato))
    assert "caselle" in testo


def test_senza_caselle_non_compaiono(archivio_misurabile):
    misurato = banco.misura(archivio_misurabile)
    assert not any(riga.inquadratura.startswith("caselle")
                   for riga in misurato.righe)
