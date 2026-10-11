# Privacy

[← Indietro](../../README.it.md) · [English](../en/privacy.md)

**In breve:** le tue foto, i video, le etichette, le categorie e i nomi delle
persone restano sul tuo computer. Non vengono mai mandati all'autore, a
GitHub, a chi ha fatto i modelli né a nessun altro.

## Cosa resta sul tuo computer

- le foto e i video, che il programma legge ma non modifica, non sposta e non
  copia altrove;
- l'archivio: miniature, impronte, etichette, l'albero delle categorie, le
  facce e i nomi;
- i modelli, una volta scaricati;
- la chiave di Hugging Face, se la dai. Sta nel *Gestore credenziali* di
  Windows, mai in un file.

Non ci sono account, statistiche d'uso, segnalazioni automatiche degli errori
né pubblicità.

## Quando il programma si collega a internet

| Quando | Dove | Cosa manda | Perché |
|---|---|---|---|
| al primo avvio | `pypi.org`, `download.pytorch.org` | una normale richiesta di scaricamento | scarica i motori |
| quando premi il tasto | `huggingface.co` | una richiesta di scaricamento, e la chiave se il modello la chiede | scarica un modello |
| all'avvio | `api.github.com` | la richiesta dell'elenco delle versioni | controlla se c'è una versione nuova |
| quando aggiorni | `github.com` | una richiesta di scaricamento | scarica la versione nuova |

Come per qualsiasi scaricamento, questi servizi vedono il tuo indirizzo IP e
che qualcuno ha scaricato i loro file. Nessuna di queste richieste contiene
qualcosa delle tue foto.

Quando motori e modelli sono al loro posto, puoi lavorare col cavo di rete
staccato.

## Il forziere

Se accendi il forziere, tutto l'archivio viene cifrato con la tua password:
senza, sul disco c'è solo rumore. Le foto originali restano fuori dal
forziere, dove erano.

**Se perdi la password, nessuno può recuperare l'archivio.** Nemmeno
l'autore: non esiste un «password dimenticata», perché una via per rientrare
sarebbe anche la via di chi non deve entrare. Scrivi la password su un foglio e
tienilo in un posto sicuro. Le foto originali sono fuori dal forziere, quindi
non si perdono mai.

## I due computer e il telefono

Portare il lavoro su un altro PC, o preparare il pacchetto per il telefono,
passa sempre da una cartella che copi **tu**, per esempio su una chiavetta.
Né il lavoro né i pacchetti passano mai in rete. Il pacchetto per il telefono
è cifrato file per file.

## L'accesso dalla rete di casa

La finestra parla con un piccolo server che gira dentro il programma e che,
di suo, risponde **solo al tuo computer**. Da **Impostazioni** puoi lasciare
che anche altri dispositivi della rete di casa vedano l'archivio; anche così
risponde solo a quelli che approvi uno per uno. È spento finché non lo
accendi tu.
