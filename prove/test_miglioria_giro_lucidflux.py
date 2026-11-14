from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from officina.errori import ErroreOfficina
from officina.miglioria import accesa, catena, coda, lavoro, mezzi, motori, veloce
from officina.miglioria import giro_lucidflux_stanza as giro_stanza
from prove.test_miglioria import _jpeg, _metti, _riga, cartella, importato

pytest.importorskip("av")

__all__ = ["cartella", "importato"]


@pytest.fixture(autouse=True)
def rete_che_non_si_chiude(monkeypatch):
    from officina.miglioria import rete

    monkeypatch.setattr(rete, "chiudi", lambda: None)
QUI = "prove.test_miglioria_giro_lucidflux"
SCELTI = {"foto": motori.LUCIDFLUX, "video": motori.FINTO, "volti": None}


class FintoLucid:

    nome = motori.LUCIDFLUX
    versione = "prova-1"
    creati = 0
    spenti = 0

    def __init__(self, tieni: bool = False, **_opzioni) -> None:
        type(self).creati += 1
        self.tieni = tieni

    def foto(self, immagine, larghezza: int, altezza: int):
        grande = immagine.resize((larghezza, altezza), Image.Resampling.BICUBIC)
        return grande.point(lambda valore: (valore * 7 + 3) % 256)

    def spegni(self) -> None:
        type(self).spenti += 1


class FintoSeed:

    nome = motori.SEEDVR2
    versione = "prova-2"

    def __init__(self, **_opzioni) -> None:
        pass

    def foto(self, immagine, larghezza: int, altezza: int):
        grande = immagine.resize((larghezza, altezza), Image.Resampling.LANCZOS)
        return grande.point(lambda valore: 255 - valore)

    def spegni(self) -> None:
        pass


@pytest.fixture
def finti(monkeypatch):
    monkeypatch.setitem(motori.FOTO, motori.LUCIDFLUX, f"{QUI}:FintoLucid")
    monkeypatch.setitem(motori.FOTO, motori.SEEDVR2, f"{QUI}:FintoSeed")
    monkeypatch.setattr(FintoLucid, "creati", 0)
    monkeypatch.setattr(FintoLucid, "spenti", 0)
    return FintoLucid


def _foto(cartella_: Path, nome: str, misura_=(160, 120)) -> Path:
    percorso = cartella_ / nome
    _jpeg(percorso, misura_, "2019:05:06 07:08:09")
    return percorso


def _lavoro(originale: Path, uscita: Path, **altro) -> dict:
    return {"genere": "immagine", "originale": str(originale), "uscita": str(uscita),
            "motori": {"foto": motori.LUCIDFLUX, "volti": None}, "misura": "4k", **altro}


def _senza_tempi(esito: dict) -> dict:
    fuori = {chiave: valore for chiave, valore in esito.items()
             if chiave not in ("secondi", "dopo")}
    return json.loads(json.dumps(fuori))


def test_il_mezzo_torna_uguale_bit_per_bit(tmp_path):
    immagine = Image.effect_noise((97, 61), 80).convert("RGB")
    suo = mezzi.timbro("abc", "lucidflux", "v", (10, 6), (97, 61))
    assert mezzi.scrivi(tmp_path, 7, immagine, suo, {"nome": "lucidflux"}, {"secondi": 1})
    immagine_letta, usato, misura_ = mezzi.leggi(tmp_path, 7, suo)
    assert immagine_letta.tobytes() == immagine.tobytes() and immagine_letta.mode == "RGB"
    assert usato == {"nome": "lucidflux"} and misura_ == {"secondi": 1}
    assert mezzi.c_e(tmp_path, 7, "abc", "v")
    assert not mezzi.c_e(tmp_path, 7, "altra", "v")
    assert not mezzi.c_e(tmp_path, 7, "abc", "altra")
    assert mezzi.leggi(tmp_path, 7, dict(suo, impronta="altra")) is None
    assert mezzi.leggi(tmp_path, 7, dict(suo, dopo=[96, 61])) is None
    assert not mezzi.scrivi(tmp_path, 8, immagine.convert("RGBA"), suo, {}, {})
    assert not any(tmp_path.glob("8.*"))


def test_un_mezzo_toccato_non_si_usa(tmp_path):
    immagine = Image.effect_noise((40, 30), 80).convert("RGB")
    suo = mezzi.timbro("abc", "lucidflux", "v", (10, 6), (40, 30))
    assert mezzi.scrivi(tmp_path, 3, immagine, suo, {}, {})
    png, json_ = mezzi.percorsi(tmp_path, 3)
    cambiata = immagine.copy()
    cambiata.putpixel((5, 5), tuple((v + 1) % 256 for v in cambiata.getpixel((5, 5))))
    cambiata.save(png, format="PNG")
    assert mezzi.leggi(tmp_path, 3, suo) is None
    assert mezzi.scrivi(tmp_path, 3, immagine, suo, {}, {})
    json_.write_text("{rotto", encoding="utf-8")
    assert mezzi.leggi(tmp_path, 3, suo) is None
    png.write_bytes(b"non sono un png")
    assert mezzi.leggi(tmp_path, 3, suo) is None


def test_pulisci_tiene_solo_quelli_che_servono(tmp_path):
    immagine = Image.new("RGB", (4, 4), (1, 2, 3))
    for numero in (1, 2, 3):
        assert mezzi.scrivi(tmp_path, numero, immagine,
                            mezzi.timbro("a", "l", "v", (2, 2), (4, 4)), {}, {})
    (tmp_path / "9.png.parziale").write_bytes(b"x")
    assert mezzi.pulisci(tmp_path, {2}) == 5
    assert sorted(file.name for file in tmp_path.iterdir()) == ["2.json", "2.png"]
    mezzi.butta(tmp_path, 2)
    assert not any(tmp_path.iterdir())
    assert mezzi.pulisci(tmp_path / "non_c_e", set()) == 0


def test_col_giro_la_foto_esce_uguale_a_prima_e_lucidflux_si_carica_una_volta(
        tmp_path, finti):
    foto = [_foto(tmp_path / "originali", f"f{numero}.jpg", (160 + numero * 8, 120))
            for numero in range(3)]
    prima = {}
    for numero, originale in enumerate(foto):
        uscita = tmp_path / "prima" / f"{numero}.jpg"
        uscita.parent.mkdir(parents=True, exist_ok=True)
        prima[numero] = (catena.foto(_lavoro(originale, uscita)), uscita.read_bytes())
    assert finti.creati == 3

    finti.creati = finti.spenti = 0
    base = tmp_path / "mezzi"
    acceso = FintoLucid(tieni=True)
    for numero, originale in enumerate(foto):
        assert catena.solo_lucidflux(_lavoro(originale, tmp_path / "x"), acceso, base,
                                     numero) == "fatto"
    assert catena.solo_lucidflux(_lavoro(foto[0], tmp_path / "x"), acceso, base,
                                 0) == "gia_fatto"
    assert finti.creati == 1 and finti.spenti == 0

    for numero, originale in enumerate(foto):
        uscita = tmp_path / "dopo" / f"{numero}.jpg"
        uscita.parent.mkdir(parents=True, exist_ok=True)
        esito = catena.foto(_lavoro(originale, uscita,
                                    mezzo={"cartella": str(base), "id": numero}))
        assert uscita.read_bytes() == prima[numero][1]
        assert _senza_tempi(esito) == _senza_tempi(prima[numero][0])
        assert [usato["nome"] for usato in esito["motori"]] == ["lucidflux", "seedvr2"]
    assert finti.creati == 1


def test_un_mezzo_che_non_torna_ferma_la_foto_e_non_tocca_l_uscita(tmp_path, finti):
    originale = _foto(tmp_path, "a.jpg")
    base = tmp_path / "mezzi"
    assert catena.solo_lucidflux(_lavoro(originale, tmp_path / "x"), FintoLucid(), base,
                                 1) == "fatto"
    png, _json = mezzi.percorsi(base, 1)
    with Image.open(png) as aperta:
        rovinata = aperta.convert("RGB")
    rovinata.putpixel((0, 0), (0, 0, 0) if rovinata.getpixel((0, 0)) != (0, 0, 0)
                      else (1, 1, 1))
    rovinata.save(png, format="PNG")
    uscita = tmp_path / "uscita.jpg"
    with pytest.raises(mezzi.MezzoRotto) as preso:
        catena.foto(_lavoro(originale, uscita, mezzo={"cartella": str(base), "id": 1}))
    assert preso.value.codice == "mezzo_rotto" and isinstance(preso.value, ErroreOfficina)
    assert not uscita.exists()

    assert catena.solo_lucidflux(_lavoro(originale, tmp_path / "x"), FintoLucid(), base,
                                 1) == "fatto"
    _jpeg(originale, (160, 120), "2020:01:01 00:00:00")
    with pytest.raises(mezzi.MezzoRotto):
        catena.foto(_lavoro(originale, uscita, mezzo={"cartella": str(base), "id": 1}))


def test_il_mezzo_non_serve_se_lucidflux_non_fa_il_primo_passo(tmp_path, finti):
    grande = _foto(tmp_path, "grande.jpg", (3000, 2000))
    assert catena.solo_lucidflux(_lavoro(grande, tmp_path / "x"), FintoLucid(),
                                 tmp_path / "mezzi", 1) == "non_serve"
    piccola = _foto(tmp_path, "piccola.jpg")
    assert catena.solo_lucidflux(_lavoro(piccola, tmp_path / "x", misura="2k"),
                                 FintoLucid(), tmp_path / "mezzi", 2) == "fatto"
    uscita = tmp_path / "u.jpg"
    esito = catena.foto(_lavoro(piccola, uscita, misura="2k",
                                mezzo={"cartella": str(tmp_path / "mezzi"), "id": 2}))
    assert [usato["nome"] for usato in esito["motori"]] == ["lucidflux"]
    lavoro_seed = _lavoro(piccola, uscita, mezzo={"cartella": "x", "id": 2})
    lavoro_seed["motori"] = {"foto": motori.SEEDVR2, "volti": None}
    assert catena.foto(lavoro_seed)["motori"][0]["nome"] == "seedvr2"


def test_lo_spazio_poco_non_scrive_il_mezzo(tmp_path, finti, monkeypatch):
    monkeypatch.setattr(mezzi, "ci_sta", lambda *_: False)
    originale = _foto(tmp_path, "a.jpg")
    assert catena.solo_lucidflux(_lavoro(originale, tmp_path / "x"), FintoLucid(),
                                 tmp_path / "mezzi", 1) == "spazio"
    assert finti.creati == 1 and not mezzi.c_e(tmp_path / "mezzi", 1, "", "")


def test_la_stanza_del_giro_carica_lucidflux_una_volta_e_lo_spegne(tmp_path, finti):
    foto = [_foto(tmp_path, f"{numero}.jpg") for numero in range(3)]
    mandati = []
    lavoro_ = {"giro": [{"id": numero, "originale": str(originale)}
                        for numero, originale in enumerate(foto)]
               + [{"id": 9, "originale": str(tmp_path / "manca.jpg")}],
               "cartella": str(tmp_path / "mezzi"), "misura": "4k", "intensita": 100,
               "percorsi": [], "opzioni": {}}
    assert giro_stanza.un_giro(lavoro_, mandati.append) == 0
    assert mandati[-1] == {"fatto": {"mezzi": {"0": "fatto", "1": "fatto", "2": "fatto",
                                               "9": "illeggibile"}}}
    assert {"fatti": 4, "totale": 4} in mandati
    assert finti.creati == 1 and finti.spenti == 1
    assert giro_stanza.un_giro({"giro": "x"}, mandati.append) == 2
    assert mandati[-1] == {"guasto": "lavoro_illeggibile"}


def test_la_stanza_del_giro_dice_il_guasto_e_quelli_gia_fatti(tmp_path, finti, monkeypatch):
    foto = [_foto(tmp_path, f"{numero}.jpg") for numero in range(2)]
    vero = catena.solo_lucidflux

    def a_meta(lavoro_, acceso, cartella_, miglioria_id, freno=None):
        if miglioria_id == 1:
            raise RuntimeError("si rompe")
        return vero(lavoro_, acceso, cartella_, miglioria_id, freno)

    monkeypatch.setattr(catena, "solo_lucidflux", a_meta)
    mandati = []
    lavoro_ = {"giro": [{"id": numero, "originale": str(originale)}
                        for numero, originale in enumerate(foto)],
               "cartella": str(tmp_path / "mezzi"), "opzioni": {}}
    assert giro_stanza.un_giro(lavoro_, mandati.append) == 1
    assert mandati[-1]["guasto"] == "rotto" and mandati[-1]["mezzi"] == {"0": "fatto"}
    assert finti.spenti == 1


def test_la_stanza_accesa_tiene_seedvr2_quando_c_e_il_mezzo():
    foto = {"genere": "immagine", "motori": {"foto": motori.LUCIDFLUX}}
    assert accesa.resta_accesa(dict(foto, mezzo={"cartella": "x", "id": 1})) is \
        motori.resta_acceso(motori.FOTO, motori.SEEDVR2)
    assert accesa.resta_accesa(foto) is motori.resta_acceso(motori.FOTO, motori.LUCIDFLUX)


def _nella_stanza(lavori: list, rovina=None):
    def lancia(lavoro_da_fare, al_passo, ricorda):
        lavori.append(dict(lavoro_da_fare))
        if rovina is not None and lavoro_da_fare.get("mezzo"):
            rovina(lavoro_da_fare["mezzo"])
        try:
            return {"fatto": catena.esegui(lavoro_da_fare, al_passo)}
        except ErroreOfficina as errore:
            return {"guasto": errore.codice}

    return lancia


def _giri(giri: list):
    def lancia_il_giro(lavoro_da_fare, al_passo, ricorda):
        giri.append(lavoro_da_fare)
        mandati = []
        giro_stanza.un_giro(lavoro_da_fare, mandati.append)
        return mandati[-1]

    return lancia_il_giro


def _gira_col_giro(archivio, lancia, lancia_il_giro, acceso=True):
    archivio.imposta(veloce.CHIAVE, {veloce.SCRITTURA: False,
                                     veloce.GIRO_LUCIDFLUX: acceso})
    miglioratore = lavoro.Miglioratore(archivio, lancia=lancia, motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: False,
                                       lancia_il_giro=lancia_il_giro)
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(120)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.guasto
    return miglioratore


def _uscite(archivio) -> dict:
    return {Path(riga["percorso_originale"]).name:
            Path(riga["in_revisione"]).read_bytes()
            for riga in _riga(archivio, coda.DA_RIVEDERE)}


def test_il_miglioramento_col_giro_fa_le_stesse_foto_di_prima(importato, finti, tmp_path):
    _metti(importato, "piccola.jpg", "grande.jpg")
    lavori: list = []
    giri: list = []
    _gira_col_giro(importato, _nella_stanza(lavori), _giri(giri))
    assert len(giri) == 1 and len(giri[0]["giro"]) == 2
    assert finti.creati == 1 and finti.spenti == 1
    assert [bool(fatto.get("mezzo")) for fatto in lavori] == [True, True]
    assert not any(mezzi.cartella(importato.dove).iterdir())
    col_giro = _uscite(importato)
    assert set(col_giro) == {"piccola.jpg", "grande.jpg"}

    for riga in _riga(importato, coda.DA_RIVEDERE):
        uscita = tmp_path / f"vecchia-{riga['id']}.jpg"
        catena.foto(_lavoro(Path(riga["percorso_originale"]), uscita))
        assert uscita.read_bytes() == col_giro[Path(riga["percorso_originale"]).name]


def test_spento_si_lavora_come_prima(importato, finti):
    _metti(importato, "piccola.jpg")
    lavori: list = []
    giri: list = []
    _gira_col_giro(importato, _nella_stanza(lavori), _giri(giri), acceso=False)
    assert giri == [] and [fatto.get("mezzo") for fatto in lavori] == [None]
    assert finti.creati == 1


def test_un_mezzo_rotto_si_butta_e_la_foto_si_rifa_senza(importato, finti):
    _metti(importato, "piccola.jpg")

    def rovina(mezzo):
        png, _json = mezzi.percorsi(Path(mezzo["cartella"]), mezzo["id"])
        png.write_bytes(b"rotto")

    lavori: list = []
    _gira_col_giro(importato, _nella_stanza(lavori, rovina), _giri([]))
    assert [bool(fatto.get("mezzo")) for fatto in lavori] == [True, False]
    assert finti.creati == 2
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    assert Path(riga["in_revisione"]).is_file()
    assert not any(mezzi.cartella(importato.dove).iterdir())


def test_se_il_giro_si_rompe_le_foto_si_fanno_come_prima(importato, finti):
    _metti(importato, "piccola.jpg", "grande.jpg")

    def rotto(lavoro_da_fare, al_passo, ricorda):
        return {"guasto": "memoria_finita", "mezzi": {}}

    lavori: list = []
    miglioratore = _gira_col_giro(importato, _nella_stanza(lavori), rotto)
    assert [fatto.get("mezzo") for fatto in lavori] == [None, None]
    assert len(_riga(importato, coda.DA_RIVEDERE)) == 2
    assert miglioratore._mezzi_provati
