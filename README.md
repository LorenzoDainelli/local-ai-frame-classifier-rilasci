# Local AI Frame Classifier

**Le tue foto e i tuoi video, ordinati dall'intelligenza artificiale, tutto
sul tuo computer.**

Beta · Windows 10 e 11 (64 bit) · interfaccia in italiano ·
[licenza](LICENSE.md): tutti i diritti riservati

Questo è il deposito del **codice**, privato. Chi usa il programma non passa
di qui: la pagina pubblica, con le guide in italiano e in inglese e il file da
scaricare, è
[**local-ai-frame-classifier-rilasci**](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci).
Il suo contenuto si scrive qui, nella cartella [`vetrina/`](vetrina/), e la
costruzione lo pubblica da sola a ogni versione (regola 471).

---

## Scarica

L'ultima versione è sempre nella pagina dei
[**rilasci**](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases):
un file `.exe` di circa 37 MB. Doppio clic, e non serve altro: né Python, né il
prompt dei comandi, né la password dell'amministratore (regole 458-470).

Windows la prima volta dice «PC protetto», perché il file non è ancora
firmato: si passa con **Ulteriori informazioni → Esegui comunque**. La guida
completa è in [Come si installa](documentazione/come-si-installa.md).

## Cosa fa

- **Importa foto e video** — HEIC, JPEG, PNG, MOV — senza mai toccare gli
  originali. Riconosce i doppioni, unisce le live photo e legge la data vera di
  ogni scatto.
- **Impara le tue categorie.** L'albero delle categorie lo decidi tu; il
  programma guarda gli scatti che hai confermato e propone le etichette per gli
  altri, dicendo sempre *perché*.
- **Etichetta in fretta**, con la tastiera, senza che la pagina si ricarichi.
- **Trova le facce** e le raggruppa, così le persone si nominano un gruppo
  alla volta.
- **Cerca a parole**, con un modello linguistico che gira sul computer.
- **Chiude tutto in un forziere cifrato**, se vuoi: senza la password, sul
  disco c'è solo rumore.
- **Lavora su due computer**, passandosi il lavoro con una chiavetta.
- **Prepara un pacchetto cifrato per il telefono.** L'app per il telefono è in
  costruzione.
- **Migliora foto e video piccoli** fino al Full HD, con l'approvazione
  affiancata e la sfida alla cieca fra due modelli.
- **Il portatile fa da schermo al fisso**, abbinato con un codice e cifrato.
- **Aspetto a scelta**: tema, accento, versione di ogni pagina e dei
  movimenti, con la fotina.
- **Usa la scheda video NVIDIA** se c'è, e funziona anche senza.
- **Si aggiorna da solo.**

La descrizione lunga, tappa per tappa e con quello che ancora manca, è in
[Cosa fa e a che punto è](documentazione/cosa-fa.md).

## La privacy

Le foto, i video, le etichette e le categorie **non escono mai dal computer**
(regole 1 e 106). Il programma si collega a internet solo per cinque cose, e
nessuna contiene i tuoi dati:

| Quando | Dove | Perché |
|---|---|---|
| al primo avvio | `pypi.org`, `download.pytorch.org` | scarica i motori dei modelli |
| quando premi il tasto | `huggingface.co` | scarica i modelli |
| quando prepari il miglioramento | `github.com` | scarica il codice dei modelli, a versione fissata |
| all'avvio | `api.github.com` | controlla se c'è una versione nuova |
| quando aggiorni | `github.com` | scarica la versione nuova |

Dopo il primo avvio, e una volta scaricati i modelli, funziona anche a rete
spenta.

## La documentazione

**Per chi lo usa**

- [Come si installa](documentazione/come-si-installa.md)
- [Come si usa](documentazione/come-si-usa.md)
- [Cosa fa e a che punto è](documentazione/cosa-fa.md)
- [I modelli](documentazione/i-modelli.md): quali sono, perché e con che
  licenza
- [La misura](documentazione/la-misura.md)
- [I due computer](documentazione/la-sincronizzazione.md)
- [Il Visore](documentazione/il-visore.md), cioè il telefono
- [La protezione](documentazione/la-protezione.md): da cosa si difende e dove
  la difesa finisce

**Per chi ci lavora**

- [Da riga di comando](documentazione/da-terminale.md)
- [Come funziona dentro](documentazione/come-funziona-dentro.md)
- [Come si costruisce l'app](documentazione/come-si-costruisce-l-app.md) del
  telefono
- [Il prossimo aggiornamento](documentazione/il-prossimo-aggiornamento.md)
- [Come si dismette](documentazione/dismissione.md) la versione 1

## Com'è fatto il deposito

```
officina/          il programma: Python, FastAPI e le pagine della finestra
  programma/       la versione installabile: finestra, primo avvio, aggiornamenti
  web/             il server locale, le pagine e i fogli di stile
installatore/      come si costruisce il .exe (Inno Setup)
visore/            l'app del telefono (Kotlin)
prove/             le prove automatiche, tutte su dati finti
strumenti/         attrezzi per chi sviluppa, compreso il blocco prima del commit
documentazione/    le guide
vetrina/           la pagina pubblica, in italiano e in inglese
sviluppo/          le regole, le bozze grafiche e la storia del progetto
.github/workflows/ la costruzione automatica dell'installatore
```

## Per chi sviluppa

```bash
pip install -r requirements-sviluppo.txt
python -m pytest prove
```

Le prove girano tutte su foto finte generate al momento, mai su foto vere
(regola 73). Ogni push che tocca il programma fa partire su GitHub la
costruzione: prove su Linux e su Windows, collaudo con la finestra vera,
installatore, installazione silenziosa e disinstallazione. Se tutto passa, la
versione è pubblicata.

Il file [`sviluppo/REGOLE.md`](sviluppo/REGOLE.md) è la memoria delle
decisioni: 570 regole
numerate. Non descrive come è fatto il programma, perché quello lo dice il
codice: spiega **perché** è fatto così. Nel codice le regole sono citate per
numero, e quando una scelta sembra strana la spiegazione è lì. I numeri non si
riusano e le regole superate non si cancellano (regole 164 e 343).

La versione 1, `Officina.cmd` con la finestra nera, è conservata intatta nel
ramo `versione-1`. Nella radice resta finché non si smantella (vedi
[Come si dismette](documentazione/dismissione.md)).

## Licenza

Copyright © 2026 Lorenzo Dainelli. Tutti i diritti riservati: il testo è in
[LICENSE.md](LICENSE.md).
