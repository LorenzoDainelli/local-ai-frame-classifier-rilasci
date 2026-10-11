from __future__ import annotations

import random

import pytest

from officina.modello import etichette, nodi, scatti
from officina.modello.scatti import Filtro


def _il_modo_ottuso(connessione, filtro: Filtro) -> dict[int, int]:
    return {riga["id"]: scatti.conta(connessione, filtro.con_nodo(riga["id"], "e"))
            for riga in nodi.elenco(connessione)}


@pytest.fixture
def albero_e_foto(archivio):
    caso = random.Random(920)
    with archivio.scrittura() as c:
        radici = [nodi.crea(c, "radice_%d" % n) for n in range(3)]
        figli = []
        for quale, radice in enumerate(radici):
            for n in range(3):
                figli.append(nodi.crea(c, "figlio_%d_%d" % (quale, n),
                                       genitore_id=radice))
        nipoti = [nodi.crea(c, "nipote_%d" % n, genitore_id=figli[n % len(figli)])
                  for n in range(6)]
        tutti_i_nodi = radici + figli + nipoti

        numeri = []
        for i in range(120):
            numeri.append(c.execute(
                "INSERT INTO scatti (genere, giorno, fuori_archivio, creato_il) "
                "VALUES (?, ?, ?, '2026-01-01T00:00:00')",
                ("video" if i % 7 == 0 else "foto",
                 "2024-%02d-%02d" % (1 + i % 12, 1 + i % 28),
                 1 if i % 23 == 0 else 0)).lastrowid)
        for scatto_id in numeri:
            for _ in range(caso.randrange(0, 4)):
                etichette.metti(c, scatto_id, caso.choice(tutti_i_nodi), "si")
    return archivio, tutti_i_nodi


I_FILTRI = [
    ("nessun filtro", {}),
    ("un genere", {"genere": "foto"}),
    ("un intervallo di giorni", {"dal": "2024-03-01", "al": "2024-08-31"}),
    ("fuori archivio", {"fuori_archivio": True}),
    ("senza etichetta", {"senza_etichetta": True}),
    ("col ramo spento", {"ramo": False}),
]


@pytest.mark.parametrize("nome,cosa", I_FILTRI, ids=[n for n, _ in I_FILTRI])
def test_il_conto_svelto_dice_gli_stessi_numeri_di_quello_ottuso(
        albero_e_foto, nome, cosa):
    archivio, _ = albero_e_foto
    filtro = Filtro(**cosa)
    with archivio.lettura() as c:
        lento = _il_modo_ottuso(c, filtro)
        svelto = scatti.conteggi_dei_nodi(c, filtro)
    assert svelto == lento, f"i due conti non combaciano con «{nome}»"
    if nome not in ("senza etichetta",):
        assert max(svelto.values()) > 0, (
            f"con «{nome}» non è rimasto niente da contare: la prova passa "
            "ma non prova nulla")


def test_combaciano_anche_con_un_nodo_gia_attivo(albero_e_foto):
    archivio, tutti_i_nodi = albero_e_foto
    for quale in (tutti_i_nodi[0], tutti_i_nodi[5], tutti_i_nodi[-1]):
        filtro = Filtro(nodi_e=[quale])
        with archivio.lettura() as c:
            assert scatti.conteggi_dei_nodi(c, filtro) == _il_modo_ottuso(c, filtro)


def test_un_nodo_gia_nel_filtro_si_conta_da_solo(albero_e_foto):
    archivio, tutti_i_nodi = albero_e_foto
    quale = tutti_i_nodi[0]
    filtro = Filtro(nodi_e=[quale])
    with archivio.lettura() as c:
        quanti_adesso = scatti.conta(c, filtro)
        assert scatti.conteggi_dei_nodi(c, filtro)[quale] == quanti_adesso


def test_un_ramo_conta_i_suoi_scatti_una_volta_sola(archivio):
    with archivio.scrittura() as c:
        radice = nodi.crea(c, "vestiti")
        figlio = nodi.crea(c, "magliette", genitore_id=radice)
        nipote = nodi.crea(c, "tommy", genitore_id=figlio)
        scatto_id = c.execute(
            "INSERT INTO scatti (genere, creato_il) "
            "VALUES ('foto', '2026-01-01T00:00:00')").lastrowid
        for quale in (radice, figlio, nipote):
            etichette.metti(c, scatto_id, quale, "si")

    with archivio.lettura() as c:
        conteggi = scatti.conteggi_dei_nodi(c, Filtro())
    assert conteggi[radice] == 1, "lo stesso scatto contato una volta per etichetta"
    assert conteggi[figlio] == 1
    assert conteggi[nipote] == 1


@pytest.fixture
def gente_e_posti(archivio):
    import random

    from officina.modello import persone

    caso = random.Random(7788)
    with archivio.scrittura() as c:
        chi = [persone.crea(c, "persona_%d" % n) for n in range(5)]
        from officina.modello import posti

        cima = posti.crea(c, "posto_cima")
        dove = [posti.crea(c, "posto_%d" % n, cima if n else None) for n in range(4)]
        numeri = []
        for i in range(80):
            numeri.append(c.execute(
                "INSERT INTO scatti (genere, fuori_archivio, giorno, "
                "creato_il) VALUES (?, ?, ?, '2026-01-01T00:00:00')",
                ("video" if i % 9 == 0 else "foto",
                 1 if i % 17 == 0 else 0,
                 "2024-%02d-15" % (1 + i % 12))).lastrowid)
            posto = caso.choice(dove + [None])
            if posto is not None:
                c.execute("INSERT INTO posti_negli_scatti (scatto_id, posto_id, messo_il) "
                          "VALUES (?, ?, '2026-01-01T00:00:00')", (numeri[-1], posto))
        for scatto_id in numeri:
            for _ in range(caso.randrange(0, 3)):
                c.execute(
                    "INSERT INTO volti (scatto_id, persona_id, riquadro, area, "
                    "nitidezza, sicurezza, modello, versione, trovato_il) "
                    "VALUES (?, ?, '[0,0,0.2,0.2]', 0.04, 1.0, 0.9, 'finto', "
                    "'1', '2026-01-01T00:00:00')",
                    (scatto_id, caso.choice(chi)))
            if caso.random() < 0.3:
                persone.metti_a_mano(c, scatto_id, caso.choice(chi))
    return archivio, chi, dove


I_FILTRI_GENTE = [
    ("nessun filtro", {}),
    ("un genere", {"genere": "foto"}),
    ("un intervallo", {"dal": "2024-04-01", "al": "2024-09-30"}),
    ("fuori archivio", {"fuori_archivio": True}),
]


@pytest.mark.parametrize("nome,cosa", I_FILTRI_GENTE,
                         ids=[n for n, _ in I_FILTRI_GENTE])
def test_i_numeri_delle_persone_combaciano(gente_e_posti, nome, cosa):
    from officina.modello import persone

    archivio, chi, _ = gente_e_posti
    filtro = Filtro(**cosa)
    with archivio.lettura() as c:
        lento = {riga["id"]: scatti.conta(
                     c, filtro.copia_con(persone=filtro.persone + [riga["id"]]))
                 for riga in persone.elenco(c)}
        svelto = scatti.conteggi_delle_persone(c, filtro)
    assert svelto == lento, f"i due conti non combaciano con «{nome}»"
    if nome != "fuori archivio":
        assert max(svelto.values()) > 0, "non è rimasto niente da contare"


def test_i_numeri_delle_persone_combaciano_con_una_gia_scelta(gente_e_posti):
    from officina.modello import persone

    archivio, chi, _ = gente_e_posti
    filtro = Filtro(persone=[chi[0]])
    with archivio.lettura() as c:
        svelto = scatti.conteggi_delle_persone(c, filtro)
        for riga in persone.elenco(c):
            if riga["id"] in filtro.persone:
                atteso = scatti.conta(c, filtro)
            else:
                atteso = scatti.conta(
                    c, filtro.copia_con(persone=filtro.persone + [riga["id"]]))
            assert svelto[riga["id"]] == atteso


@pytest.mark.parametrize("nome,cosa", I_FILTRI_GENTE,
                         ids=[n for n, _ in I_FILTRI_GENTE])
def test_i_numeri_dei_luoghi_combaciano(gente_e_posti, nome, cosa):
    from officina.modello import posti

    archivio, _, dove = gente_e_posti
    filtro = Filtro(**cosa)
    with archivio.lettura() as c:
        lento = {riga["id"]: scatti.conta(c, filtro.copia_con(luogo=riga["id"]))
                 for riga in posti.attivi(c)}
        svelto = scatti.conteggi_dei_luoghi(c, filtro)
    assert svelto == lento, f"i due conti non combaciano con «{nome}»"


def test_un_luogo_sostituisce_l_altro_e_il_numero_lo_dice(gente_e_posti):
    from officina.modello import posti

    archivio, _, dove = gente_e_posti
    filtro = Filtro(luogo=dove[0])
    with archivio.lettura() as c:
        svelto = scatti.conteggi_dei_luoghi(c, filtro)
        for riga in posti.attivi(c):
            assert svelto[riga["id"]] == scatti.conta(
                c, filtro.copia_con(luogo=riga["id"]))
    assert sum(1 for quanti in svelto.values() if quanti > 0) > 1, (
        "solo il posto dove sei ha un numero: il conto si sta facendo col "
        "luogo già dentro")


def _quante_domande(connessione, cosa) -> int:
    quante = 0

    def segna(_):
        nonlocal quante
        quante += 1

    connessione.set_trace_callback(segna)
    try:
        cosa()
    finally:
        connessione.set_trace_callback(None)
    return quante


def test_i_numeri_dei_nodi_non_costano_una_domanda_per_nodo(albero_e_foto):
    archivio, tutti_i_nodi = albero_e_foto
    with archivio.lettura() as c:
        piccolo = _quante_domande(
            c, lambda: scatti.conteggi_dei_nodi(c, Filtro()))

    with archivio.scrittura() as c:
        for n in range(len(tutti_i_nodi) * 2):
            nodi.crea(c, "nodo_in_piu_%d" % n)

    with archivio.lettura() as c:
        grande = _quante_domande(
            c, lambda: scatti.conteggi_dei_nodi(c, Filtro()))

    assert grande == piccolo, (
        f"con tre volte i nodi il conto fa {grande} domande invece di "
        f"{piccolo}: sta tornando a chiederne una per nodo")
    assert piccolo <= 6, (
        f"{piccolo} domande per una colonna di filtri sono già troppe")


def test_le_righe_del_ripasso_non_costano_una_domanda_per_domanda(albero_e_foto):
    from officina.modello import etichette, ripassi

    archivio, tutti_i_nodi = albero_e_foto
    with archivio.lettura() as c:
        uno_scatto = uno_qualunque(c)
    with archivio.scrittura() as c:
        etichette.metti(c, uno_scatto, tutti_i_nodi[0], "si")

    with archivio.lettura() as c:
        piccolo = _quante_domande(c, lambda: ripassi.da_chiedere(c))

    with archivio.scrittura() as c:
        for n in range(len(tutti_i_nodi) * 3):
            nodi.crea(c, "altro_nodo_%d" % n)

    with archivio.lettura() as c:
        grande = _quante_domande(c, lambda: ripassi.da_chiedere(c))

    assert grande <= piccolo + 1, (
        f"con quattro volte le domande aperte il ripasso ne fa {grande} "
        f"invece di {piccolo}: sta tornando a chiederne una per nodo")


def uno_qualunque(connessione) -> int:
    from officina.archivio.database import uno

    return uno(connessione, "SELECT id FROM scatti ORDER BY id LIMIT 1")["id"]
