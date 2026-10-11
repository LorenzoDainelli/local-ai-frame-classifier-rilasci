from __future__ import annotations

from pathlib import Path

from officina import registro
from officina.archivio.database import leggi_impostazione, scrivi_impostazione
from officina.errori import ErroreOfficina
from officina.modello import cambiamenti
from officina.sincronia import costruzione, fusione, lettore
from officina.web import lavori

DOVE = "sincronia.cartella"


def cartella_ricordata(connessione) -> str:
    return leggi_impostazione(connessione, DOVE, "") or ""


def ricorda_la_cartella(connessione, cartella: str) -> None:
    scrivi_impostazione(connessione, DOVE, (cartella or "").strip())


def pacchetti_nella_cartella(cartella: str) -> list[dict]:
    dove = Path(cartella.strip()) if cartella and cartella.strip() else None
    if dove is None or not dove.is_dir():
        return []
    trovati = []
    for figlia in sorted(dove.iterdir()):
        if not figlia.is_dir():
            continue
        try:
            carta = lettore.sbircia(figlia)
        except ErroreOfficina:
            continue
        trovati.append({
            "cartella": str(figlia),
            "nome": figlia.name,
            "da": carta.mittente_nome,
            "quanti": carta.quanti_cambiamenti,
            "quanti_file": carta.quanti_file,
            "dal": carta.dal_seriale + 1,
            "al": carta.al_seriale,
            "fatto_il": carta.fatto_il,
            "intero": carta.completa,
            "archivio": carta.archivio,
        })
    trovati.sort(key=lambda voce: voce["fatto_il"], reverse=True)
    return trovati


def stato_dei_computer(connessione) -> dict:
    mia = cambiamenti.questa_macchina(connessione)
    altre = []
    for riga in cambiamenti.altre_macchine(connessione):
        altre.append({
            "id": riga["id"],
            "nome": riga["nome"],
            "da_mandarle": cambiamenti.quanti_da_mandare(
                connessione, riga["mi_ha_vista_fino_a"]),
            "vista_il": riga["vista_il"],
        })
    return {
        "io": mia["nome"],
        "scritti": cambiamenti.quanti_da_mandare(connessione),
        "altre": altre,
    }


class InCorso:

    def __init__(self) -> None:
        self.lavoro = lavori.Lavoro("la sincronizzazione")
        self.verso = ""
        self.dove = ""
        self.fatti = 0
        self.quanti = 0
        self.esito: fusione.Esito | None = None
        self.fatto: costruzione.Fatto | None = None


    def costruisci(self, archivio, cartella: Path, password: str,
                   per_macchina_id: int | None = None) -> bool:
        if self.lavoro.sta_lavorando:
            return False
        self._azzera("costruisco", cartella)

        def fallo() -> None:
            fatto = costruzione.costruisci(
                archivio, cartella, password, per_macchina_id=per_macchina_id,
                avanzamento=self._a_che_punto)
            self.fatto = fatto
            self.dove = str(fatto.cartella)
            self.lavoro.di(f"Pacchetto pronto: {fatto.cartella.name}")
            self.lavoro.di(
                f"{fatto.carta.quanti_cambiamenti} cambiamenti, "
                f"{fatto.carta.quanti_file} file, "
                f"{fatto.carta.quante_miniature} miniature")
            for nota in fatto.note[:20]:
                self.lavoro.di(f"Nota — {nota}")
            self.lavoro.di("Adesso portala sull'altro computer come preferisci.")
            registro.evento("visore.pacchetto_fatto",
                            quanti=fatto.carta.quanti_cambiamenti)

        return self.lavoro.parti(fallo, nome="sincronia-costruisci")

    def applica(self, archivio, cartella: Path, password: str) -> bool:
        if self.lavoro.sta_lavorando:
            return False
        self._azzera("applico", cartella)

        def fallo() -> None:
            esito = fusione.fondi(archivio, cartella, password,
                                  avanzamento=self._a_che_punto)
            self.esito = esito
            for riga in racconta(esito):
                self.lavoro.di(riga)
            registro.evento("visore.pacchetto_applicato",
                            gesti=esito.gesti_applicati)

        return self.lavoro.parti(fallo, nome="sincronia-applica")


    def _azzera(self, verso: str, cartella: Path) -> None:
        self.verso = verso
        self.dove = str(cartella)
        self.fatti = 0
        self.quanti = 0
        self.esito = None
        self.fatto = None

    def _a_che_punto(self, fatti: int, quanti: int) -> None:
        self.fatti = fatti
        self.quanti = quanti

    @property
    def percentuale(self) -> int:
        if not self.quanti:
            return 0
        return min(100, int(self.fatti * 100 / self.quanti))

    def come_va(self) -> dict:
        esito = self.esito
        return {
            **self.lavoro.come_va(),
            "verso": self.verso,
            "dove": self.dove,
            "fatti": self.fatti,
            "quanti": self.quanti,
            "percentuale": self.percentuale,
            "numeri": numeri_dell_esito(esito) if esito else None,
            "note": list(esito.note) if esito else [],
        }


in_corso = InCorso()


def numeri_dell_esito(esito: fusione.Esito) -> dict:
    return {
        "mittente": esito.mittente,
        "dal": esito.dal_seriale + 1,
        "al": esito.al_seriale,
        "gesti": esito.gesti_applicati,
        "gia_visti": esito.gesti_gia_visti,
        "file_nuovi": esito.file_nuovi,
        "originali": esito.originali_copiati,
        "miniature": esito.miniature_copiate,
        "impronte": esito.impronte_prese,
        "nodi_creati": esito.nodi_creati,
        "nodi_rinominati": esito.nodi_rinominati,
        "nodi_spostati": esito.nodi_spostati,
        "nodi_cestinati": esito.nodi_cestinati,
        "nodi_risorti": esito.nodi_risorti,
        "etichette_messe": esito.etichette_messe,
        "etichette_tolte": esito.etichette_tolte,
        "etichette_perse": esito.etichette_perse,
        "persone_nominate": esito.persone_nominate,
        "persone_da_guardare": esito.persone_da_guardare,
        "cuori": esito.cuori_arrivati,
        "impostazioni": esito.impostazioni_arrivate,
        "impostazioni_contese": esito.impostazioni_contese,
        "telefoni_nuovi": esito.telefoni_nuovi,
        "niente": not esito.qualcosa_e_cambiato,
    }


def racconta(esito: fusione.Esito) -> list[str]:
    righe = [f"Pacchetto da «{esito.mittente}», cambiamenti dal "
             f"{esito.dal_seriale + 1} al {esito.al_seriale}."]
    if not esito.qualcosa_e_cambiato:
        righe.append("Non c'era niente di nuovo: l'avevo già letto tutto.")
        return righe
    righe.append(
        f"Fotografie nuove: {esito.file_nuovi} — arrivate col pacchetto "
        f"{esito.originali_copiati}, con la miniatura già pronta "
        f"{esito.miniature_copiate}.")
    righe.append(f"Impronte prese così come stavano: {esito.impronte_prese}.")
    righe.append(
        f"Nodi: {esito.nodi_creati} creati, {esito.nodi_rinominati} rinominati, "
        f"{esito.nodi_spostati} spostati, {esito.nodi_cestinati} cestinati.")
    righe.append(f"Etichette: {esito.etichette_messe} messe, "
                 f"{esito.etichette_tolte} tolte.")
    if esito.etichette_perse:
        righe.append(
            f"{esito.etichette_perse} etichette in arrivo sono state scartate "
            "perché qui c'era una tua decisione più forte (regole 404, 405).")
    if esito.nodi_risorti:
        righe.append(
            f"{esito.nodi_risorti} nodi sono tornati in vita perché qui li "
            "avevi usati dopo (regola 407).")
    if esito.impostazioni_arrivate:
        righe.append(
            f"Impostazioni: {esito.impostazioni_arrivate} sono passate da "
            "quel computer a questo. Quelle che dipendono dalla macchina "
            "— la scheda video, lo schermo, il blocco — restano di qui "
            "(regola 28).")
    if esito.persone_nominate:
        righe.append(f"{esito.persone_nominate} persone hanno preso il nome "
                     "che gli avevi dato sull'altro computer.")
    if esito.persone_da_guardare:
        righe.append(
            f"{esito.persone_da_guardare} coppie di persone sono finite nel "
            "cassetto: le guardi affiancate e decidi tu (regola 408).")
    if esito.cuori_arrivati:
        righe.append(f"{esito.cuori_arrivati} cuori dal telefono, col nome del "
                     "telefono attaccato (regola 409).")
    for nota in esito.note[:30]:
        righe.append(f"Nota — {nota}")
    return righe
