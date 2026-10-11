from __future__ import annotations

from officina.importazione import gruppi, scansione
from officina.importazione.motore import Motore
from officina.web.strade import intelligenza


def test_il_totale_delle_scritte_segue_il_gruppo(archivio, tmp_path):
    from officina.finto import generatore

    galleria, altra = tmp_path / "galleria", tmp_path / "altra"
    generatore.genera(galleria, quanti=6, seme=3, leggero=True)
    generatore.genera(altra, quanti=4, seme=9, leggero=True)
    connessione = archivio.connessione
    gruppo_id = gruppi.trova_o_crea(connessione, "Gruppo finto")
    scansione.aggiungi_cartella(connessione, altra, gruppo_id)
    connessione.commit()
    motore = Motore(archivio)
    motore.prepara([galleria, altra])
    assert motore.esegui().stato == "finita"

    tutto = intelligenza.quanti_mancano_ia(archivio)
    assert tutto["totale"] - tutto["scritte"] == 0

    gruppi.ricorda(connessione, "intelligenza", gruppo_id)
    connessione.commit()
    nel_gruppo = intelligenza.quanti_mancano_ia(archivio)
    assert 0 < nel_gruppo["totale"] < tutto["totale"]
    assert nel_gruppo["totale"] - nel_gruppo["scritte"] == 0
    assert nel_gruppo["impronte"] <= nel_gruppo["totale"]
