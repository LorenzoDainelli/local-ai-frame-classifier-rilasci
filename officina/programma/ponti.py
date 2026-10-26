from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from officina.programma.avvio import Programma


class PonteFinestrina:

    def __init__(self, programma: Programma):
        self._programma = programma

    def stato(self) -> dict:
        return self._programma.stato_per_la_finestrina()

    def usa_la_versione_1(self) -> dict:
        return self._programma.fai(self._programma.usa_la_versione_1)

    def comincia_da_zero(self) -> dict:
        return self._programma.fai(self._programma.comincia_da_zero)

    def sfoglia_archivio(self) -> dict:
        return self._programma.fai(self._programma.sfoglia_archivio)

    def usa_lo_scelto(self) -> dict:
        return self._programma.fai(self._programma.usa_lo_scelto)

    def torna_all_archivio(self) -> dict:
        return self._programma.fai(self._programma.torna_all_archivio)

    def prepara_i_motori(self) -> dict:
        return self._programma.fai(self._programma.prepara_i_motori)

    def come_vanno_i_motori(self) -> dict:
        return self._programma.installatore.stato.come_dati()

    def come_va_l_apertura(self) -> int:
        return int(getattr(self._programma, "fase_apertura", 0))

    def ferma_i_motori(self) -> dict:
        return self._programma.fai(self._programma.ferma_i_motori)

    def entra_col_torch_vecchio(self) -> dict:
        return self._programma.fai(self._programma.entra_col_torch_vecchio)

    def salva_la_chiave(self, valore: str) -> dict:
        return self._programma.fai(lambda: self._programma.salva_la_chiave(valore))

    def apri_il_sito(self, dove: str) -> dict:
        return self._programma.fai(lambda: self._programma.apri_il_sito(dove))

    def scarica_i_modelli(self, facoltativi: list) -> dict:
        return self._programma.fai(lambda: self._programma.scarica_i_modelli(facoltativi))

    def come_vanno_i_modelli(self) -> dict:
        return self._programma.come_vanno_i_modelli()

    def entra_senza_i_corpi(self) -> dict:
        return self._programma.fai(self._programma.entra_senza_i_corpi)

    def ferma_i_modelli(self) -> dict:
        return self._programma.fai(self._programma.ferma_i_modelli)

    def apri_con_windows(self) -> dict:
        return self._programma.fai(self._programma.apri_con_windows)

    def apri_il_forziere(self, password: str) -> dict:
        return self._programma.fai(lambda: self._programma.apri_il_forziere(password))

    def riprova(self) -> dict:
        return self._programma.fai(self._programma.riprova)

    def scegli_lo_schermo(self) -> dict:
        return self._programma.fai(self._programma.scegli_lo_schermo)

    def lascia_lo_schermo(self) -> dict:
        return self._programma.fai(self._programma.lascia_lo_schermo)

    def riabbina(self) -> dict:
        return self._programma.fai(self._programma.riabbina)

    def cerca_il_fisso(self) -> dict:
        return self._programma.fai(self._programma.cerca_il_fisso)

    def com_e_il_fisso(self) -> dict:
        return self._programma.fai(self._programma.com_e_il_fisso)

    def abbina_il_fisso(self, indirizzo: str, porta, codice: str, password: str) -> dict:
        return self._programma.fai(lambda: self._programma.abbina_il_fisso(
            indirizzo, porta, codice, password))

    def entra_nel_fisso_con_windows(self) -> dict:
        return self._programma.fai(self._programma.entra_nel_fisso_con_windows)

    def entra_nel_fisso(self, password: str) -> dict:
        return self._programma.fai(lambda: self._programma.entra_nel_fisso(password))


class PontePrincipale:

    def __init__(self, programma: Programma):
        self._programma = programma

    def versione(self) -> str:
        return self._programma.versione

    def aggiornamento(self) -> dict:
        return self._programma.come_va_l_aggiornamento()

    def aggiorna_adesso(self) -> dict:
        return self._programma.fai(self._programma.aggiorna_adesso)

    def rifiuta_aggiornamento(self) -> dict:
        return self._programma.fai(self._programma.rifiuta_aggiornamento)

    def stato_del_programma(self) -> dict:
        return self._programma.fai(self._programma.stato_del_programma)

    def prepara_i_motori(self) -> dict:
        return self._programma.fai(self._programma.prepara_i_motori_da_dentro)

    def come_vanno_i_motori(self) -> dict:
        return self._programma.installatore.stato.come_dati()

    def salva_la_chiave(self, valore: str) -> dict:
        return self._programma.fai(lambda: self._programma.salva_la_chiave_da_dentro(valore))

    def togli_la_chiave(self) -> dict:
        return self._programma.fai(self._programma.togli_la_chiave)

    def rientra_con_windows(self) -> dict:
        return self._programma.fai(self._programma.rientra_con_windows)

    def rientra(self, password: str) -> dict:
        return self._programma.fai(lambda: self._programma.rientra(password))

    def ricollegati(self) -> dict:
        return self._programma.fai(self._programma.ricollegati)

    def spegni_il_forziere(self, password: str) -> dict:
        return self._programma.fai(lambda: self._programma.spegni_il_forziere(password))

    def accendi_il_forziere(self, password: str, ancora: str, su_carta: bool,
                            dove_torno: str = "") -> dict:
        return self._programma.fai(lambda: self._programma.accendi_il_forziere(
            password, ancora, su_carta, dove_torno))

    def chiudi_comunque(self) -> dict:
        return self._programma.fai(self._programma.chiudi_comunque)

    def apri_l_archivio_sicuro(self, password: str) -> dict:
        return self._programma.fai(lambda: self._programma.apri_l_archivio_sicuro(password))
