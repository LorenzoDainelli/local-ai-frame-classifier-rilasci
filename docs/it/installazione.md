# Installazione

[← Indietro](../../README.it.md) · [English](../en/installation.md)

## Prima di cominciare

- Windows 10 (versione 1809 o più recente) o Windows 11, a 64 bit.
- Circa 2 GB liberi sul disco, circa 6 GB con una scheda video NVIDIA, più lo
  spazio per i modelli che deciderai di scaricare.
- La connessione a internet per il primo avvio.

La scheda NVIDIA è facoltativa. Senza, il programma usa il processore: è più
lento, ma i risultati sono gli stessi.

## Installa

1. Scarica l'ultimo installatore:
   **[local-ai-frame-classifier-2.0.0-beta.15.exe](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases/download/v2.0.0-beta.15/local-ai-frame-classifier-2.0.0-beta.15.exe)**.
   Le versioni precedenti sono nella [pagina dei rilasci](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases).
2. Doppio clic sul file.
3. Windows può mostrare **«PC protetto»**. Succede perché l'installatore non è
   ancora firmato digitalmente, non perché ci sia qualcosa che non va. Premi
   **Ulteriori informazioni**, poi **Esegui comunque**.
4. Scegli se vuoi l'icona sul desktop, poi premi **Installa**. Il programma si
   installa solo per il tuo utente, quindi non chiede mai la password
   dell'amministratore.

## Il primo avvio

Apri **Local AI Frame Classifier** dal menu Start.

1. Una finestrina esamina il computer e prepara i **motori** adatti a lui:
   circa 2,7 GB da scaricare con una scheda NVIDIA, circa 0,5 GB senza.
   Succede una volta sola, e intanto puoi fare altro.
2. Chiede una **chiave di Hugging Face**. È facoltativa: serve solo per i
   pochi modelli i cui autori la richiedono. Puoi saltarla e aggiungerla dopo
   da **Impostazioni**.
3. Si apre la finestra grande con una breve procedura guidata: cosa fa il
   programma e cosa non fa, in che cartella sono le foto, la prima
   importazione. Vedi [Primi passi](primi-passi.md).

## Controllare il file scaricato

Ogni rilascio contiene anche un file `.sha256` con l'impronta
dell'installatore. Per confrontarla apri PowerShell nella cartella dei file
scaricati e scrivi:

```powershell
Get-FileHash .\local-ai-frame-classifier-2.0.0-beta.15.exe
```

Il valore deve essere uguale a quello del file `.sha256`. È un passo
facoltativo: il programma controlla da solo l'impronta di ogni aggiornamento.

## Qualcosa non va?

- **L'installatore dice che il programma è aperto.** Chiudi Local AI Frame
  Classifier e riapri l'installatore.
- **Il primo avvio si è fermato mentre scaricava i motori.** Controlla la
  connessione e riapri il programma: ricomincia a scaricarli.
- Per tutto il resto: le [domande frequenti](domande.md), oppure
  [apri una segnalazione](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/issues/new/choose).
