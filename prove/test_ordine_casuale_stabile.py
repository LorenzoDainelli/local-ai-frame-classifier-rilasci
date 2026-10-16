from officina.modello import scatti
from officina.modello.scatti import Filtro


def test_l_ordine_mescolato_resta_uguale_fra_una_pagina_e_l_altra(archivio_pieno):
    filtro = Filtro(ordine="casuale")
    with archivio_pieno.lettura() as connessione:
        prima = scatti.soli_numeri(connessione, filtro)
        dopo = scatti.soli_numeri(connessione, filtro)
        assert prima == dopo
        assert sorted(prima) == sorted(set(prima))
        if len(prima) > 2:
            mezzo = prima[len(prima) // 2]
            vicini = scatti.vicini(connessione, filtro, mezzo)
            indice = prima.index(mezzo)
            assert vicini["prima"] == prima[indice - 1]
            assert vicini["dopo"] == prima[indice + 1]
