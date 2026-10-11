from __future__ import annotations

import struct
from pathlib import Path

import pytest

from officina import finestra
from officina.errori import ErroreOfficina


def test_su_windows_cerca_chrome_e_edge_dove_stanno_davvero():
    posti = [str(p).lower() for p in finestra.candidati("win32")]
    assert any("chrome.exe" in p for p in posti)
    assert any("msedge.exe" in p for p in posti)


def test_cerca_anche_dove_chrome_si_installa_senza_amministratore():
    posti = [str(p) for p in finestra.candidati("win32")]
    assert any("AppData" in p or "Local" in p for p in posti)


def test_il_primo_browser_che_c_e_vince():
    elenco = [Path("/manca/chrome"), Path("/qui/chrome"), Path("/qui/edge")]
    trovato = finestra.dove_sta_un_browser(
        elenco, c_e=lambda p: str(p).startswith("/qui"))
    assert trovato == Path("/qui/chrome")


def test_se_nei_posti_soliti_non_c_e_lo_cerca_nel_percorso():
    trovato = finestra.dove_sta_un_browser(
        [Path("/niente")], c_e=lambda p: False,
        nel_percorso=lambda nome: "/usr/bin/chromium" if nome == "chromium" else None)
    assert trovato == Path("/usr/bin/chromium")


def test_senza_nessun_browser_non_inventa_niente():
    assert finestra.dove_sta_un_browser(
        [Path("/niente")], c_e=lambda p: False, nel_percorso=lambda n: None) is None


def test_la_finestra_si_chiede_con_app():
    comando = finestra.comando_per_la_finestra(Path("/x/chrome"),
                                               "http://localhost:8080")
    assert any(pezzo.startswith("--app=") for pezzo in comando)


def test_l_indirizzo_sta_attaccato_ad_app_e_non_di_fianco():
    comando = finestra.comando_per_la_finestra(Path("/x/chrome"),
                                               "http://localhost:8080")
    assert "--app=http://localhost:8080" in comando
    assert "http://localhost:8080" not in comando


def test_aspetta_finche_la_porta_non_risponde():
    risposte = iter([False, False, True])
    bussate = []

    def bussa(porta, host):
        bussate.append(porta)
        return next(risposte)

    assert finestra.aspetta_che_risponda(8080, bussa=bussa, riposa=lambda s: None)
    assert len(bussate) == 3


def test_non_aspetta_per_sempre():
    tempo = iter([0.0, 10.0, 20.0, 31.0])
    assert finestra.aspetta_che_risponda(
        8080, entro=30.0, bussa=lambda p, h: False, riposa=lambda s: None,
        adesso=lambda: next(tempo)) is False


def test_non_apre_niente_prima_che_il_server_risponda(monkeypatch):
    aperti = []
    monkeypatch.setattr(finestra, "aspetta_che_risponda", lambda *a, **k: False)
    monkeypatch.setattr(finestra, "apri", lambda i: aperti.append(i) or "finestra")

    assert finestra.apri_quando_e_pronto(8080) == "niente"
    assert aperti == []


def test_se_c_e_chrome_apre_la_finestra():
    lanciati = []
    com_e_andata = finestra.apri("http://localhost:8080",
                                 cerca=lambda: Path("/x/chrome"),
                                 lancia=lambda c: lanciati.append(c))
    assert com_e_andata == "finestra"
    assert lanciati and "--app=http://localhost:8080" in lanciati[0]


def test_senza_chrome_ripiega_sul_browser_normale():
    assert finestra.apri("http://localhost:8080", cerca=lambda: None,
                         ripiego=lambda i: True) == "browser"


def test_se_il_browser_non_parte_prova_lo_stesso_l_altra_strada():
    def esplode(comando):
        raise OSError("non parte")

    assert finestra.apri("http://localhost:8080", cerca=lambda: Path("/x/chrome"),
                         lancia=esplode, ripiego=lambda i: True) == "browser"


def test_se_non_si_apre_niente_lo_dice_invece_di_fingere():
    assert finestra.apri("http://localhost:8080", cerca=lambda: None,
                         ripiego=lambda i: False) == "niente"


def test_il_desktop_non_si_indovina_si_chiede_a_windows():
    testo = finestra.righe_di_powershell(Path("C:/o/Officina.cmd"), Path("C:/o"),
                                         Path("C:/o/icona.ico"))
    assert "GetFolderPath('Desktop')" in testo
    assert "\\Desktop" not in testo


def test_va_anche_nel_menu_start_cosi_si_trova_scrivendo():
    testo = finestra.righe_di_powershell(Path("C:/o/Officina.cmd"), Path("C:/o"),
                                         Path("C:/o/icona.ico"))
    assert "GetFolderPath('Programs')" in testo


def test_un_apice_nel_nome_utente_non_spezza_il_comando():
    testo = finestra.righe_di_powershell(
        Path("C:/Users/D'Angelo/Officina.cmd"), Path("C:/Users/D'Angelo"),
        Path("C:/i.ico"))
    assert "D''Angelo" in testo


def test_la_finestra_nera_parte_ridotta_a_icona_non_nascosta():
    testo = finestra.righe_di_powershell(Path("C:/o/Officina.cmd"), Path("C:/o"),
                                         Path("C:/i.ico"))
    assert "WindowStyle = 7" in testo


def test_il_collegamento_si_dice_fatto_solo_se_il_file_c_e(tmp_path):
    testo = finestra.righe_di_powershell(Path("C:/o/Officina.cmd"), Path("C:/o"),
                                         Path("C:/i.ico"))
    assert "Test-Path" in testo
    posto_del_test = testo.index("Test-Path")
    assert testo.index("$c.Save()") < posto_del_test, "prima si salva, poi si guarda"


def test_il_collegamento_punta_al_cmd_che_sa_cosa_fare(tmp_path):
    (tmp_path / "Officina.cmd").write_text("@echo off\n")
    visto = {}

    def finto_powershell(script):
        visto["testo"] = script
        return "C:/Users/x/Desktop/Officina.lnk\n"

    fatti = finestra.crea_scorciatoia(radice=tmp_path, piattaforma="win32",
                                      esegui=finto_powershell)
    assert fatti == ["C:/Users/x/Desktop/Officina.lnk"]
    assert "Officina.cmd" in visto["testo"]


def test_senza_il_cmd_non_crea_un_collegamento_al_vuoto(tmp_path):
    with pytest.raises(ErroreOfficina) as errore:
        finestra.crea_scorciatoia(radice=tmp_path, piattaforma="win32",
                                  esegui=lambda s: "")
    assert "Officina.cmd" in str(errore.value)


def test_se_windows_non_lo_crea_dice_come_farlo_a_mano(tmp_path):
    (tmp_path / "Officina.cmd").write_text("@echo off\n")
    with pytest.raises(ErroreOfficina) as errore:
        finestra.crea_scorciatoia(radice=tmp_path, piattaforma="win32",
                                  esegui=lambda s: "\n  \n")
    messaggio = str(errore.value)
    assert "Invia a" in messaggio
    assert "Officina.cmd" in messaggio
    assert str(tmp_path) in messaggio


def test_il_ripiego_a_mano_riporta_anche_cosa_ha_detto_windows():
    messaggio = finestra.a_mano(Path("C:/o"), Path("C:/o/Officina.cmd"),
                                "accesso negato")
    assert "accesso negato" in messaggio


def test_lo_script_arriva_intero_e_non_riga_per_riga():
    comando = finestra.comando_di_powershell("ps.exe", "Write-Output 'ciao'")
    assert "-EncodedCommand" in comando
    assert "-" not in comando[1:], "niente lettura dallo standard input"


def test_lo_script_viaggia_nel_formato_che_powershell_si_aspetta():
    import base64

    comando = finestra.comando_di_powershell("ps.exe", "Write-Output 'ciao'")
    dentro = base64.b64decode(comando[-1]).decode("utf-16-le")
    assert dentro == "Write-Output 'ciao'"


def test_niente_apici_da_proteggere_nella_riga_di_comando():
    script = finestra.righe_di_powershell(
        Path("C:/Users/D'Angelo/Officina.cmd"), Path("C:/Users/D'Angelo"),
        Path("C:/i.ico"))
    comando = finestra.comando_di_powershell("ps.exe", script)
    assert not any("'" in pezzo for pezzo in comando)


def test_powershell_si_cerca_anche_dove_sta_sempre():
    trovato = finestra.dov_e_powershell(cerca=lambda n: None, c_e=lambda p: True)
    assert trovato is not None
    assert "powershell" in trovato.lower()


def test_se_powershell_non_c_e_proprio_lo_dice():
    assert finestra.dov_e_powershell(cerca=lambda n: None,
                                     c_e=lambda p: False) is None


def test_su_linux_scrive_un_collegamento_secondo_lo_standard(tmp_path):
    scritti = {}
    fatti = finestra.crea_scorciatoia(
        radice=tmp_path, piattaforma="linux",
        scrivi=lambda dove, testo: scritti.__setitem__(dove, testo))
    assert fatti
    testo = next(iter(scritti.values()))
    assert testo.startswith("[Desktop Entry]")
    assert "Type=Application" in testo
    assert "Exec=" in testo


def test_su_macos_lo_dice_invece_di_fare_finta(tmp_path):
    with pytest.raises(ErroreOfficina):
        finestra.crea_scorciatoia(radice=tmp_path, piattaforma="darwin")


def misure_dentro(percorso: Path) -> set[int]:
    dati = percorso.read_bytes()
    riserva, genere, quante = struct.unpack("<HHH", dati[:6])
    assert (riserva, genere) == (0, 1), "non è un .ico"
    return {dati[6 + i * 16] or 256 for i in range(quante)}


def test_l_icona_c_e_e_contiene_anche_la_misura_piccola():
    misure = misure_dentro(finestra.ICONA)
    assert 16 in misure
    assert 256 in misure


def test_l_icona_si_rifa_da_zero_da_uno_script_che_si_legge(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "strumenti"))
    try:
        import fai_icona
    finally:
        sys.path.pop(0)

    rifatta = tmp_path / "officina.ico"
    fai_icona.scrivi(rifatta)
    assert misure_dentro(rifatta) == misure_dentro(finestra.ICONA)


def test_una_libreria_che_manca_si_dice_col_comando_per_metterla(monkeypatch):
    from officina import riga_di_comando

    monkeypatch.setattr(riga_di_comando.importlib.util, "find_spec", lambda nome: None)
    with pytest.raises(ErroreOfficina) as errore:
        riga_di_comando._controlla_che_ci_sia_tutto()
    assert "pip install -r requirements.txt" in str(errore.value)


def test_se_c_e_tutto_non_dice_niente(monkeypatch):
    from officina import riga_di_comando

    monkeypatch.setattr(riga_di_comando.importlib.util, "find_spec", lambda nome: object())
    riga_di_comando._controlla_che_ci_sia_tutto()
