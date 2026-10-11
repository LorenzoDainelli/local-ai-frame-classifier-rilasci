from __future__ import annotations

import re
from pathlib import Path

import pytest

from officina.riga_di_comando import costruisci_parser

GUIDA = (Path(__file__).resolve().parent.parent
         / "documentazione" / "come-si-usa.md")


def _i_comandi() -> dict:
    parser = costruisci_parser()
    for azione in parser._actions:
        if isinstance(getattr(azione, "choices", None), dict):
            return dict(azione.choices)
    raise AssertionError("il parser non ha sottocomandi")


def _bandierine(pezzo) -> set[str]:
    return {lunga for azione in pezzo._actions for lunga in azione.option_strings
            if lunga.startswith("--")}


def _dalla_guida() -> dict[str, set[str]]:
    testo = GUIDA.read_text(encoding="utf-8")
    principio = testo.index("## I comandi")
    blocco = testo[testo.index("```bash", principio) + 7:]
    blocco = blocco[:blocco.index("```")]

    detti: dict[str, set[str]] = {}
    quale = None
    for riga in blocco.splitlines():
        if not riga.strip():
            continue
        avvio = re.match(r"python -m officina\s+([a-z-]+)", riga.strip())
        if avvio:
            quale = avvio.group(1)
            detti.setdefault(quale, set())
        if quale:
            detti[quale] |= set(re.findall(r"--[a-z][a-z-]*", riga))
    return detti


def test_il_parser_si_costruisce_e_ogni_comando_sa_cosa_chiamare():
    for nome, pezzo in _i_comandi().items():
        assert callable(pezzo.get_default("funzione")), (
            f"«{nome}» non sa quale funzione chiamare")


@pytest.mark.parametrize("nome", sorted(_i_comandi()))
def test_ogni_comando_sa_dire_come_si_usa(nome, capsys):
    with pytest.raises(SystemExit) as uscita:
        costruisci_parser().parse_args([nome, "--help"])
    assert uscita.value.code == 0
    detto = capsys.readouterr().out
    assert nome in detto and "usage" in detto.lower()


def test_la_guida_non_promette_comandi_che_non_esistono():
    veri = set(_i_comandi())
    detti = set(_dalla_guida())
    inventati = detti - veri
    assert not inventati, (
        "la guida dice di scrivere comandi che il programma non ha: "
        + ", ".join(sorted(inventati)))


def test_la_guida_li_elenca_tutti():
    veri = set(_i_comandi())
    mancano = veri - set(_dalla_guida())
    assert not mancano, (
        "questi comandi ci sono e la guida non li nomina: "
        + ", ".join(sorted(mancano)))


def test_la_guida_non_promette_bandierine_che_non_esistono():
    comandi = _i_comandi()
    guai = []
    for nome, dette in _dalla_guida().items():
        if nome not in comandi:
            continue
        for bandierina in sorted(dette - _bandierine(comandi[nome])):
            guai.append(f"{nome} {bandierina}")
    assert not guai, ("la guida promette opzioni che non ci sono: "
                      + ", ".join(guai))


def test_chi_non_prende_finto_e_chi_non_apre_un_archivio():
    senza = {nome for nome, pezzo in _i_comandi().items()
             if "--finto" not in _bandierine(pezzo)}
    assert senza == {"finto", "dottore", "scorciatoia", "leggi-pacchetto"}
