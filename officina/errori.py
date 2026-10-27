from __future__ import annotations


class ErroreOfficina(Exception):

    codice = "errore_generico"

    def __init__(self, messaggio: str, codice: str | None = None):
        super().__init__(messaggio)
        self.messaggio = messaggio
        if codice:
            self.codice = codice


class ArchivioChiuso(ErroreOfficina):
    codice = "archivio_chiuso"


class PasswordSbagliata(ErroreOfficina):
    codice = "password_sbagliata"


class SpazioInsufficiente(ErroreOfficina):
    codice = "spazio_insufficiente"


class FileNonLeggibile(ErroreOfficina):
    codice = "file_non_leggibile"

    def __init__(self, messaggio: str, codice: str | None = None,
                 file_id: int | None = None):
        super().__init__(messaggio, codice)
        self.file_id = file_id


class DaRifare(ErroreOfficina):
    codice = "da_rifare"


class CartellaNonTrovata(ErroreOfficina):
    codice = "cartella_non_trovata"


class DatabaseIncoerente(ErroreOfficina):
    codice = "database_incoerente"


class OperazioneNonPermessa(ErroreOfficina):
    codice = "operazione_non_permessa"


PERCHE_SALTATO = {
    "file_non_leggibile": "il file non si è lasciato aprire",
    "cartella_non_trovata": "la cartella non c'era",
    "errore_imprevisto": "si è rotto qualcosa aprendolo: forse il file è danneggiato",
    "senza_file": "allo scatto non è rimasto nessun file",
    "file_non_trovato": "il file non si trova più sul disco",
    "manca_decodificatore": "manca il decodificatore per aprire questi video",
    "video_senza_indice": "al video manca l'indice interno: la copia si è interrotta",
    "video_danneggiato": "il video è danneggiato e non si apre",
    "video_senza_immagini": "il video si apre ma dentro non c'è nessuna immagine",
    "video_non_apribile": "il video non si è aperto",
    "lettura_fallita": "il file non si è lasciato leggere",
    "permesso_negato": "il permesso di aprire il file è stato negato dal sistema",
    "vuoto": ("il file è di zero byte: forse un segnaposto di iCloud o "
              "OneDrive, con il contenuto ancora nella nuvola"),
    "estensione_bugiarda": "il file non è del tipo che dice di essere",
    "corrotto": "il file è danneggiato",
    "sicuro_chiuso": ("il file non è sul disco e l'Archivio sicuro è chiuso: lo rifaccio "
                      "quando lo apri"),
    "persa_nell_archivio": ("nell'Archivio sicuro il file è rovinato: lo riprovo quando "
                            "l'archivio l'ha riparato"),
    "versione_diversa": ("nell'Archivio sicuro c'è solo una versione cambiata dopo "
                         "l'importazione: l'IA non la guarda"),
}

MOTIVO_SENZA_FRASE = "per un motivo che il programma non sa ancora spiegare"


def perche_saltato(codice: str) -> str:
    return PERCHE_SALTATO.get(codice, MOTIVO_SENZA_FRASE)
