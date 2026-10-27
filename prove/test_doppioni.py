from __future__ import annotations

import io

import pytest

from officina.archivio.database import uno
from officina.doppioni import motore, occhio

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402


def _disegno(seme: int, larghezza: int = 480, altezza: int = 360) -> Image.Image:
    import random

    caso = random.Random(seme)
    tela = Image.new("RGB", (larghezza, altezza), (20, 20, 30))
    pennello = ImageDraw.Draw(tela)
    for _ in range(14):
        x = caso.randrange(larghezza)
        y = caso.randrange(altezza)
        lato = caso.randrange(30, 160)
        colore = (caso.randrange(256), caso.randrange(256), caso.randrange(256))
        pennello.ellipse([x, y, x + lato, y + lato], fill=colore)
    return tela


def _ricompressa(immagine: Image.Image, qualita: int = 30) -> Image.Image:
    dentro = io.BytesIO()
    immagine.save(dentro, "JPEG", quality=qualita)
    dentro.seek(0)
    return Image.open(dentro).convert("RGB")


def test_la_ricompressione_non_cambia_l_impronta():
    originale = _disegno(1)
    assert occhio.dell_immagine(originale) == occhio.dell_immagine(
        _ricompressa(originale))


def test_rimpicciolire_non_cambia_l_impronta():
    originale = _disegno(2)
    piccola = originale.resize((240, 180), Image.Resampling.LANCZOS)
    assert occhio.distanza(
        occhio.dell_immagine(originale), occhio.dell_immagine(piccola)) <= 1


def test_due_fotografie_diverse_hanno_impronte_lontane():
    lontane = [
        occhio.distanza(occhio.dell_immagine(_disegno(quale)),
                        occhio.dell_immagine(_disegno(quale + 100)))
        for quale in range(1, 12)
    ]
    assert min(lontane) > occhio.QUASI_UGUALI


def test_l_impronta_e_sempre_lunga_uguale():
    for quale in range(30):
        segno = occhio.dell_immagine(_disegno(quale))
        assert len(segno) == occhio.QUANTI_BIT // 4
    piatta = Image.new("RGB", (100, 100), (128, 128, 128))
    assert occhio.dell_immagine(piatta) == "0" * (occhio.QUANTI_BIT // 4)


def test_la_distanza_di_una_con_se_stessa_e_zero():
    segno = occhio.dell_immagine(_disegno(7))
    assert occhio.distanza(segno, segno) == 0


def _metti(archivio, quale: int, segno: str, dimensione: int) -> int:
    with archivio.scrittura() as connessione:
        cursore = connessione.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, "
            "impronta_occhio, aggiunto_il) VALUES (?, ?, 'immagine', ?, "
            "'2026-01-01T00:00:00')",
            ("byte-%d" % quale, dimensione, segno))
        return int(cursore.lastrowid)


def test_due_copie_della_stessa_foto_finiscono_in_un_gruppo(archivio):
    segno = occhio.dell_immagine(_disegno(3))
    grande = _metti(archivio, 1, segno, 4_000_000)
    piccola = _metti(archivio, 2, segno, 180_000)
    _metti(archivio, 3, occhio.dell_immagine(_disegno(300)), 3_000_000)

    fatti = motore.gruppi(archivio)

    assert len(fatti) == 1
    assert set(fatti[0].file_id) == {grande, piccola}
    assert fatti[0].identiche


def test_il_piu_grande_e_il_primo(archivio):
    segno = occhio.dell_immagine(_disegno(4))
    piccola = _metti(archivio, 1, segno, 90_000)
    grande = _metti(archivio, 2, segno, 5_000_000)

    fatti = motore.gruppi(archivio)

    assert fatti[0].file_id[0] == grande
    assert fatti[0].file_id[1] == piccola


def test_tre_copie_di_qualita_calante_restano_un_gruppo_solo(archivio):
    principio = int(occhio.dell_immagine(_disegno(5)), 16)
    quante_cifre = occhio.QUANTI_BIT // 4
    uno = format(principio, "0%dx" % quante_cifre)
    due = format(principio ^ 0b1111, "0%dx" % quante_cifre)
    tre = format(principio ^ 0b11111111, "0%dx" % quante_cifre)
    assert occhio.distanza(uno, tre) > occhio.QUASI_UGUALI

    a = _metti(archivio, 1, uno, 3_000_000)
    b = _metti(archivio, 2, due, 2_000_000)
    c = _metti(archivio, 3, tre, 1_000_000)

    fatti = motore.gruppi(archivio)

    assert len(fatti) == 1
    assert set(fatti[0].file_id) == {a, b, c}
    assert not fatti[0].identiche


def test_due_fotografie_lontane_non_fanno_gruppo(archivio):
    _metti(archivio, 1, occhio.dell_immagine(_disegno(6)), 1_000_000)
    _metti(archivio, 2, occhio.dell_immagine(_disegno(600)), 1_000_000)
    assert motore.gruppi(archivio) == []


def test_chi_non_e_stato_guardato_non_somiglia_a_niente(archivio):
    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, "
            "impronta_occhio, aggiunto_il) VALUES ('a', 1, 'immagine', NULL, "
            "'2026-01-01T00:00:00')")
        connessione.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, "
            "impronta_occhio, aggiunto_il) VALUES ('b', 1, 'immagine', NULL, "
            "'2026-01-01T00:00:00')")
        connessione.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, "
            "impronta_occhio, aggiunto_il) VALUES ('c', 1, 'immagine', '', "
            "'2026-01-01T00:00:00')")
        connessione.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, "
            "impronta_occhio, aggiunto_il) VALUES ('d', 1, 'immagine', '', "
            "'2026-01-01T00:00:00')")

    assert motore.gruppi(archivio) == []


def test_il_taglio_in_pezzi_non_perde_nessuna_coppia(archivio):
    quante_cifre = occhio.QUANTI_BIT // 4
    attesi = 0
    for quanti_bit in range(1, occhio.QUASI_UGUALI + 1):
        maschera = 0
        for quale in range(quanti_bit):
            maschera |= 1 << (quale * 11)
        base = int(occhio.dell_immagine(_disegno(50 + quanti_bit * 7)), 16)
        _metti(archivio, quanti_bit * 2, format(base, "0%dx" % quante_cifre),
               1_000_000)
        _metti(archivio, quanti_bit * 2 + 1,
               format(base ^ maschera, "0%dx" % quante_cifre), 500_000)
        attesi += 1

    fatti = motore.gruppi(archivio)

    assert len(fatti) == attesi, (
        "il taglio in pezzi ha perso delle coppie: trovati %d gruppi su %d"
        % (len(fatti), attesi))
    assert all(gruppo.quante == 2 for gruppo in fatti)


def test_il_taglio_non_perde_niente_nemmeno_a_caso():
    import random

    caso = random.Random(1789)
    numeri = {}
    for quale in range(1000):
        numeri[quale] = caso.getrandbits(occhio.QUANTI_BIT)
    for quanti_bit in range(1, occhio.QUASI_UGUALI + 1):
        for copia in range(20):
            quale = caso.randrange(1000)
            sporco = 0
            for posto in caso.sample(range(occhio.QUANTI_BIT), quanti_bit):
                sporco |= 1 << posto
            numeri[10_000 + quanti_bit * 100 + copia] = numeri[quale] ^ sporco

    dal_taglio = motore._coppie_possibili(numeri)

    quali = sorted(numeri)
    perse = []
    for posto, questo in enumerate(quali):
        for altro in quali[posto + 1:]:
            if occhio.distanza_fra_numeri(numeri[questo],
                                          numeri[altro]) > occhio.QUASI_UGUALI:
                continue
            if (questo, altro) not in dal_taglio:
                perse.append((questo, altro))

    assert not perse, (
        "il taglio in %d pezzi ha perso %d coppie vere: non è un conto "
        "veloce, è un conto sbagliato" % (motore.QUANTI_PEZZI, len(perse)))


def test_i_pezzi_coprono_l_impronta_intera_e_sono_lunghi_uguali():
    tagli = motore._tagli()
    assert len(tagli) == motore.QUANTI_PEZZI
    assert sum(lungo for _, lungo in tagli) == occhio.QUANTI_BIT
    assert max(lungo for _, lungo in tagli) - min(lungo for _, lungo in tagli) <= 1
    atteso = 0
    for da, lungo in tagli:
        assert da == atteso
        atteso += lungo


def test_l_importazione_lascia_le_immagini_gia_guardate(archivio_pieno):
    passata = motore.Passata(archivio_pieno)
    assert passata.quante_mancano() == 0

    with archivio_pieno.lettura() as connessione:
        quante = connessione.execute(
            "SELECT COUNT(*) AS q FROM file_media WHERE genere = 'immagine' "
            "AND impronta_occhio IS NOT NULL AND impronta_occhio != ''"
        ).fetchone()["q"]
    assert quante > 0


def test_i_video_non_hanno_questa_impronta_e_non_la_aspettano(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        senza = connessione.execute(
            "SELECT COUNT(*) AS q FROM file_media WHERE genere = 'video' "
            "AND impronta_occhio IS NOT NULL"
        ).fetchone()["q"]
    assert senza == 0
    assert motore.Passata(archivio_pieno).quante_mancano() == 0


def test_la_passata_riempie_quelle_che_mancano_e_poi_ha_finito(archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        connessione.execute(
            "UPDATE file_media SET impronta_occhio = NULL "
            "WHERE genere = 'immagine'")

    passata = motore.Passata(archivio_pieno)
    mancavano = passata.quante_mancano()
    assert mancavano > 0

    avanzamento = passata.esegui()

    assert avanzamento.guardate + avanzamento.saltate == mancavano
    assert avanzamento.resta == 0
    assert motore.Passata(archivio_pieno).quante_mancano() == 0


def test_si_puo_fermare_a_meta_e_riprende_da_dove_era(archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        connessione.execute(
            "UPDATE file_media SET impronta_occhio = NULL "
            "WHERE genere = 'immagine'")

    tutte = motore.Passata(archivio_pieno).quante_mancano()
    assert tutte >= 4

    prima = motore.Passata(archivio_pieno)
    prima.esegui(quante_al_massimo=2)
    assert motore.Passata(archivio_pieno).quante_mancano() == tutte - 2

    dopo = motore.Passata(archivio_pieno)
    dopo.esegui()
    assert motore.Passata(archivio_pieno).quante_mancano() == 0


def test_un_file_che_non_si_apre_non_viene_riprovato_per_sempre(archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        riga = connessione.execute(
            "SELECT f.id, MIN(p.id) AS percorso_id FROM file_media AS f "
            "JOIN percorsi AS p ON p.file_id = f.id AND p.presente = 1 "
            "WHERE f.genere = 'immagine' GROUP BY f.id LIMIT 1").fetchone()
        connessione.execute(
            "UPDATE file_media SET impronta_occhio = NULL WHERE id = ?",
            (riga["id"],))
        connessione.execute(
            "UPDATE percorsi SET percorso = percorso || '.andato' WHERE file_id = ?",
            (riga["id"],))

    avanzamento = motore.Passata(archivio_pieno).esegui()

    assert avanzamento.saltate == 1
    assert avanzamento.motivi_saltate
    assert motore.Passata(archivio_pieno).quante_mancano() == 0


def _con_scatto(archivio, quale: int, segno: str, dimensione: int) -> tuple[int, int]:
    with archivio.scrittura() as connessione:
        scatto = connessione.execute(
            "INSERT INTO scatti (genere, creato_il) VALUES ('foto', "
            "'2026-01-01T00:00:00')")
        scatto_id = int(scatto.lastrowid)
        file = connessione.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, "
            "impronta_occhio, scatto_id, ruolo, aggiunto_il) "
            "VALUES (?, ?, 'immagine', ?, ?, 'principale', "
            "'2026-01-01T00:00:00')",
            ("byte-%d" % quale, dimensione, segno, scatto_id))
        return int(file.lastrowid), scatto_id


def _una_coppia(archivio, seme: int = 71):
    from officina.doppioni import decisioni

    segno = occhio.dell_immagine(_disegno(seme))
    grande = _con_scatto(archivio, 1, segno, 4_100_000)
    piccola = _con_scatto(archivio, 2, segno, 180_000)
    decisioni.conta_e_scrivi(archivio)
    with archivio.lettura() as connessione:
        gruppo = decisioni.da_decidere(connessione)[0]
    return gruppo, grande, piccola


def test_la_firma_non_dipende_dall_ordine(archivio):
    from officina.doppioni import decisioni

    assert decisioni.firma([7, 3, 11]) == decisioni.firma([11, 7, 3])


def test_mai_contato_non_e_la_stessa_cosa_di_nessun_doppione(archivio):
    from officina.doppioni import decisioni

    with archivio.lettura() as connessione:
        assert decisioni.mai_contato(connessione)

    _con_scatto(archivio, 1, occhio.dell_immagine(_disegno(8)), 1_000_000)
    decisioni.conta_e_scrivi(archivio)

    with archivio.lettura() as connessione:
        assert decisioni.il_conto(connessione)["totale"] == 0
        assert not decisioni.mai_contato(connessione)
        assert decisioni.quando_contato(connessione)


def test_il_conto_scende_quando_si_decide(archivio):
    from officina.doppioni import decisioni

    gruppo, grande, _ = _una_coppia(archivio)
    with archivio.lettura() as connessione:
        assert decisioni.il_conto(connessione) == {
            "totale": 1, "decisi": 0, "restano": 1}

    decisioni.tieni(archivio, gruppo["firma"], grande[0])

    with archivio.lettura() as connessione:
        assert decisioni.il_conto(connessione) == {
            "totale": 1, "decisi": 1, "restano": 0}
        assert decisioni.da_decidere(connessione) == []


def test_tenere_una_copia_mette_le_altre_fuori_archivio_e_non_cancella(archivio):
    from officina.doppioni import decisioni

    gruppo, grande, piccola = _una_coppia(archivio, seme=72)
    esito = decisioni.tieni(archivio, gruppo["firma"], grande[0])

    assert esito["spostati"] == 1
    with archivio.lettura() as connessione:
        dentro = connessione.execute(
            "SELECT id, fuori_archivio FROM scatti ORDER BY id").fetchall()
        assert [(r["id"], r["fuori_archivio"]) for r in dentro] == [
            (grande[1], 0), (piccola[1], 1)]
        assert connessione.execute(
            "SELECT count(*) AS q FROM file_media").fetchone()["q"] == 2


def test_il_ripensamento_riporta_dentro_solo_quello_che_avevo_spostato(archivio):
    from officina.doppioni import decisioni

    segno = occhio.dell_immagine(_disegno(73))
    grande = _con_scatto(archivio, 1, segno, 4_000_000)
    media = _con_scatto(archivio, 2, segno, 900_000)
    piccola = _con_scatto(archivio, 3, segno, 120_000)
    with archivio.scrittura() as connessione:
        connessione.execute(
            "UPDATE scatti SET fuori_archivio = 1 WHERE id = ?", (piccola[1],))

    decisioni.conta_e_scrivi(archivio)
    with archivio.lettura() as connessione:
        gruppo = decisioni.da_decidere(connessione)[0]

    esito = decisioni.tieni(archivio, gruppo["firma"], grande[0])
    assert esito["spostati"] == 1

    decisioni.rimetti(archivio, gruppo["firma"])

    with archivio.lettura() as connessione:
        fuori = {r["id"]: r["fuori_archivio"] for r in connessione.execute(
            "SELECT id, fuori_archivio FROM scatti")}
    assert fuori[grande[1]] == 0
    assert fuori[media[1]] == 0
    assert fuori[piccola[1]] == 1


def test_sono_diverse_non_sposta_niente_e_non_richiede_piu(archivio):
    from officina.doppioni import decisioni

    gruppo, grande, piccola = _una_coppia(archivio, seme=74)
    decisioni.sono_diverse(archivio, gruppo["firma"])

    with archivio.lettura() as connessione:
        assert decisioni.da_decidere(connessione) == []
        fuori = connessione.execute(
            "SELECT count(*) AS q FROM scatti WHERE fuori_archivio = 1"
        ).fetchone()["q"]
    assert fuori == 0


def test_una_copia_in_piu_rifa_la_domanda(archivio):
    from officina.doppioni import decisioni

    segno = occhio.dell_immagine(_disegno(75))
    grande = _con_scatto(archivio, 1, segno, 4_000_000)
    _con_scatto(archivio, 2, segno, 180_000)
    decisioni.conta_e_scrivi(archivio)
    with archivio.lettura() as connessione:
        prima = decisioni.da_decidere(connessione)[0]
    decisioni.tieni(archivio, prima["firma"], grande[0])

    _con_scatto(archivio, 3, segno, 90_000)
    decisioni.conta_e_scrivi(archivio)

    with archivio.lettura() as connessione:
        dopo = decisioni.da_decidere(connessione)
    assert len(dopo) == 1
    assert dopo[0]["firma"] != prima["firma"]
    assert len(dopo[0]["copie"]) == 3


def test_il_bollo_solo_sui_gruppi_ancora_aperti(archivio):
    from officina.doppioni import decisioni

    gruppo, grande, piccola = _una_coppia(archivio, seme=76)
    with archivio.lettura() as connessione:
        bollate = decisioni.doppie(connessione, [grande[0], piccola[0]])
    assert set(bollate) == {grande[0], piccola[0]}
    assert bollate[grande[0]] == gruppo["firma"]

    decisioni.sono_diverse(archivio, gruppo["firma"])
    with archivio.lettura() as connessione:
        assert decisioni.doppie(connessione, [grande[0], piccola[0]]) == {}


def test_il_conto_si_rifa_da_zero_senza_toccare_le_decisioni(archivio):
    from officina.doppioni import decisioni

    gruppo, grande, _ = _una_coppia(archivio, seme=77)
    decisioni.tieni(archivio, gruppo["firma"], grande[0])

    decisioni.conta_e_scrivi(archivio)

    with archivio.lettura() as connessione:
        assert decisioni.il_conto(connessione)["decisi"] == 1
        assert decisioni.da_decidere(connessione) == []


def test_rimetti_tutto_disfa_ogni_decisione(archivio):
    from officina.doppioni import decisioni

    segno_uno = occhio.dell_immagine(_disegno(78))
    grande_uno = _con_scatto(archivio, 1, segno_uno, 4_000_000)
    _con_scatto(archivio, 2, segno_uno, 200_000)
    segno_due = occhio.dell_immagine(_disegno(790))
    grande_due = _con_scatto(archivio, 3, segno_due, 3_000_000)
    _con_scatto(archivio, 4, segno_due, 150_000)
    decisioni.conta_e_scrivi(archivio)

    with archivio.lettura() as connessione:
        gruppi = decisioni.da_decidere(connessione)
    assert len(gruppi) == 2
    for gruppo in gruppi:
        decisioni.tieni(archivio, gruppo["firma"], gruppo["copie"][0]["file_id"])

    assert decisioni.rimetti_tutto(archivio) == 2

    with archivio.lettura() as connessione:
        assert decisioni.il_conto(connessione) == {
            "totale": 2, "decisi": 0, "restano": 2}
        fuori = connessione.execute(
            "SELECT count(*) AS q FROM scatti WHERE fuori_archivio = 1"
        ).fetchone()["q"]
    assert fuori == 0
    assert grande_uno[1] and grande_due[1]


def test_decidere_due_volte_e_l_ultima_parola_non_un_errore(archivio):
    from officina.doppioni import decisioni

    gruppo, grande, piccola = _una_coppia(archivio, seme=80)
    decisioni.tieni(archivio, gruppo["firma"], grande[0])
    decisioni.sono_diverse(archivio, gruppo["firma"])

    with archivio.lettura() as connessione:
        riga = connessione.execute(
            "SELECT scelta FROM doppioni_decisi WHERE firma = ?",
            (gruppo["firma"],)).fetchone()
        fuori = {r["id"]: r["fuori_archivio"] for r in connessione.execute(
            "SELECT id, fuori_archivio FROM scatti")}
    assert riga["scelta"] == "diverse"
    assert fuori[grande[1]] == 0
    assert fuori[piccola[1]] == 0


def test_l_elenco_a_blocchi_conta_solo_quelli_da_decidere(archivio):
    from officina.doppioni import decisioni

    for quale in range(4):
        segno = occhio.dell_immagine(_disegno(900 + quale * 31))
        _con_scatto(archivio, quale * 2, segno, 4_000_000 - quale)
        _con_scatto(archivio, quale * 2 + 1, segno, 200_000)
    decisioni.conta_e_scrivi(archivio)

    with archivio.lettura() as connessione:
        tutti_i_gruppi = decisioni.da_decidere(connessione)
    assert len(tutti_i_gruppi) == 4

    decisioni.sono_diverse(archivio, tutti_i_gruppi[0]["firma"])

    with archivio.lettura() as connessione:
        restano = decisioni.da_decidere(connessione)
        secondo_blocco = decisioni.da_decidere(connessione, da=1, quanti=10)
    assert [g["firma"] for g in restano] == [g["firma"] for g in tutti_i_gruppi[1:]]
    assert [g["firma"] for g in secondo_blocco] == [g["firma"] for g in restano[1:]]


def test_un_gruppo_rimasto_in_una_copia_sola_non_blocca_il_lavoro(archivio):
    from officina.doppioni import decisioni

    segno = occhio.dell_immagine(_disegno(311))
    grande = _con_scatto(archivio, 1, segno, 4_000_000)
    piccola = _con_scatto(archivio, 2, segno, 150_000)
    decisioni.conta_e_scrivi(archivio)

    with archivio.lettura() as connessione:
        assert decisioni.il_conto(connessione)["restano"] == 1

    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM file_media WHERE id = ?", (piccola[0],))
        resta = connessione.execute(
            "SELECT count(*) AS q FROM doppioni_gruppi").fetchone()["q"]
    assert resta == 1, "la cascata deve lasciare in piedi la riga del grande"

    with archivio.lettura() as connessione:
        conto = decisioni.il_conto(connessione)
        elenco = decisioni.da_decidere(connessione)
    assert elenco == []
    assert conto == {"totale": 0, "decisi": 0, "restano": 0}
    assert grande


def test_i_gruppi_e_la_data_del_conto_sono_una_cosa_sola(archivio):
    from officina.doppioni import decisioni

    segno = occhio.dell_immagine(_disegno(407))
    _con_scatto(archivio, 1, segno, 4_000_000)
    _con_scatto(archivio, 2, segno, 150_000)

    class MiSonoSpento(Exception):
        pass

    vera = type(archivio).imposta

    def non_ce_la_faccio(self, chiave, valore):
        if chiave == decisioni.QUANDO_CONTATO:
            raise MiSonoSpento
        return vera(self, chiave, valore)

    type(archivio).imposta = non_ce_la_faccio
    try:
        with pytest.raises(MiSonoSpento):
            decisioni.conta_e_scrivi(archivio)
    finally:
        type(archivio).imposta = vera

    with archivio.lettura() as connessione:
        quante = uno(connessione,
                     "SELECT count(*) AS q FROM doppioni_gruppi")["q"]
        assert quante == 0, "i gruppi sono rimasti scritti a metà"
        assert decisioni.mai_contato(connessione), (
            "la data del conto è rimasta senza i gruppi che dovrebbe datare")


def test_dice_quante_ne_sono_arrivate_dopo_il_conto(archivio):
    from officina.doppioni import decisioni

    segno = occhio.dell_immagine(_disegno(515))
    _con_scatto(archivio, 1, segno, 3_000_000)
    _con_scatto(archivio, 2, segno, 120_000)

    with archivio.lettura() as connessione:
        assert decisioni.arrivate_dopo_il_conto(connessione) == 0

    decisioni.conta_e_scrivi(archivio)
    with archivio.lettura() as connessione:
        assert decisioni.arrivate_dopo_il_conto(connessione) == 0

    with archivio.scrittura() as connessione:
        for quale in (3, 4):
            connessione.execute(
                "INSERT INTO file_media (impronta, dimensione, genere, "
                "ruolo, aggiunto_il) VALUES (?, 1000, 'immagine', "
                "'principale', ?)",
                ("byte-nuovo-%d" % quale, adesso_dopo()))

    with archivio.lettura() as connessione:
        assert decisioni.arrivate_dopo_il_conto(connessione) == 2

    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, ruolo, "
            "aggiunto_il) VALUES ('byte-video', 1000, 'video', 'principale', ?)",
            (adesso_dopo(),))
    with archivio.lettura() as connessione:
        assert decisioni.arrivate_dopo_il_conto(connessione) == 2


def adesso_dopo() -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=5)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
