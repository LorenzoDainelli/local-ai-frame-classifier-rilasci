# Local AI Frame Classifier

**Le tue foto e i tuoi video, ordinati dall'intelligenza artificiale, tutto
sul tuo computer.**

**[⬇ Scarica per Windows](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases/download/v2.0.0-beta.15/local-ai-frame-classifier-2.0.0-beta.15.exe)** · versione 2.0.0-beta.15 · 38 MB ·
[tutte le versioni](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases) · **[English](README.md)**

> **Beta.** Il programma funziona e si aggiorna da solo, ma è ancora in
> collaudo.

---

## Perché

Quasi tutti i programmi che riconoscono cosa c'è nelle foto prima le mandano
sui server di qualcun altro. Questo no. I modelli di intelligenza artificiale
girano sul tuo PC, l'archivio resta sul tuo disco, e niente di quello che
etichetti esce mai dal tuo computer.

## Cosa fa

- **Importa foto e video** (HEIC, JPEG, PNG, MOV, MP4 e altri) e **non tocca mai gli
  originali**. Riconosce i doppioni, unisce le Live Photo al loro video e
  legge la data vera di ogni scatto, fuso orario compreso.
- **Impara le tue categorie.** L'albero delle categorie lo costruisci tu; il
  programma studia gli scatti che hai confermato e propone le etichette per
  gli altri, dicendo sempre *perché*: «assomiglia a questi cinque che hai già
  etichettato».
- **Si etichetta in fretta**, con la tastiera, uno scatto dopo l'altro, senza
  che la pagina si ricarichi mai.
- **Trova le facce** e raggruppa quelle simili, così le persone si nominano
  un gruppo alla volta.
- **Cerca a parole**, con un modello linguistico che gira anche lui sul
  computer.
- **Ti dice a che punto sei**: quanto è etichettato, quanto spesso ci prende
  sulle *tue* foto e cosa conviene etichettare adesso.
- **Forziere cifrato**, se lo vuoi: senza la password, sul disco l'archivio
  è solo rumore.
- **Due computer**: porti il lavoro da un PC all'altro con una chiavetta.
  In rete non passa niente.
- **Usa la scheda video NVIDIA** se c'è, e funziona anche senza.
- **Si aggiorna da solo.**

È in costruzione un'**app per il telefono**, che mostrerà l'archivio anche
senza connessione.

## Si installa in tre passi

1. **[Scarica l'installatore](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases/download/v2.0.0-beta.15/local-ai-frame-classifier-2.0.0-beta.15.exe)** (38 MB).
2. Doppio clic. Windows può dire *«PC protetto»*, perché il file non è ancora
   firmato: premi **Ulteriori informazioni → Esegui comunque**.
3. Apri **Local AI Frame Classifier** dal menu Start. Al primo avvio prepara i
   motori per il tuo computer (circa 0,5 GB da scaricare, 2,7 GB con una
   scheda NVIDIA) e poi ti accompagna nella scelta della cartella delle foto.

Niente password dell'amministratore, niente Python, niente prompt dei
comandi. [La guida completa →](docs/it/installazione.md)

## Cosa serve

| | |
|---|---|
| Sistema | Windows 10 (1809 o più recente) o Windows 11, a 64 bit |
| Scheda video | facoltativa; le NVIDIA si usano da sole |
| Spazio su disco | circa 2 GB, 6 GB con una NVIDIA, più i modelli che scegli |
| Internet | al primo avvio e per scaricare i modelli; dopo funziona anche senza |

## La tua privacy

Foto, video, etichette, categorie e nomi **non escono mai dal tuo computer**.
Il programma si collega a internet solo per queste quattro cose, e nessuna
contiene i tuoi dati:

| Quando | Dove | Perché |
|---|---|---|
| al primo avvio | `pypi.org`, `download.pytorch.org` | scarica i motori |
| quando premi il tasto | `huggingface.co` | scarica i modelli |
| all'avvio | `api.github.com` | controlla se c'è una versione nuova |
| quando aggiorni | `github.com` | scarica la versione nuova |

[La privacy nel dettaglio →](docs/it/privacy.md)

## Le guide

- [Installazione](docs/it/installazione.md)
- [Primi passi](docs/it/primi-passi.md)
- [Aggiornamenti](docs/it/aggiornamenti.md)
- [Privacy](docs/it/privacy.md)
- [Disinstallazione](docs/it/disinstallazione.md)
- [Domande frequenti](docs/it/domande.md)

## Aiuto e suggerimenti

Hai trovato un errore o hai un'idea?
[Apri una segnalazione](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/issues/new/choose). **Non allegare mai le tue
foto**, e non scrivere i nomi delle persone o delle categorie del tuo
archivio: bastano la descrizione di cosa è successo e il numero di versione.

Per segnalare in privato un problema di sicurezza, vedi
[SECURITY.md](SECURITY.md).

## Licenza

Copyright © 2026 Lorenzo Dainelli. Tutti i diritti riservati. Il programma si
scarica e si usa sui tuoi computer: vedi [LICENSE.md](LICENSE.md). Il
codice sorgente non è pubblico.
