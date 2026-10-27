from __future__ import annotations

import dataclasses
import io
import math
import threading
import weakref

import pytest
from PIL import Image

from officina import registro
from officina.archivio.database import tutti, uno
from officina.errori import (DaRifare, ErroreOfficina, FileNonLeggibile, PasswordSbagliata,
                             perche_saltato)
from officina.immagini import lettura
from officina.importazione import (metadati, raddrizza, rileggi_date, rileggi_macchine,
                                    ripasso)
from officina.modello import file_media, segnalazioni
from officina.programma import archivio_sicuro
from officina.sicuro.dall_archivio import (CHIUSO_ADESSO, DIVERSA, PERSA, SENZA_ARCHIVIO,
                                           SI_APRE, DallArchivio, attento, da_rifare)
from prove import test_programma_finestre as finestre
from prove import test_sicuro_dall_archivio as dall_archivio_di_prova
from prove import test_sicuro_nel_programma as nel_programma
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_sicuro_dall_archivio import _impronta, _prepara, _rovina, _stacca
from prove.test_sicuro_servizio import ATTESA, PAROLA

costo_leggero = servizio_di_prova.costo_leggero
LARGA, ALTA, F35 = 400, 300, 26
foto_nell_archivio = dall_archivio_di_prova.foto_nell_archivio
casa = finestre.casa
posto = nel_programma.posto


def _avvisi(monkeypatch) -> list:
    detti: list = []
    monkeypatch.setattr(registro, "avviso",
                        lambda nome, **campi: detti.append((nome, campi)))
    return detti


def _guarda(pronta):
    with pronta.archivio.lettura() as connessione:
        return file_media.da_guardare(connessione, pronta.file_id)


def _codice(fare) -> str:
    with pytest.raises(ErroreOfficina) as preso:
        fare()
    return preso.value.codice


def _diversa(pronta) -> None:
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                            (_impronta(b"la versione importata"), pronta.file_id))


def _chiudi(pronta) -> None:
    assert pronta.casa.archivio.chiudi(ATTESA)


def _riapri(pronta) -> None:
    pronta.casa.archivio.apri(PAROLA)


def _messe_da_parte(pronta) -> list:
    with pronta.archivio.lettura() as connessione:
        return [(riga["tipo"], riga["dettaglio"], riga["file_id"]) for riga in tutti(
            connessione, "SELECT tipo, dettaglio, file_id FROM segnalazioni "
            "WHERE scatto_id = ? AND risolta = 0", pronta.scatto_id)]


def test_sul_disco_si_guarda_il_file_e_l_archivio_non_si_tocca(foto_nell_archivio,
                                                               monkeypatch):
    pronta = foto_nell_archivio
    pronta.originale.write_bytes(pronta.dati)
    monkeypatch.setattr(file_media, "cerca_nell_archivio",
                        lambda *_: pytest.fail("non doveva cercare"))
    assert _guarda(pronta) == pronta.originale


def test_solo_nell_archivio_si_guarda_dall_archivio(foto_nell_archivio):
    pronta = foto_nell_archivio
    trovata = _guarda(pronta)
    assert isinstance(trovata, DallArchivio)
    assert trovata.intero and not trovata.diversa
    with trovata.apri() as flusso:
        assert flusso.read() == pronta.dati


@pytest.mark.parametrize("come", ["chiuso", "si_apre"])
def test_con_l_archivio_chiuso_si_rifa_dopo(foto_nell_archivio, come):
    pronta = foto_nell_archivio
    if come == "chiuso":
        _chiudi(pronta)
    else:
        pronta.situazione.forzata = SI_APRE
    with pytest.raises(DaRifare) as preso:
        _guarda(pronta)
    assert preso.value.codice == CHIUSO_ADESSO
    assert preso.value.messaggio.startswith("Il file non è sul disco")


def test_una_versione_diversa_non_si_guarda(foto_nell_archivio):
    pronta = foto_nell_archivio
    _diversa(pronta)
    with pytest.raises(FileNonLeggibile) as preso:
        _guarda(pronta)
    assert not isinstance(preso.value, DaRifare)
    assert preso.value.codice == DIVERSA and preso.value.file_id == pronta.file_id
    testo = perche_saltato(DIVERSA)
    assert preso.value.messaggio == testo[:1].upper() + testo[1:] + "."


def test_una_ricerca_che_si_rompe_si_rifa_e_si_dice(foto_nell_archivio, monkeypatch):
    pronta = foto_nell_archivio
    detti = _avvisi(monkeypatch)

    def rotta(*_):
        raise ErroreOfficina("si è rotto", codice="qualcosa_di_strano")

    monkeypatch.setattr(file_media, "cerca_nell_archivio", rotta)
    assert _codice(lambda: _guarda(pronta)) == CHIUSO_ADESSO
    assert detti == [("sicuro.ricerca_non_riuscita",
                      {"motivo": registro.Parola("qualcosa_di_strano")})]
    gia = DaRifare("persa", codice=PERSA)

    def rifare(*_):
        raise gia

    monkeypatch.setattr(file_media, "cerca_nell_archivio", rifare)
    with pytest.raises(DaRifare) as preso:
        _guarda(pronta)
    assert preso.value is gia and len(detti) == 1


def test_senza_archivio_o_senza_impronta_non_c_e_niente(foto_nell_archivio):
    pronta = foto_nell_archivio
    pronta.situazione.forzata = SENZA_ARCHIVIO
    assert _guarda(pronta) is None
    pronta.situazione.forzata = None
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = '' WHERE id = ?",
                            (pronta.file_id,))
    assert _guarda(pronta) is None


def test_un_ritocco_non_cambia_quello_che_guarda_l_ia(foto_nell_archivio):
    pronta = foto_nell_archivio
    copia = pronta.casa.base / "ritoccata.jpg"
    copia.write_bytes(b"ritocco")
    with pronta.archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO ritoccate (file_id, stato, percorso_copia, impronta_copia, "
            "percorso_base, impronta_base, base_e) VALUES (?, 'fatta', ?, ?, ?, ?, "
            "'originale')",
            (pronta.file_id, str(copia), _impronta(b"ritocco"), str(pronta.originale),
             _impronta(pronta.dati)))
    assert isinstance(_guarda(pronta), DallArchivio)


def _solo_questo(pronta) -> None:
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE scatti SET fuori_archivio = 1 WHERE id != ?",
                            (pronta.scatto_id,))
        connessione.execute("DELETE FROM segnalazioni WHERE scatto_id = ?",
                            (pronta.scatto_id,))


def _impronte_di(pronta) -> int:
    with pronta.archivio.lettura() as connessione:
        return uno(connessione, "SELECT count(*) AS q FROM impronte WHERE scatto_id = ?",
                   pronta.scatto_id)["q"]


def _passata_impronte(pronta):
    from officina.impronte.motore import Passata

    passata = Passata(pronta.archivio, "disegnato", intensita=100)
    return passata, passata.esegui()


def test_le_impronte_si_fanno_dall_archivio(foto_nell_archivio):
    pronta = foto_nell_archivio
    _solo_questo(pronta)
    passata, fatto = _passata_impronte(pronta)
    assert fatto.fatti == 1 and fatto.saltati == 0
    assert _impronte_di(pronta) > 0 and passata.quanti_mancano() == 0
    assert not pronta.originale.exists()


def test_con_l_archivio_chiuso_le_impronte_aspettano_senza_mettere_da_parte(
        foto_nell_archivio):
    pronta = foto_nell_archivio
    _solo_questo(pronta)
    _chiudi(pronta)
    passata, fatto = _passata_impronte(pronta)
    assert fatto.fatti == 0 and fatto.saltati == 1
    assert fatto.motivi_saltati == {CHIUSO_ADESSO: 1}
    assert fatto.scatti_saltati == [(pronta.scatto_id, CHIUSO_ADESSO)]
    assert fatto.messi_da_parte == 0 and _messe_da_parte(pronta) == []
    assert _impronte_di(pronta) == 0 and passata.quanti_mancano() == 1
    _riapri(pronta)
    _, di_nuovo = _passata_impronte(pronta)
    assert di_nuovo.fatti == 1 and _impronte_di(pronta) > 0


def test_una_versione_diversa_si_mette_da_parte_e_non_fa_impronte(foto_nell_archivio):
    pronta = foto_nell_archivio
    _solo_questo(pronta)
    _diversa(pronta)
    _, fatto = _passata_impronte(pronta)
    assert fatto.motivi_saltati == {DIVERSA: 1} and fatto.messi_da_parte == 1
    assert _messe_da_parte(pronta) == [(segnalazioni.NON_SI_APRE, DIVERSA, pronta.file_id)]
    assert _impronte_di(pronta) == 0


def test_una_foto_persa_nell_archivio_aspetta_la_riparazione(foto_nell_archivio):
    pronta = foto_nell_archivio
    _solo_questo(pronta)
    _stacca(pronta.casa)
    _rovina(pronta.casa, pronta.relativo)
    passata, fatto = _passata_impronte(pronta)
    assert fatto.motivi_saltati == {PERSA: 1} and fatto.messi_da_parte == 0
    assert _messe_da_parte(pronta) == [] and _impronte_di(pronta) == 0
    assert passata.quanti_mancano() == 1


def _volti(archivio):
    from officina.volti.motore import Passata
    from prove.test_volti import RilevatoreFinto

    return Passata(archivio, rilevatore=RilevatoreFinto(), intensita=100)


def _corpi(archivio):
    from officina.corpi.motore import Passata
    from prove.test_corpi import RilevatoreFinto

    return Passata(archivio, rilevatore=RilevatoreFinto(), intensita=100)


def _scritte(archivio):
    from officina.parole.motore import Passata
    from prove.test_parole import _LettoreFinto

    return Passata(archivio, lettore=_LettoreFinto([["Bar Sport"]]), intensita=100)


LAVORI = {"volti": (_volti, "motivi"), "corpi": (_corpi, "motivi"),
          "scritte": (_scritte, "motivi_saltati")}


def _gira(pronta, quale: str) -> tuple[object, dict]:
    fai, motivi = LAVORI[quale]
    passata = fai(pronta.archivio)
    fatto = passata.esegui()
    return passata, getattr(fatto, motivi)


@pytest.mark.parametrize("quale", sorted(LAVORI))
def test_ogni_lavoro_ia_guarda_dall_archivio(foto_nell_archivio, quale):
    pronta = foto_nell_archivio
    _solo_questo(pronta)
    assert LAVORI[quale][0](pronta.archivio).quanti_mancano() == 1
    passata, motivi = _gira(pronta, quale)
    assert motivi == {} and passata.avanzamento.saltati == 0
    assert passata.quanti_mancano() == 0 and _messe_da_parte(pronta) == []


@pytest.mark.parametrize("quale", sorted(LAVORI))
def test_ogni_lavoro_ia_aspetta_l_archivio_chiuso_senza_segnare_niente(foto_nell_archivio,
                                                                       quale):
    pronta = foto_nell_archivio
    _solo_questo(pronta)
    _chiudi(pronta)
    passata, motivi = _gira(pronta, quale)
    assert motivi == {CHIUSO_ADESSO: 1} and passata.avanzamento.saltati == 1
    assert passata.quanti_mancano() == 1 and _messe_da_parte(pronta) == []
    _riapri(pronta)
    di_nuovo, motivi = _gira(pronta, quale)
    assert motivi == {} and di_nuovo.quanti_mancano() == 0


@pytest.mark.parametrize("quale", sorted(LAVORI))
def test_ogni_lavoro_ia_mette_da_parte_la_versione_diversa(foto_nell_archivio, quale):
    pronta = foto_nell_archivio
    _solo_questo(pronta)
    _diversa(pronta)
    _, motivi = _gira(pronta, quale)
    assert motivi == {DIVERSA: 1}
    assert _messe_da_parte(pronta) == [(segnalazioni.NON_SI_APRE, DIVERSA, pronta.file_id)]


@pytest.mark.parametrize("quale", sorted(LAVORI))
def test_ogni_lavoro_ia_aspetta_la_riparazione_di_una_foto_persa(foto_nell_archivio, quale):
    pronta = foto_nell_archivio
    _solo_questo(pronta)
    _stacca(pronta.casa)
    _rovina(pronta.casa, pronta.relativo)
    passata, motivi = _gira(pronta, quale)
    assert motivi == {PERSA: 1}
    assert passata.quanti_mancano() == 1 and _messe_da_parte(pronta) == []


def _con_i_punti_vecchi(pronta) -> int:
    from officina.corpi import motore

    _solo_questo(pronta)
    _gira(pronta, "corpi")
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE corpi SET punti_scala = 1")
        return motore.quanti_da_ripuntare_senza_aprire(connessione)


def _da_ripuntare(pronta) -> int:
    from officina.corpi import motore

    with pronta.archivio.lettura() as connessione:
        return motore.quanti_da_ripuntare_senza_aprire(connessione)


def test_i_punti_si_rifanno_dall_archivio_e_aspettano_se_e_chiuso(foto_nell_archivio):
    from prove.test_corpi import RipuntatoreFinto

    pronta = foto_nell_archivio
    quanti = _con_i_punti_vecchi(pronta)
    assert quanti > 0
    _chiudi(pronta)
    passata = _corpi(pronta.archivio)
    assert passata.rifai_i_punti() == 0
    assert passata.avanzamento.motivi == {CHIUSO_ADESSO: 1}
    assert _da_ripuntare(pronta) == quanti and _messe_da_parte(pronta) == []
    _riapri(pronta)
    from officina.corpi.motore import Passata

    finto = RipuntatoreFinto()
    assert Passata(pronta.archivio, rilevatore=finto, intensita=100).rifai_i_punti() > 0
    assert finto.chiesti and _da_ripuntare(pronta) == 0


def test_i_punti_di_una_versione_diversa_si_mettono_da_parte(foto_nell_archivio):
    pronta = foto_nell_archivio
    _con_i_punti_vecchi(pronta)
    _diversa(pronta)
    passata = _corpi(pronta.archivio)
    assert passata.rifai_i_punti() == 0
    assert passata.avanzamento.motivi == {DIVERSA: 1}
    assert _messe_da_parte(pronta) == [(segnalazioni.NON_SI_APRE, DIVERSA, pronta.file_id)]


def _col_fuoco() -> bytes:
    from officina.corpi import figure

    immagine = Image.new("RGB", (LARGA, ALTA), (120, 120, 120))
    exif = Image.Exif()
    exif.get_ifd(figure.IFD_EXIF)[figure.FUOCO_35MM] = F35
    fatta = io.BytesIO()
    immagine.save(fatta, "JPEG", exif=exif)
    return fatta.getvalue()


@pytest.fixture
def fuoco_nell_archivio(tmp_path, archivio_pieno, monkeypatch):
    pronta = _prepara(tmp_path, archivio_pieno, monkeypatch, "s/fuoco.jpg", _col_fuoco(),
                      "immagine", "jpeg")
    yield pronta
    pronta.casa.chiudi()


def _campo() -> float:
    from officina.corpi import figure

    fuoco = F35 * math.hypot(LARGA, ALTA) / figure.DIAGONALE_35MM
    return 2 * math.atan(ALTA / (2 * fuoco))


def test_il_fuoco_si_legge_anche_dall_archivio(fuoco_nell_archivio):
    from officina.corpi import figure

    trovata = _guarda(fuoco_nell_archivio)
    assert isinstance(trovata, DallArchivio)
    assert figure.campo_dall_exif(trovata, LARGA, ALTA) == pytest.approx(_campo())
    assert figure.campo_dall_exif(trovata, LARGA, 250) is None


def _figure_pronte(pronta):
    from officina.corpi import figure
    from prove.test_figure import FigureFinte, _con_i_corpi

    _solo_questo(pronta)
    _con_i_corpi(pronta.archivio)
    return lambda: figure.Passata(pronta.archivio, figure=FigureFinte())


def test_le_figure_si_fanno_dall_archivio_col_fuoco_della_foto(fuoco_nell_archivio):
    from officina.corpi import figure

    pronta = fuoco_nell_archivio
    nuova = _figure_pronte(pronta)
    assert nuova().quanti_mancano() == 1
    fatto = nuova().esegui()
    assert fatto.fatti == 1 and fatto.saltati == 0 and fatto.dall_exif == 1
    with pronta.archivio.lettura() as connessione:
        lente = uno(connessione, "SELECT fonte, campo_verticale FROM obiettivi "
                    "WHERE scatto_id = ?", pronta.scatto_id)
    assert lente["fonte"] == figure.EXIF
    assert lente["campo_verticale"] == pytest.approx(_campo())
    assert nuova().quanti_mancano() == 0


def test_le_figure_aspettano_l_archivio_chiuso(fuoco_nell_archivio):
    pronta = fuoco_nell_archivio
    nuova = _figure_pronte(pronta)
    _chiudi(pronta)
    fatto = nuova().esegui()
    assert fatto.fatti == 0 and fatto.motivi == {CHIUSO_ADESSO: 1}
    assert nuova().quanti_mancano() == 1 and _messe_da_parte(pronta) == []
    with pronta.archivio.lettura() as connessione:
        assert uno(connessione, "SELECT count(*) AS q FROM obiettivi WHERE scatto_id = ?",
                   pronta.scatto_id)["q"] == 0
    _riapri(pronta)
    assert nuova().esegui().fatti == 1


def test_le_figure_aspettano_la_riparazione_di_una_foto_persa(foto_nell_archivio):
    pronta = foto_nell_archivio
    nuova = _figure_pronte(pronta)
    _stacca(pronta.casa)
    _rovina(pronta.casa, pronta.relativo)
    fatto = nuova().esegui()
    assert fatto.fatti == 0 and fatto.motivi == {PERSA: 1}
    assert nuova().quanti_mancano() == 1 and _messe_da_parte(pronta) == []


def test_le_figure_di_una_versione_diversa_si_mettono_da_parte(fuoco_nell_archivio):
    pronta = fuoco_nell_archivio
    nuova = _figure_pronte(pronta)
    _diversa(pronta)
    fatto = nuova().esegui()
    assert fatto.fatti == 0 and fatto.motivi == {DIVERSA: 1}
    assert _messe_da_parte(pronta) == [(segnalazioni.NON_SI_APRE, DIVERSA, pronta.file_id)]


def _posto_con_la_foto(pronta) -> int:
    from prove.test_costruzione_stanza import _foto_dell_archivio, _un_posto_con

    altre = [scatto for scatto in _foto_dell_archivio(pronta.archivio)
             if scatto != pronta.scatto_id][:6]
    assert len(altre) == 6
    return _un_posto_con(pronta.archivio, [pronta.scatto_id, *altre])


def _stanza(pronta):
    from officina.stanza import costruzione
    from prove.test_costruzione_stanza import ModelliFinti

    return costruzione.Passata(pronta.archivio, modelli=ModelliFinti()).esegui()


def _messe_nella_stanza(pronta, posto_id: int) -> dict[int, bool]:
    from officina.modello import stanze

    with pronta.archivio.lettura() as connessione:
        return {messa["scatto_id"]: bool(messa["usata"])
                for messa in stanze.foto_di(connessione, posto_id)}


def _da_costruire(pronta) -> list:
    from officina.stanza import costruzione

    with pronta.archivio.lettura() as connessione:
        return costruzione.da_fare(connessione)


def test_la_stanza_si_costruisce_anche_con_una_foto_dall_archivio(foto_nell_archivio):
    pronta = foto_nell_archivio
    posto_id = _posto_con_la_foto(pronta)
    fatto = _stanza(pronta)
    assert fatto.stanze == 1 and fatto.foto_messe == 7 and fatto.motivi == {}
    assert _messe_nella_stanza(pronta, posto_id)[pronta.scatto_id] is True
    assert _da_costruire(pronta) == []


@pytest.mark.parametrize("come", [CHIUSO_ADESSO, PERSA])
def test_se_la_foto_non_si_legge_adesso_la_stanza_aspetta_intera(foto_nell_archivio, come):
    pronta = foto_nell_archivio
    posto_id = _posto_con_la_foto(pronta)
    if come == PERSA:
        _stacca(pronta.casa)
        _rovina(pronta.casa, pronta.relativo)
    else:
        _chiudi(pronta)
    fatto = _stanza(pronta)
    assert fatto.stanze == 0 and fatto.non_riuscite == 0
    assert fatto.motivi == {come: 1}
    assert _messe_nella_stanza(pronta, posto_id) == {}
    assert _da_costruire(pronta) == [(posto_id, "costruisci")]
    if come == CHIUSO_ADESSO:
        _riapri(pronta)
        di_nuovo = _stanza(pronta)
        assert di_nuovo.stanze == 1 and di_nuovo.foto_messe == 7


def test_la_stanza_non_usa_una_versione_diversa(foto_nell_archivio):
    pronta = foto_nell_archivio
    posto_id = _posto_con_la_foto(pronta)
    _diversa(pronta)
    fatto = _stanza(pronta)
    assert fatto.stanze == 1 and fatto.motivi == {}
    messe = _messe_nella_stanza(pronta, posto_id)
    assert pronta.scatto_id not in messe and len(messe) == 6


def _doppioni(pronta):
    from officina.doppioni.motore import Passata

    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta_occhio = CASE WHEN id = ? "
                            "THEN NULL ELSE coalesce(impronta_occhio, '') END",
                            (pronta.file_id,))
    return Passata(pronta.archivio).esegui()


def _occhio(pronta) -> str | None:
    with pronta.archivio.lettura() as connessione:
        return uno(connessione, "SELECT impronta_occhio AS o FROM file_media WHERE id = ?",
                   pronta.file_id)["o"]


def test_i_doppioni_si_guardano_anche_dall_archivio(foto_nell_archivio):
    from officina.doppioni import occhio

    pronta = foto_nell_archivio
    fatto = _doppioni(pronta)
    assert fatto.guardate == 1 and fatto.saltate == 0
    assert _occhio(pronta) == occhio.del_percorso(_guarda(pronta))
    assert _occhio(pronta)


@pytest.mark.parametrize("come", [CHIUSO_ADESSO, PERSA])
def test_i_doppioni_aspettano_una_foto_che_adesso_non_si_legge(foto_nell_archivio, come):
    pronta = foto_nell_archivio
    if come == PERSA:
        _stacca(pronta.casa)
        _rovina(pronta.casa, pronta.relativo)
    else:
        _chiudi(pronta)
    fatto = _doppioni(pronta)
    assert fatto.guardate == 0 and fatto.saltate == 1
    assert fatto.motivi_saltate == {come: 1}
    assert _occhio(pronta) is None


def test_i_doppioni_non_guardano_una_versione_diversa(foto_nell_archivio, monkeypatch):
    from officina.doppioni.motore import NON_SI_E_POTUTA

    pronta = foto_nell_archivio
    detti = _avvisi(monkeypatch)
    _diversa(pronta)
    fatto = _doppioni(pronta)
    assert fatto.guardate == 0 and fatto.motivi_saltate == {DIVERSA: 1}
    assert _occhio(pronta) == NON_SI_E_POTUTA
    assert detti == [("doppioni_immagine_non_guardata",
                      {"file_id": pronta.file_id, "motivo": registro.Parola(DIVERSA)})]


def test_i_doppioni_guardano_il_percorso_che_c_e(foto_nell_archivio):
    pronta = foto_nell_archivio
    copia = pronta.casa.base / "copia.jpg"
    copia.write_bytes(pronta.dati)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE percorsi SET presente = 1 WHERE file_id = ?",
                            (pronta.file_id,))
        connessione.execute(
            "INSERT INTO percorsi (file_id, percorso, nome, presente, visto_il) "
            "VALUES (?, ?, ?, 0, '2026-01-01T00:00:00')",
            (pronta.file_id, str(copia), copia.name))
    _chiudi(pronta)
    assert _guarda(pronta) == copia
    fatto = _doppioni(pronta)
    assert fatto.guardate == 1 and _occhio(pronta)


def _con_data_e_macchina() -> bytes:
    exif = Image.Exif()
    exif[0x0132] = "2021:06:01 10:00:00"
    exif[0x010F] = "Canon"
    exif[0x0110] = "Canon EOS 80D"
    fatta = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 40, 40)).save(fatta, "JPEG", exif=exif)
    return fatta.getvalue()


@pytest.fixture
def scheda_nell_archivio(tmp_path, archivio_pieno, monkeypatch):
    pronta = _prepara(tmp_path, archivio_pieno, monkeypatch, "s/scheda.jpg",
                      _con_data_e_macchina(), "immagine", "jpeg")
    yield pronta
    pronta.casa.chiudi()


@pytest.fixture
def girato_nell_archivio(tmp_path, archivio_pieno, monkeypatch):
    from prove.test_video_girati import _video

    girato = _video(tmp_path / "girato.mov", 90).read_bytes()
    pronta = _prepara(tmp_path, archivio_pieno, monkeypatch, "v/girato.mov", girato,
                      "video", "mov")
    yield pronta
    pronta.casa.chiudi()


def _senza_data(connessione, pronta) -> None:
    connessione.execute("UPDATE file_media SET data_locale = NULL, fuso_minuti = NULL, "
                        "istante_utc = NULL, origine_data = 'assente' WHERE id = ?",
                        (pronta.file_id,))
    connessione.execute("UPDATE scatti SET data_locale = NULL, fuso_minuti = NULL, "
                        "istante_utc = NULL, giorno = NULL, origine_data = 'assente' "
                        "WHERE id = ?", (pronta.scatto_id,))


def _con_la_data(connessione, pronta) -> bool:
    return uno(connessione, "SELECT giorno FROM scatti WHERE id = ?",
               pronta.scatto_id)["giorno"] == "2021-06-01"


def _senza_macchina(connessione, pronta) -> None:
    connessione.execute("UPDATE file_media SET marca = NULL, modello = NULL WHERE id = ?",
                        (pronta.file_id,))


def _con_la_macchina(connessione, pronta) -> bool:
    riga = uno(connessione, "SELECT marca, modello FROM file_media WHERE id = ?",
               pronta.file_id)
    return (riga["marca"], riga["modello"]) == ("Canon", "Canon EOS 80D")


def _storto(connessione, pronta) -> None:
    from prove.test_video_girati import ALTA, LARGA

    connessione.execute("UPDATE file_media SET larghezza = ?, altezza = ? WHERE id = ?",
                        (LARGA, ALTA, pronta.file_id))


def _dritto(connessione, pronta) -> bool:
    from prove.test_video_girati import ALTA, LARGA

    riga = uno(connessione, "SELECT larghezza, altezza FROM file_media WHERE id = ?",
               pronta.file_id)
    return (riga["larghezza"], riga["altezza"]) == (ALTA, LARGA)


RILETTORI = {
    "date": ("scheda_nell_archivio", rileggi_date, rileggi_date.tutti_i_file,
             rileggi_date.RIMANDATE, _senza_data, _con_la_data),
    "macchine": ("scheda_nell_archivio", rileggi_macchine, rileggi_macchine.tutti_i_file,
                 rileggi_macchine.RIMANDATE, _senza_macchina, _con_la_macchina),
    "video": ("girato_nell_archivio", raddrizza, raddrizza.tutti_i_video,
              raddrizza.RIMANDATI, _storto, _dritto),
}


class _Rilettore:

    def __init__(self, request, quale: str):
        fixture, self.modulo, self._tutti, self.lasciati, prepara, self._fatto = (
            RILETTORI[quale])
        self.pronta = request.getfixturevalue(fixture)
        archivio = self.pronta.archivio
        with archivio.scrittura() as connessione:
            prepara(connessione, self.pronta)
        archivio.salva_stato(self.modulo.FINO_A, self.pronta.file_id)
        archivio.salva_stato(self.modulo.DA, self.pronta.file_id - 1)

    def gira(self) -> int:
        return self._tutti(self.pronta.archivio)

    def fatto(self) -> bool:
        with self.pronta.archivio.lettura() as connessione:
            return self._fatto(connessione, self.pronta)

    def rimandati(self) -> list[int]:
        return ripasso.rimandati(self.pronta.archivio, self.lasciati)

    def aperto(self) -> bool:
        return self.pronta.archivio.stato(self.modulo.FINO_A) is not None

    def restano(self) -> int:
        return self.modulo.quanti_restano(self.pronta.archivio)


@pytest.mark.parametrize("quale", sorted(RILETTORI))
def test_un_rilettore_legge_dall_archivio(request, quale):
    lettore = _Rilettore(request, quale)
    assert not lettore.fatto() and lettore.restano() == 1
    assert lettore.gira() == 1
    assert lettore.fatto() and not lettore.aperto() and lettore.restano() == 0


@pytest.mark.parametrize("quale", sorted(RILETTORI))
def test_un_rilettore_tiene_da_parte_le_foto_dell_archivio_chiuso(request, quale):
    lettore = _Rilettore(request, quale)
    _chiudi(lettore.pronta)
    for _ in range(2):
        assert lettore.gira() == 0
        assert lettore.rimandati() == [lettore.pronta.file_id]
        assert lettore.aperto() and lettore.restano() == 1 and not lettore.fatto()
    _riapri(lettore.pronta)
    assert lettore.gira() == 1
    assert lettore.fatto() and not lettore.aperto() and lettore.restano() == 0
    assert lettore.pronta.archivio.stato(lettore.lasciati) is None
    assert lettore.pronta.archivio.stato(lettore.modulo.DA) is None


@pytest.mark.parametrize("quale", sorted(RILETTORI))
def test_un_rilettore_aspetta_la_riparazione_di_una_foto_persa(request, quale):
    lettore = _Rilettore(request, quale)
    _stacca(lettore.pronta.casa)
    _rovina(lettore.pronta.casa, lettore.pronta.relativo)
    assert lettore.gira() == 0
    assert lettore.rimandati() == [lettore.pronta.file_id]
    assert lettore.aperto() and not lettore.fatto()


@pytest.mark.parametrize("quale", sorted(RILETTORI))
def test_un_rilettore_lascia_stare_la_versione_diversa_e_finisce(request, quale):
    lettore = _Rilettore(request, quale)
    _diversa(lettore.pronta)
    assert lettore.gira() == 0
    assert not lettore.fatto() and not lettore.aperto() and lettore.rimandati() == []


def _errori(monkeypatch) -> list:
    detti: list = []
    monkeypatch.setattr(registro, "errore",
                        lambda nome, **campi: detti.append((nome, campi)))
    return detti


def _senza_data_e_da_sola(pronta) -> None:
    _solo_questo(pronta)
    with pronta.archivio.scrittura() as connessione:
        _senza_data(connessione, pronta)


def test_perche_manca_la_data_si_guarda_anche_dall_archivio(scheda_nell_archivio, tmp_path):
    pronta = scheda_nell_archivio
    _senza_data_e_da_sola(pronta)
    copia = tmp_path / "scheda.jpg"
    copia.write_bytes(pronta.dati)
    attesi = metadati.diagnosi(copia)
    assert attesi and all(motivo == "c'è" for _, motivo in attesi)
    assert rileggi_date.perche(pronta.archivio) == [
        {"tipo": ".jpg", "motivi": attesi, "quanti": 1}]


def _si_chiude_mentre_guarda(pronta, monkeypatch) -> None:
    vera = metadati.diagnosi

    def prima_si_chiude(percorso):
        _chiudi(pronta)
        return vera(percorso)

    monkeypatch.setattr(metadati, "diagnosi", prima_si_chiude)


def _persa(pronta, monkeypatch) -> None:
    _stacca(pronta.casa)
    _rovina(pronta.casa, pronta.relativo)


PERCHE_NELL_ARCHIVIO = {
    "chiuso": (lambda pronta, _: _chiudi(pronta), "?", rileggi_date.NEL_SICURO_CHIUSO),
    "diversa": (lambda pronta, _: _diversa(pronta), "?", rileggi_date.NEL_SICURO_DIVERSO),
    "persa": (_persa, ".jpg", rileggi_date.NEL_SICURO_ROVINATO),
    "si_chiude": (_si_chiude_mentre_guarda, ".jpg", rileggi_date.NEL_SICURO_CHIUSO),
}


@pytest.mark.parametrize("come", sorted(PERCHE_NELL_ARCHIVIO))
def test_perche_manca_la_data_dice_cosa_succede_nell_archivio(scheda_nell_archivio,
                                                              monkeypatch, come):
    pronta = scheda_nell_archivio
    _senza_data_e_da_sola(pronta)
    prepara, tipo, motivo = PERCHE_NELL_ARCHIVIO[come]
    prepara(pronta, monkeypatch)
    assert rileggi_date.perche(pronta.archivio) == [
        {"tipo": tipo, "motivi": [("file", motivo)], "quanti": 1}]


def test_una_foto_dell_archivio_non_prende_la_data_dal_file(foto_nell_archivio,
                                                            monkeypatch):
    trovata = _guarda(foto_nell_archivio)
    monkeypatch.setattr(metadati, "CON_LA_DATA_DEL_FILE", True)
    assert metadati.data_del_file(trovata) is None
    dati = metadati.leggi(trovata)
    assert not dati.ha_data and dati.origine_data == "assente"
    with monkeypatch.context() as cambia:
        cambia.setattr(metadati.os, "name", "nt")
        assert metadati.data_del_file(trovata) is None


@pytest.fixture
def nell_archivio(tmp_path, archivio_pieno, monkeypatch):
    fatte: list = []

    def metti(relativo: str, dati: bytes):
        pronta = _prepara(tmp_path, archivio_pieno, monkeypatch, relativo, dati,
                          "immagine", "jpeg")
        fatte.append(pronta)
        return pronta

    yield metti
    for pronta in fatte:
        pronta.casa.chiudi()


def _con_la_spia(trovata: DallArchivio) -> tuple[DallArchivio, list]:
    aperti: list = []

    def spia(questa):
        flusso = trovata._prendi(questa)
        aperti.append(weakref.ref(flusso))
        return flusso

    return dataclasses.replace(trovata, _prendi=spia), aperti


NON_E_UNA_FOTO = b"non sono una foto " * 64


@pytest.mark.parametrize("nome, dentro, codice", [
    ("s/foto.dat", "foto", None),
    ("s/foto.dat", "altro", "non_supportato"),
    ("s/finta.jpg", "altro", "estensione_bugiarda"),
])
def test_un_file_che_non_si_apre_richiude_quello_che_ha_preso_dall_archivio(
        nell_archivio, nome, dentro, codice):
    dati = dall_archivio_di_prova._jpeg() if dentro == "foto" else NON_E_UNA_FOTO
    pronta = nell_archivio(nome, dati)
    trovata, aperti = _con_la_spia(_guarda(pronta))
    if codice is None:
        assert metadati.leggi(trovata).larghezza == 96
    else:
        assert _codice(lambda: metadati.leggi(trovata)) == codice
        assert _codice(lambda: lettura.intestazione(trovata)) == "estensione_bugiarda"
    assert aperti and all(flusso() is None or flusso().closed for flusso in aperti)
    assert trovata.guasto is None


def _si_prende(serratura) -> bool:
    presa: list = []

    def prova() -> None:
        if serratura.acquire(timeout=5):
            serratura.release()
            presa.append(True)

    filo = threading.Thread(target=prova)
    filo.start()
    filo.join()
    return bool(presa)


class _DopoLApertura:

    def __init__(self, collegamento):
        self.collegamento = collegamento
        self.libere: list[bool] = []
        for funzione in (self.conta, self.rotta, self.conta):
            collegamento.quando_si_apre(funzione)

    def conta(self) -> None:
        self.libere.append(_si_prende(self.collegamento._serratura))

    def rotta(self) -> None:
        raise RuntimeError("si è rotta")


def _rotture(rotti: list) -> list:
    return [nome for nome, _ in rotti]


def test_aperto_da_solo_ogni_ripasso_riparte_una_volta_fuori_dalla_serratura(posto,
                                                                             monkeypatch):
    rotti = _errori(monkeypatch)
    posto.crea()
    collegamento = posto.riparti()
    dopo = _DopoLApertura(collegamento)
    assert collegamento.apri_in_sottofondo(PAROLA) == archivio_sicuro.SI_APRE
    assert nel_programma._aspetta(collegamento) == archivio_sicuro.APERTO
    assert dopo.libere == [True]
    assert _rotture(rotti) == ["sicuro.dopo_l_apertura_rotto"]
    assert collegamento.apri_in_sottofondo(PAROLA) == archivio_sicuro.APERTO
    assert collegamento.apri_con_la_password(PAROLA, None) == []
    assert dopo.libere == [True] and len(rotti) == 1


def test_aperto_a_mano_ogni_ripasso_riparte_e_con_la_password_sbagliata_no(posto,
                                                                           monkeypatch):
    rotti = _errori(monkeypatch)
    posto.crea()
    collegamento = posto.riparti()
    dopo = _DopoLApertura(collegamento)
    with pytest.raises(PasswordSbagliata):
        collegamento.apri_con_la_password("una password che non apre", None)
    assert dopo.libere == [] and rotti == []
    assert collegamento.apri_con_la_password(PAROLA, None) == []
    assert collegamento.guarda() == archivio_sicuro.APERTO
    assert dopo.libere == [True]
    assert _rotture(rotti) == ["sicuro.dopo_l_apertura_rotto"]


def test_aperto_mentre_si_chiude_non_fa_ripartire_niente(posto, monkeypatch):
    posto.crea()
    collegamento = posto.riparti()
    dopo = _DopoLApertura(collegamento)
    servizio = collegamento.servizio
    vera = servizio.apri

    def e_intanto_si_chiude(*argomenti, **chiavi):
        vera(*argomenti, **chiavi)
        collegamento._finito = True

    monkeypatch.setattr(servizio, "apri", e_intanto_si_chiude)
    assert collegamento.apri_in_sottofondo(PAROLA) == archivio_sicuro.SI_APRE
    collegamento._aspetta_l_apertura(ATTESA)
    assert not collegamento._apre() and not servizio.aperto
    assert collegamento.stato == archivio_sicuro.CHIUSO and dopo.libere == []


RIPASSI = ("raddrizza_i_video_in_sottofondo", "rileggi_le_date_in_sottofondo",
           "rileggi_le_macchine_in_sottofondo")


def _ripassi(cambia, rotto: str | None = None) -> tuple[object, list]:
    from officina.archivio import accesso
    from officina.web.strade import importazione

    archivio, partiti = object(), []

    def ripasso_finto(nome: str):
        def parti(dove) -> None:
            partiti.append((nome, dove))
            if nome == rotto:
                raise RuntimeError("non riparte")

        return parti

    cambia.setattr(accesso, "aperto", lambda: archivio)
    for nome in RIPASSI:
        cambia.setattr(importazione, nome, ripasso_finto(nome))
    return archivio, partiti


def test_il_programma_fa_ripartire_i_ripassi_quando_l_archivio_si_apre(casa, monkeypatch):
    from officina.web.strade import comune

    programma, _ = finestre._programma()
    try:
        collegamento = programma._il_sicuro()
        assert programma._il_sicuro() is collegamento
        assert collegamento._dopo_l_apertura == [programma._ripassi_dopo_l_apertura]
        with monkeypatch.context() as cambia:
            archivio, partiti = _ripassi(cambia)
            cambia.setattr(comune, "gia_ripreso", False)
            collegamento._aperto_adesso()
            assert partiti == []
            cambia.setattr(comune, "gia_ripreso", True)
            collegamento._aperto_adesso()
            assert partiti == [(nome, archivio) for nome in RIPASSI]
    finally:
        finestre._chiudi_davvero(programma)


def test_se_un_ripasso_non_riparte_gli_altri_partono_lo_stesso(casa, monkeypatch):
    from officina.archivio import accesso
    from officina.errori import ArchivioChiuso
    from officina.web.strade import comune

    rotti = _errori(monkeypatch)
    programma, _ = finestre._programma()
    try:
        with monkeypatch.context() as cambia:
            cambia.setattr(comune, "gia_ripreso", True)
            archivio, partiti = _ripassi(cambia, rotto=RIPASSI[0])
            programma._ripassi_dopo_l_apertura()
            assert partiti == [(nome, archivio) for nome in RIPASSI]
            assert _rotture(rotti) == ["programma.ripassi_non_ripartiti"]

            def chiuso():
                raise ArchivioChiuso("L'archivio non è aperto.")

            cambia.setattr(accesso, "aperto", chiuso)
            partiti.clear()
            programma._ripassi_dopo_l_apertura()
            assert partiti == [] and len(rotti) == 1
    finally:
        finestre._chiudi_davvero(programma)


IN_FILA_DI_PROVA = "SELECT id FROM file_media WHERE id > ? AND id <= ? ORDER BY id LIMIT ?"
RIPRESI_DI_PROVA = ("SELECT id FROM file_media WHERE id IN (SELECT value FROM json_each(?)) "
                    "ORDER BY id")


def _primi(archivio, quanti: int) -> list[int]:
    with archivio.lettura() as connessione:
        return [riga["id"] for riga in tutti(
            connessione, "SELECT id FROM file_media ORDER BY id LIMIT ?", quanti)]


def _passa(archivio, fai, basta=lambda: False):
    return ripasso.passa(archivio, fino_a="prova_fino_a", da="prova_da",
                         lasciati="prova_lasciati", in_fila=IN_FILA_DI_PROVA,
                         ripresi=RIPRESI_DI_PROVA, fai=fai,
                         avviso="prova.non_letto", basta=basta, a_gruppi=2)


def test_i_rimandati_sono_solo_numeri_interi(archivio_pieno):
    archivio_pieno.salva_stato("prova_lasciati", [3, True, "4", 3, 2.0, 1, None])
    assert ripasso.rimandati(archivio_pieno, "prova_lasciati") == [1, 3]
    archivio_pieno.salva_stato("prova_lasciati", [True, 7])
    assert ripasso.rimandati(archivio_pieno, "prova_lasciati") == [7]
    for strano in (5, "testo", {"1": 1}):
        archivio_pieno.salva_stato("prova_lasciati", strano)
        assert ripasso.rimandati(archivio_pieno, "prova_lasciati") == []
    assert ripasso.rimandati(archivio_pieno, "prova_che_non_c_e") == []


def test_un_rimandato_si_riprova_in_fondo_e_quelli_spariti_si_lasciano(archivio_pieno):
    primo, secondo, terzo = _primi(archivio_pieno, 3)
    archivio_pieno.salva_stato("prova_fino_a", terzo)
    archivio_pieno.salva_stato("prova_lasciati", [10 ** 9])
    visti: list = []

    def fai(riga) -> bool:
        visti.append(riga["id"])
        if riga["id"] == secondo and visti.count(secondo) == 1:
            raise DaRifare("chiuso", codice=CHIUSO_ADESSO)
        return True

    esito = _passa(archivio_pieno, fai)
    assert visti == [primo, secondo, terzo, secondo]
    assert (esito.fatti, esito.rimandati, esito.fermato) == (3, 0, False)
    assert ripasso.rimandati(archivio_pieno, "prova_lasciati") == []
    assert archivio_pieno.stato("prova_da") == terzo


def test_un_rimandato_che_si_rompe_davvero_non_si_riprova_piu(archivio_pieno, monkeypatch):
    primo, = _primi(archivio_pieno, 1)
    for chiave in ("prova_fino_a", "prova_da"):
        archivio_pieno.salva_stato(chiave, primo)
    archivio_pieno.salva_stato("prova_lasciati", [primo])
    detti = _avvisi(monkeypatch)

    def fai(riga) -> bool:
        raise ValueError("rotto")

    esito = _passa(archivio_pieno, fai)
    assert esito.rimandati == 0 and esito.fatti == 0
    assert detti == [("prova.non_letto", {})]
    assert ripasso.rimandati(archivio_pieno, "prova_lasciati") == []


def test_il_ripasso_si_ferma_anche_mentre_riprova_i_rimandati(archivio_pieno):
    primo, secondo = _primi(archivio_pieno, 2)
    for chiave in ("prova_fino_a", "prova_da"):
        archivio_pieno.salva_stato(chiave, secondo)
    archivio_pieno.salva_stato("prova_lasciati", [primo, secondo])
    visti: list = []
    esito = _passa(archivio_pieno, lambda riga: visti.append(riga["id"]) or True,
                   basta=lambda: bool(visti))
    assert visti == [primo] and esito.fermato
    assert esito.fatti == 1 and esito.rimandati == 1
    assert ripasso.rimandati(archivio_pieno, "prova_lasciati") == [secondo]


def test_un_da_rifare_che_arriva_da_dentro_passa_com_e():
    trovata = DallArchivio("ab" * 16, "a.jpg", 1, "0" * 64, True, False, lambda _: None)
    gia = da_rifare(CHIUSO_ADESSO)
    with pytest.raises(DaRifare) as preso:
        with attento(trovata):
            trovata.segna_guasto(PERSA)
            raise gia
    assert preso.value is gia
