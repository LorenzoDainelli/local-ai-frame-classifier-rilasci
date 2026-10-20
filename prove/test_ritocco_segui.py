from __future__ import annotations

import os
import time
from pathlib import Path

import numpy
import pytest

from officina.archivio.database import adesso, inserisci
from officina.errori import ErroreOfficina
from officina.ritocco import filmato, maschere, segui, seguiti
from officina.web import in_disparte, lavori
from officina.web import ritocco as ritocco_web
from officina.web import seguire
from prove import sceglitore_finto

LARGA, ALTA = 160, 96
QUANTI = 20
AL_SECONDO = 10
LATO = 24


def _video(dove: Path, quanti: int = QUANTI) -> Path:
    av = pytest.importorskip("av")

    dove.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(dove), "w") as fuori:
        traccia = fuori.add_stream("libx264", rate=AL_SECONDO)
        traccia.width, traccia.height, traccia.pix_fmt = LARGA, ALTA, "yuv420p"
        for numero in range(quanti):
            tela = numpy.full((ALTA, LARGA, 3), 30, dtype=numpy.uint8)
            x = 10 + numero * 4
            tela[30:30 + LATO, x:x + LATO] = (220, 40, 40)
            quadro = av.VideoFrame.from_ndarray(tela, format="rgb24")
            for pacchetto in traccia.encode(quadro):
                fuori.mux(pacchetto)
        for pacchetto in traccia.encode():
            fuori.mux(pacchetto)
    return dove


def _quadrato(numero: int, larga: int = LARGA, alta: int = ALTA) -> bytes:
    piena = numpy.zeros((alta, larga), dtype=bool)
    x = 10 + numero * 4
    piena[30:30 + LATO, x:x + LATO] = True
    return maschere.comprimi(piena, (0, 0), larga, alta)


def _aspetta(condizione, entro: float = 15.0) -> bool:
    scadenza = time.monotonic() + entro
    while time.monotonic() < scadenza:
        if condizione():
            return True
        time.sleep(0.02)
    return condizione()


@pytest.fixture(autouse=True)
def turno_pulito():
    yield
    if lavori.turno.chi is not None:
        lavori.turno.lascia(lavori.turno.chi)


@pytest.fixture
def video(tmp_path) -> Path:
    return _video(tmp_path / "film" / "giro.mp4")


@pytest.fixture
def sam3(tmp_path) -> Path:
    dove = tmp_path / "sam3"
    dove.mkdir()
    return dove


@pytest.fixture
def strumento():
    fatti: list[ritocco_web.AlClic] = []

    def fai(come: str = "Finto") -> ritocco_web.AlClic:
        nuovo = ritocco_web.AlClic("prove.sceglitore_finto:" + come)
        fatti.append(nuovo)
        return nuovo

    yield fai
    for fatto in fatti:
        fatto.chiudi()


def test_ogni_fotogramma_si_segue_dalla_scelta_piu_vicina():
    assert segui.regioni([5], 20) == [segui.Tratto(5, 0, 19)]
    assert segui.regioni([5, 15], 20) == [segui.Tratto(5, 0, 10), segui.Tratto(15, 11, 19)]
    assert segui.regioni([0, 3, 19], 20) == [
        segui.Tratto(0, 0, 1), segui.Tratto(3, 2, 11), segui.Tratto(19, 12, 19)]
    assert segui.regioni([25, -1], 20) == []
    chi = segui.da_chi([5, 15], 20)
    assert chi[:11] == [5] * 11 and chi[11:] == [15] * 9


def test_una_correzione_rifa_solo_la_sua_parte():
    tutto = {indice: (5, 1) for indice in range(20)}
    assert segui.da_rifare({5: 1}, tutto, 20) == []
    assert segui.da_rifare({5: 1}, {}, 20) == [segui.Tratto(5, 0, 19)]
    assert segui.da_rifare({5: 1, 15: 2}, tutto, 20) == [segui.Tratto(15, 11, 19)]
    rifatta = {**tutto, **{indice: (15, 2) for indice in range(11, 20)}}
    assert segui.da_rifare({5: 3, 15: 2}, rifatta, 20) == [segui.Tratto(5, 0, 10)]
    assert segui.da_rifare({5: 1}, rifatta, 20) == [segui.Tratto(5, 5, 19)]


def test_il_filmato_tiene_ogni_fotogramma_dritto_e_coi_suoi_tempi(video):
    pronto = filmato.Filmato(video)
    assert pronto.quanti == QUANTI
    assert (pronto.larghezza, pronto.altezza) == (LARGA, ALTA)
    assert pronto.istanti[0] == 0 and pronto.istanti[1] == 1000 // AL_SECONDO
    assert pronto.istanti == sorted(pronto.istanti)
    quadro = numpy.asarray(pronto.quadro(7))
    x = 10 + 7 * 4
    assert quadro[30 + LATO // 2, x + LATO // 2, 0] > 150
    assert quadro[30 + LATO // 2, x - 6, 0] < 80


def test_il_filmato_grande_si_rimpicciolisce(tmp_path):
    assert filmato.misura_di_lavoro(3840, 2160) == (1008, 567)
    assert filmato.misura_di_lavoro(1080, 1920) == (567, 1008)
    assert filmato.misura_di_lavoro(640, 360) == (640, 360)
    assert filmato.misura_per(300)[0] == filmato.LATO
    assert filmato.misura_per(10 ** 6)[0] < filmato.LATO


def test_il_filmato_si_ferma_a_meta(video):
    with pytest.raises(filmato.Fermato):
        filmato.Filmato(video, fermati=lambda: True)


def test_un_file_che_non_e_un_video_non_si_segue(tmp_path):
    rotto = tmp_path / "rotto.mp4"
    rotto.write_bytes(b"non sono un video")
    with pytest.raises(ErroreOfficina) as preso:
        filmato.Filmato(rotto)
    assert preso.value.messaggio == filmato.NON_SI_APRE
    assert "rotto" not in preso.value.messaggio


def test_si_prepara_e_si_segue_in_casa(strumento, sam3, video):
    al_clic = strumento()
    pronto = al_clic.prepara(sam3, "v1", video)
    assert pronto["quanti"] == QUANTI and len(pronto["istanti"]) == QUANTI
    arrivati = []
    esito = al_clic.segui(sam3, "v1", video, {5: _quadrato(5)}, [segui.Tratto(5, 0, 19)],
                          lambda dati: arrivati.extend(dati.get("fotogrammi", [])))
    assert esito["fatti"] == QUANTI and not esito["fermato"]
    assert sorted(indice for indice, *_ in arrivati) == list(range(QUANTI))
    assert {da for _, da, _, _ in arrivati} == {5}
    dati = dict((indice, maschera) for indice, _, maschera, _ in arrivati)
    assert maschere.apri(dati[6]).x == maschere.apri(dati[5]).x + sceglitore_finto.PASSO
    assert lavori.turno.chi is al_clic.lavoro


def test_si_sceglie_su_un_fotogramma_del_video(strumento, sam3, video):
    al_clic = strumento()
    dati = al_clic.scegli(sam3, "v1", video, [], None, fotogramma=3)
    assert (dati["larghezza"], dati["altezza"]) == (LARGA, ALTA)
    with pytest.raises(ErroreOfficina):
        al_clic.scegli(sam3, "v1", video, [], None, fotogramma=QUANTI + 4)


def test_senza_scheda_libera_il_seguito_aspetta(strumento, sam3, video):
    al_clic = strumento("SenzaScheda")
    with pytest.raises(ritocco_web.SchedaOccupata):
        al_clic.segui(sam3, "v1", video, {5: _quadrato(5)}, [segui.Tratto(5, 0, 19)])
    altro = lavori.Lavoro("miglioramento")
    occupante = strumento()
    assert lavori.turno.prendi_se_libera(altro)
    with pytest.raises(ritocco_web.SchedaOccupata):
        occupante.segui(sam3, "v1", video, {5: _quadrato(5)}, [segui.Tratto(5, 0, 19)])
    lavori.turno.lascia(altro)
    esito = occupante.segui(sam3, "v1", video, {5: _quadrato(5)}, [segui.Tratto(5, 0, 19)],
                            scheda=False)
    assert esito["fatti"] == QUANTI and esito["dove"] == "processore"


def test_se_la_scheda_finisce_la_memoria_segue_sul_processore(strumento, sam3, video):
    al_clic = strumento("Piena")
    esito = al_clic.segui(sam3, "v1", video, {5: _quadrato(5)}, [segui.Tratto(5, 0, 19)])
    assert esito["fatti"] == QUANTI and esito["dove"] == "processore"


def test_un_guasto_nel_seguire_non_dice_dove_stanno_i_file(strumento, sam3, video):
    al_clic = strumento("Rotta")
    with pytest.raises(ErroreOfficina) as preso:
        al_clic.segui(sam3, "v1", video, {5: _quadrato(5)}, [segui.Tratto(5, 0, 19)])
    assert preso.value.messaggio == ritocco_web.NON_SEGUE
    assert "segreta" not in preso.value.messaggio


def test_a_parte_si_segue_e_ci_si_ferma_a_meta(strumento, sam3, video, monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    al_clic = strumento("Lento")
    arrivati = []
    risultato = {}
    try:
        al_clic.prepara(sam3, "v1", video)

        def fai():
            risultato.update(al_clic.segui(
                sam3, "v1", video, {5: _quadrato(5)}, [segui.Tratto(5, 0, 19)],
                lambda dati: arrivati.extend(dati.get("fotogrammi", []))))

        import threading

        filo = threading.Thread(target=fai)
        filo.start()
        assert _aspetta(lambda: len(arrivati) >= ritocco_web.OGNI_QUANTI)
        al_clic.ferma()
        filo.join(timeout=15)
        assert risultato["fermato"] and 0 < len(arrivati) < QUANTI
        pid = {visto["pid"] for visto in sceglitore_finto.seguiti(sam3)}
        assert len(pid) == 1 and pid != {os.getpid()}
        dopo = al_clic.segui(sam3, "v1", video, {1: _quadrato(1)}, [segui.Tratto(1, 0, 2)])
        assert dopo["fatti"] == 3 and not dopo["fermato"]
    finally:
        al_clic.chiudi()


def _file_video(archivio, video: Path) -> int:
    quando = adesso()
    with archivio.scrittura() as connessione:
        scatto = inserisci(connessione,
                           "INSERT INTO scatti (genere, creato_il) VALUES ('video', ?)", quando)
        return inserisci(
            connessione,
            "INSERT INTO file_media (scatto_id, ruolo, genere, impronta, dimensione, "
            "aggiunto_il) VALUES (?, 'principale', 'video', ?, ?, ?)",
            scatto, "v1", video.stat().st_size, quando)


def _seguito(archivio, file_id: int, scelte: dict[int, bytes]) -> int:
    with archivio.scrittura() as connessione:
        seguito_id = seguiti.nuovo(connessione, file_id, cosa="volto", impronta="v1",
                                   larghezza=LARGA, altezza=ALTA, quanti=QUANTI,
                                   istanti_ms=[indice * 100 for indice in range(QUANTI)])
        for fotogramma, maschera in scelte.items():
            seguiti.metti_scelta(connessione, seguito_id, fotogramma, maschera)
    return seguito_id


def test_il_seguito_si_scrive_e_una_correzione_rifa_solo_la_sua_parte(archivio, strumento,
                                                                       sam3, video):
    al_clic = strumento()
    file_id = _file_video(archivio, video)
    seguito_id = _seguito(archivio, file_id, {5: _quadrato(5)})
    esito = seguire.segui_ora(archivio, seguito_id, al_clic, sam3, video, "v1")
    assert esito["fatti"] == QUANTI
    with archivio.lettura() as connessione:
        stato = seguiti.come_sta(connessione, seguito_id)
        assert stato["stato"] == seguiti.SEGUITO and stato["fatti"] == QUANTI
        assert stato["presenze"] == [[0, QUANTI - 1]] and stato["scelte"] == [5]
        assert seguiti.tratti_da_fare(connessione, seguito_id) == []
        istanti = seguiti.istanti(seguiti.per_id(connessione, seguito_id))
    assert istanti[3] == 300

    with archivio.scrittura() as connessione:
        seguiti.metti_scelta(connessione, seguito_id, 15, _quadrato(15))
        assert seguiti.come_sta(connessione, seguito_id)["stato"] == seguiti.DA_SEGUIRE
    seguire.segui_ora(archivio, seguito_id, al_clic, sam3, video, "v1")
    assert sceglitore_finto.seguiti(sam3)[-1]["tratti"] == [[15, 11, 19]]
    with archivio.lettura() as connessione:
        da = seguiti.fatti(connessione, seguito_id)
        assert {da[indice][0] for indice in range(11)} == {5}
        assert {da[indice][0] for indice in range(11, QUANTI)} == {15}
        assert maschere.apri(seguiti.maschera_di(connessione, seguito_id, 15)).x == 10 + 15 * 4
        assert len(seguiti.tutte_le_maschere(connessione, seguito_id)) == QUANTI


def test_chi_sparisce_lascia_un_buco_nella_striscia(archivio, strumento, sam3, video):
    al_clic = strumento()
    file_id = _file_video(archivio, video)
    seguito_id = _seguito(archivio, file_id, {2: _quadrato(2)})
    seguire.segui_ora(archivio, seguito_id, al_clic, sam3, video, "v1")
    with archivio.lettura() as connessione:
        presenze = seguiti.presenze(connessione, seguito_id)
    ultimo = (LARGA - 10) // sceglitore_finto.PASSO
    assert presenze[0][0] == 0 and presenze[-1][1] < QUANTI
    assert presenze == [[0, min(QUANTI - 1, ultimo)]]


def test_una_scelta_sola_non_si_toglie(archivio):
    with archivio.scrittura() as connessione:
        scatto = inserisci(connessione, "INSERT INTO scatti (genere, creato_il) "
                           "VALUES ('video', ?)", adesso())
        file_id = inserisci(connessione,
                            "INSERT INTO file_media (scatto_id, ruolo, genere, impronta, "
                            "dimensione, aggiunto_il) VALUES (?, 'principale', 'video', 'v', 1, ?)",
                            scatto, adesso())
        seguito_id = seguiti.nuovo(connessione, file_id, cosa="oggetto", impronta="v",
                                   larghezza=LARGA, altezza=ALTA, quanti=QUANTI, istanti_ms=[])
        seguiti.metti_scelta(connessione, seguito_id, 4, _quadrato(4))
        assert not seguiti.togli_scelta(connessione, seguito_id, 4)
        seguiti.metti_scelta(connessione, seguito_id, 12, _quadrato(12))
        assert seguiti.togli_scelta(connessione, seguito_id, 12)
        assert sorted(seguiti.scelte(connessione, seguito_id)) == [4]


def test_senza_scheda_il_seguito_va_in_coda(archivio, strumento, sam3, video):
    al_clic = strumento("SenzaScheda")
    file_id = _file_video(archivio, video)
    seguito_id = _seguito(archivio, file_id, {5: _quadrato(5)})
    assert seguire.segui_ora(archivio, seguito_id, al_clic, sam3, video, "v1")["in_coda"]
    with archivio.lettura() as connessione:
        assert seguiti.come_sta(connessione, seguito_id)["stato"] == seguiti.IN_CODA


def test_un_guasto_lo_segna_fallito_con_parole_semplici(archivio, strumento, sam3, video):
    al_clic = strumento("Rotta")
    file_id = _file_video(archivio, video)
    seguito_id = _seguito(archivio, file_id, {5: _quadrato(5)})
    with pytest.raises(ErroreOfficina):
        seguire.segui_ora(archivio, seguito_id, al_clic, sam3, video, "v1")
    with archivio.lettura() as connessione:
        stato = seguiti.come_sta(connessione, seguito_id)
    assert stato["stato"] == seguiti.FALLITO and stato["guasto"] == ritocco_web.NON_SEGUE


def test_l_inseguitore_rifa_il_giro_se_arriva_una_correzione(archivio, strumento, sam3,
                                                             video, monkeypatch):
    from officina.archivio import accesso

    al_clic = strumento("Lento")
    monkeypatch.setattr(accesso, "aperto", lambda: archivio)
    inseguitore = seguire.Inseguitore(al_clic)
    file_id = _file_video(archivio, video)
    seguito_id = _seguito(archivio, file_id, {5: _quadrato(5)})
    inseguitore.parti(seguito_id, sam3, video, "v1")
    assert _aspetta(lambda: len(sceglitore_finto.seguiti(sam3)) == 1)
    with archivio.scrittura() as connessione:
        seguiti.metti_scelta(connessione, seguito_id, 15, _quadrato(15))
    inseguitore.parti(seguito_id, sam3, video, "v1")
    assert inseguitore.lavoro.aspetta_che_finisca(30)
    with archivio.lettura() as connessione:
        stato = seguiti.come_sta(connessione, seguito_id)
        da = seguiti.fatti(connessione, seguito_id)
    assert stato["stato"] == seguiti.SEGUITO and stato["fatti"] == QUANTI
    assert {da[indice][0] for indice in range(11, QUANTI)} == {15}
    assert len(sceglitore_finto.seguiti(sam3)) >= 2
