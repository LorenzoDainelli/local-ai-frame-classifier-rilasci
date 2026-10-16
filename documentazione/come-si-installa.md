# Come si installa

## Con l'installatore

È il modo normale, e l'unico che serve a chi usa il programma.

**Cosa serve**

- Windows 10 (versione 1809 o più recente) oppure Windows 11, a 64 bit;
- circa 2 GB liberi sul disco senza scheda video NVIDIA, circa 6 GB con una
  NVIDIA, più lo spazio per i modelli che scegli di scaricare;
- la connessione a internet al primo avvio. Dopo si può lavorare anche a rete
  spenta.

La scheda video NVIDIA non è obbligatoria: senza, il programma usa il
processore ed è più lento.

**I passi**

1. Dalla pagina dei
   [rilasci](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases)
   si scarica l'ultimo `local-ai-frame-classifier-….exe`.
2. Doppio clic. La prima volta Windows dice «PC protetto», perché il file non
   è ancora firmato: si passa con **Ulteriori informazioni → Esegui
   comunque**.
3. L'installazione vale solo per il tuo utente e non chiede la password
   dell'amministratore. Mette l'icona nel menu Start e, se vuoi, sul desktop.
4. Al primo avvio una finestrina prepara i **motori** per la scheda video che
   trova: circa 2,7 GB da scaricare con una NVIDIA, circa 0,5 GB senza. Se
   trova l'archivio della versione 1 lo riprende, senza copiarlo.
5. Poi si apre la finestra grande, con la procedura guidata del primo avvio
   (vedi [Come si usa](come-si-usa.md)).

**Gli aggiornamenti** arrivano da soli. Finché il programma è in beta si
installano senza chiedere. Le versioni finali invece chiedono prima, con
**Aggiorna** o **Rifiuta**: quella rifiutata resta in sospeso in
*Impostazioni*, e da lì si installa quando vuoi.

**Per disinstallarlo** si va in *Impostazioni di Windows → App → App
installate → Local AI Frame Classifier → Disinstalla*. Il programma se ne va,
ma **l'archivio resta**, così una reinstallazione ritrova tutto. Per togliere
anche quello si cancella la cartella
`%LOCALAPPDATA%\Local AI Frame Classifier` e, se c'è, quella della versione 1,
`%LOCALAPPDATA%\Officina`. Le foto originali non sono mai state toccate e
restano dove sono.

## Dal codice sorgente

Per chi sviluppa, ed è com'era la versione 1.

### Cosa serve

- **Python 3.11 o più recente.** Su Windows si scarica da python.org; durante
  l'installazione va spuntato «Add Python to PATH».
- Nient'altro. Niente Node, niente npm, niente database da installare a parte
  (regola 15/19).

### Installazione

```bash
git clone <indirizzo del repository>
cd Local-AI-Frame-Classifier
pip install -r requirements.txt
python -m officina scorciatoia
```

Sette pacchetti, tutti con la versione fissata (regola 1). Si possono leggere
in `requirements.txt`: sono pochi apposta, perché in un progetto la cui base è
la privacy ogni dipendenza è codice di qualcun altro che gira sulle proprie
foto.

#### L'icona

`python -m officina scorciatoia` è l'ultima riga di comando che serve.

Mette l'icona dell'Officina sul desktop e nel menu Start, e da lì in poi il
programma si apre come si aprono gli altri programmi: doppio clic, e si apre
una finestra sua — senza barra degli indirizzi e senza schede — perché Chrome
ed Edge sanno già aprire una pagina come se fosse un'applicazione. Se non c'è
né l'uno né l'altro si apre il browser normale: è un ripiego, non un guasto.

**Il browser predefinito non viene guardato**, ed è voluto. Se il predefinito è
Firefox, l'icona apre lo stesso Edge: `--app=` è un'opzione di Chromium e
Firefox non ha niente di equivalente — con lui si otterrebbe una finestra di
browser qualunque, con barra degli indirizzi, schede e l'indirizzo
dell'Officina nella cronologia. Edge qui non fa il browser: fa la cornice. Apre
una finestra sola su `127.0.0.1`, non naviga da nessuna parte e si chiude
insieme al programma. Il predefinito torna a contare solo nel ripiego.

Non installa niente. Non serve essere amministratore, non tocca il registro di
sistema, e per disfarlo si cancella l'icona. Il collegamento punta a
`Officina.cmd`, dentro questa cartella: se sposti il programma, si rifà con lo
stesso comando.

Dietro la finestra ne resta una nera, ridotta a icona. Non è una dimenticanza:
se l'archivio è dentro un forziere, la password si scrive lì (regola 340).
Chiudendola, l'Officina si ferma.

#### I modelli, a parte

I due descrittori grandi, il decodificatore dei video e i modelli dei volti
pesano qualche GB e si installano **solo se si vogliono** (regola 74):

```bash
pip install -r requirements-modelli.txt
```

Le librerie sì, da qui: installare una libreria non si fa da una pagina web.
I **pesi** dei modelli invece si scaricano dal programma, dalla pagina
**Salute**: una riga per modello, con scritto da dove arriva, quanto pesa e con
che licenza, e accanto il tasto. Resta l'unico momento in cui il programma apre
una connessione, ed è dichiarato quanto lo era il comando: la regola 74 non
chiede che sia scomodo, chiede che sia voluto e visibile. Dopo, l'Officina
funziona a scheda di rete spenta.

Il comando c'è ancora, per chi preferisce:

```bash
python -m officina modelli --scarica tutti
python -m officina modelli --scarica volti
```

Senza, tutto il resto continua a funzionare: importazione, galleria, impronte e
misura girano con il descrittore disegnato a mano, che non è intelligenza
artificiale ma un conto sui colori e sui bordi. I dettagli stanno in
[I modelli](i-modelli.md).

Su Windows con una scheda NVIDIA, `torch` va preso dall'indice di PyTorch,
perché quello normale non contiene la versione con CUDA:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

Senza CUDA funziona lo stesso, sul processore, e sarà circa venti volte più
lento (regola 71).

### Controllo

```bash
python -m officina dottore
```

Dice cosa sa fare la macchina, e per ogni pezzo che manca dice il comando che
lo rimedia. Le righe che contano davvero:

- **legge HEIC** — senza, le foto dell'iPhone non si aprono (regola 51). Si
  risolve con `pip install pillow-heif`.
- **scrive AVIF** — senza, le foto arrivano al browser in JPEG invece che in
  AVIF. Funziona lo stesso, si vede appena peggio (regola 327).
- **numpy** — senza, si può guardare l'archivio ma non calcolare le impronte.
- **calcolo** — dice se ha trovato una scheda video o se lavorerà con il
  processore, che è circa venti volte più lento (regola 71).
- **i modelli** — quali sono già in casa e quali no.

In fondo dice anche, per ogni archivio, **quante impronte sono state calcolate
e con quale modello** (regola 43).

### Dove finiscono i dati

| Sistema | Cartella |
|---|---|
| Windows | `%LOCALAPPDATA%\Officina` |
| macOS | `~/Library/Application Support/Officina` |
| Linux | `~/.local/share/officina` |

Dentro ci sono due archivi separati, `reale` e `finto`, e non si toccano mai
(regola 341). In ciascuno: il database, le miniature, le copie di sicurezza e
i modelli.

Quanto occupa, per dare un ordine di grandezza su 1300 scatti: il database
qualche decina di megabyte, le miniature qualche centinaio, le impronte una
ventina (si conservano intere, quattro byte per numero — regola 172), i modelli
scaricati circa 5 GB. I modelli sono **l'unica di queste cose che si può
riscaricare invece che salvare**.

Si può spostare tutto altrove con la variabile d'ambiente `OFFICINA_ARCHIVIO`.

**Le foto restano dove sono.** Il programma non le sposta, non le copia e non
le modifica mai (regola 2).

### Il blocco prima dei commit

Chi modifica il codice deve installarlo una volta sola:

```bash
python strumenti/blocco_commit.py --installa
```

Da quel momento rifiuta automaticamente immagini, video, database e file che
contengono parole vietate (regola 110). L'elenco delle parole vietate — i nomi
veri dei nodi, il nome della cartella delle foto, i nomi delle persone — si
scrive in `parole-vietate.txt` **dentro la cartella dell'archivio**, mai nel
repository: scriverlo qui sarebbe esattamente la cosa che si vuole impedire.

### Sui due computer

Il programma gira sul fisso, insieme al database e (più avanti) alla scheda
video. Lo ZenBook apre la pagina sulla rete di casa ed è solo una finestra
(regola 187).

Sul fisso si accende «Accesso dagli altri computer di casa» in *Impostazioni →
Sicurezza* e si riavvia il programma. Dallo ZenBook si apre l'indirizzo scritto
lì sotto, `https://<indirizzo-del-fisso>:8443`: la prima volta il browser avvisa
del certificato fatto in casa, e si confronta l'impronta SHA-256 con quella delle
impostazioni; poi lo ZenBook mostra un codice di sei cifre che si scrive sul fisso
per approvarlo. I passi sono in [come si usa](come-si-usa.md#lavorare-dallo-zenbook).

Con l'interruttore spento il programma risponde soltanto al computer su cui gira
(regola 190), e lì solo alla sua finestra; acceso, accetta solo gli indirizzi
della rete locale, solo cifrato e solo dai dispositivi approvati col codice
(regola 189). Anche `python -m officina avvia --rete` dal terminale fa lo
stesso: la porta in chiaro resta solo per questo computer e per la rete apre
quella cifrata, `:8443`.

#### Quando lavorano tutti e due per conto loro

Se lo ZenBook esce di casa e si etichetta anche da lì, i due archivi si
riallineano con una chiavetta e non con la rete (regola 403). La prima volta
ogni computer si dà un nome:

```bash
python -m officina sincronizza --chiamami "il fisso"
```

Poi, ogni volta che ci si rivede:

```bash
python -m officina sincronizza --dove D:\Scambio        # fanne uno da portare
python -m officina sincronizza --applica D:\Scambio\da-lo-zenbook
```

Da **Dispositivi › Altro computer** si fa lo stesso con due tasti, e la cartella
si sceglie una volta sola. Tutti i dettagli in
[La sincronizzazione](la-sincronizzazione.md).
