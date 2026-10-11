# Come si usa

## Il giro completo, la prima volta

Doppio clic sull'icona dell'Officina. Non serve altro: si apre una finestra, e
la prima volta — e solo quella — dentro c'è una procedura guidata in sei
passi, uno per pagina (regole 86, 136, 488).

| | | |
|---|---|---|
| **1 · il computer** | cosa fa e cosa non fa; i controlli che la macchina regga; la password | due minuti a leggerlo |
| **2 · la chiave** | come si fa la chiave di Hugging Face e dove incollarla; il passo per LucidFlux | si può saltare |
| **3 · i modelli** | quali ci sono e quanto pesano, «Scarica quello che manca» | LucidFlux ha il suo tasto |
| **4 · la cartella** | dove sono le foto; il programma conta e dice cosa ha trovato | il tasto che comincia compare **dopo** il conto (regola 274) |
| **5 · l'elaborazione** | importa, e le miniature vere compaiono mentre lavora; le impronte | si può chiudere a metà |
| **6 · il tutorial** | il giro sulle foto finte con la fotina, poi il primo scatto da etichettare | si esce quando si vuole |

**Il tutorial.** Una piccola foto con due occhi, nell'angolo in basso a
destra, porta in sette tappe per le schermate vere: la ricerca, i filtri,
l'etichettatura, la pagella, il miglioramento, le impostazioni. A ogni tappa
parla in una nuvola, e il pezzo di cui parla si illumina d'arancio. Si va
avanti, indietro, si fa rispiegare o si esce. L'ultima tappa lascia i tasti
da ricordare. Gira su un archivio finto a parte: il tuo non si tocca.

Per la chiave di Hugging Face: su `huggingface.co/settings/tokens` si crea una
chiave di tipo **Read** (se si sceglie «Fine-grained», va spuntato *Read
access to contents of all public gated repos you can access*). Per LucidFlux,
una volta sola, su `huggingface.co/black-forest-labs/FLUX.1-dev` si preme
**Agree and access repository**.

Non c'è niente da copiare in un terminale.

La guida si riapre dal menu Stato › La guida, oppure dalle Impostazioni.

### 1. Prova sul finto

Prima di dare al programma le proprie foto conviene fargli fare tutto il giro
su un archivio che non esiste (regole 158, 341):

```bash
python -m officina finto ~/archivio-finto --quanti 120
python -m officina importa --finto ~/archivio-finto
python -m officina avvia --finto
```

L'archivio finto contiene apposta i casi difficili: live photo, video lunghi,
schermate, foto senza data, doppioni e file rotti. Serve a vedere come si
comporta il programma quando le cose non sono in ordine — che è la metà del
lavoro.

### 2. Poi sul vero

```bash
python -m officina avvia
```

Nella pagina **Importazione**: si aggiunge la cartella delle foto, si preme
*Conta i file*, si guarda cosa ha trovato e quanto ci metterà, e solo allora si
preme *Comincia* (regola 274).

Da quel momento la griglia si riempie sotto gli occhi (regola 275). Non è solo
bello da vedere: è il modo più rapido di accorgersi di aver dato la cartella
sbagliata — una barra al 12% non lo direbbe mai.

Si può chiudere tutto a metà. Alla riapertura riprende dal file dopo
(regole 48, 277).

## Le schermate

### Galleria

Ogni scatto è una scheda con sotto le sue etichette: **piene** quelle
confermate da te, **a contorno** quelle proposte dal programma (regola 18).
Se dice «nessuna», quello scatto è da fare.

- **clic** apre lo scatto;
- **Maiusc+clic** seleziona un intervallo, **Ctrl+clic** aggiunge o toglie,
  **Ctrl+A** prende tutto, **Esc** lascia (regola 121);
- **barra spaziatrice** ingrandisce senza perdere il posto (regola 161).

I filtri stanno nella colonna a sinistra — o a destra, o in una barra in alto:
si sceglie nelle impostazioni (regola 298). Ogni voce porta accanto **quanti
scatti darebbe** (regola 302), e quel numero vuol dire sempre la stessa cosa:
*quanti ne vedresti se la aggiungessi adesso* (regola 330). Uno zero si vede
prima di cliccarlo.

I filtri attivi sono sempre scritti sopra la griglia e non si possono
nascondere (regola 299): una griglia vuota senza sapere quale filtro l'ha
svuotata è il modo più comune di perdere fiducia in un programma del genere.

### Da guardare

Tutto quello che il programma ha notato e ha lasciato decidere a te:

- **non importati** — file che non si sono aperti, con scritto perché e un
  «riprova» per ciascuno (regole 53, 279);
- **senza data** — la data si legge solo dai metadati, mai da quella del file
  (regola 83); questi si sistemano a mano o restano così;
- **sembrano schermate** — misura esatta di uno schermo e nessun dato di
  scatto. Una domanda sola, mai un'azione automatica (regola 321);
- **doppioni** — lo stesso file in due cartelle è un solo scatto con due
  percorsi (regola 135);
- **doppioni ricompressi** — la stessa fotografia tornata da WhatsApp o da
  un'email: stessa immagine, byte diversi. Per il contenuto sono due file, e
  restano due file; il programma però sa dire che sembrano la stessa, e lo
  propone senza cancellare niente. Riconosce le ricompressioni, i
  ridimensionamenti e i cambi di formato; **non** riconosce un ritaglio o una
  rotazione, e non è una mancanza: una foto ritagliata è un'altra fotografia.
  I video non ce l'hanno — farla vorrebbe dire decodificarli;
- **coppie incerte** — un video che potrebbe appartenere a una foto ma con un
  indizio solo. Meglio una domanda che un errore silenzioso (regola 11).

### Senza data

Gli scatti che non hanno una data nei metadati (regola 83) finiscono qui, e
questo elenco resta finché non si svuota — o anche per sempre, perché «senza
data» è una risposta legittima (regola 87).

Per ognuno il programma **propone** una data e dice sempre da dove l'ha
ricavata: «gli scatti IMG_1023 e IMG_1025, subito prima e subito dopo nella
stessa cartella, sono tutti e due dell'8 settembre 2021». Quando i due vicini
non concordano lo dice e non insiste (regola 11): una data proposta senza il
motivo sarebbe una data inventata.

Si può anche mettere una data sola a tutti in blocco («questi 12 sono tutti del
3 luglio 2024»), o lasciarli senza data — che li toglie dall'elenco senza
toglierli dall'archivio.

### Correzioni in blocco

Nella galleria: si filtra, si seleziona, si agisce (regola 47). Sopra la
griglia compare **«seleziona tutti gli 84 risultati»**, che è diverso da
Ctrl+A — quello prende solo quelli già caricati (regola 305).

Le azioni sono quattro: mettere e togliere fuori archivio, dare una data, e
**mettere o togliere un nodo** su tutta la selezione. Il nodo si cerca con la
stessa barra dell'etichettatura.

«Togli» riporta a *non ancora deciso*, **non** a «no» (regola 55). Dire di no è
una decisione, e in blocco non si prendono decisioni: non c'è un tasto per
farlo, ed è voluto.

### Etichetta

Il giro della tappa 3 (regola 337), ed è la schermata dove si passa il tempo:
guardo uno scatto, decido, passo al successivo. La pagina non si ricarica mai
fra uno scatto e l'altro.

A sinistra lo scatto, che prende tutto lo spazio. `L` accende la live photo;
sotto i video c'è la striscia dei fotogrammi, e si clicca (regola 124).

A destra la colonna dove si decide:

- **le confermate** sono pillole piene, **le proposte** a contorno: mai un
  colore (regole 18, 21). Ogni pillola porta il proprio tasto, e i tasti li
  decide il programma — così l'ordine sullo schermo e l'ordine dei tasti non
  possono scollarsi (regola 23);
- **il filo** separa le proposte in cui il nodo crede da quelle in cui non
  crede. Non è una percentuale: è la soglia del singolo nodo (regola 333),
  perché il «70%» di un nodo e quello di un altro non vogliono dire la stessa
  cosa;
- **il perché** è un fatto controllabile: «assomiglia a 5 scatti che hai
  confermato», e quei cinque sono miniature che si aprono (regola 56);
- **la barra** cerca e crea insieme, e cambia comportamento solo quando cambia
  il rischio: se non c'è niente con cui confondersi, Invio crea; se c'è
  qualcosa che somiglia, Invio sceglie e creare diventa il tasto `+`
  (regole 118, 133, 159);
- **il riquadro dell'albero** in fondo dice dove sei: aperto il ramo in uso,
  chiusi gli altri (regola 238).

I tasti: `0-9` applica o toglie, `← →` cambia scatto, `spazio` salta, `L` live
photo, `/` cerca, `Ctrl+Z` annulla un passo, `A` apre l'albero.

### Albero

La mappa (regole 202-241). **La disposizione la decide il programma, sempre**:
trascinare significa una cosa sola, *cambia posto nell'albero* (regola 204).
Non esiste «sposta più a destra perché mi piace», e per questo l'albero non può
diventare disordinato.

I bersagli del trascinamento sono **due**, e i nodi non sono fra questi
(regola 213):

- il **quadratino col `+`** appeso a un nodo lo fa diventare suo figlio
  (regola 209); quello in fondo alla prima colonna lo porta a primo livello
  (regola 239);
- il **filo** lo incastra in mezzo, e scende **solo quel figlio**: gli altri
  restano dove sono (regola 211).

Mentre trascini si vedono solo le mosse possibili, compreso il ramo che stai
spostando che si spegne — non può contenere se stesso (regola 214). Alla fine
una finestrella attaccata al nodo chiede conferma, con dentro tutte e due le
domande — dove va, e se porta i figli — e la frase che risponde alla paura
vera: **le foto già etichettate non si toccano** (regole 218, 219, 220).

`Ctrl+Z` annulla per tutta la sessione, un passo alla volta, e `Ctrl+Y` rifà
(regola 226). Ogni riorganizzazione lascia una **fotografia dell'albero**,
ripristinabile dalle impostazioni (regola 227): contiene la forma e mai le
etichette.

Il pannello a destra dice **come sta** un nodo, non solo cosa è (regola 229):
esempi, quanto ci azzecca, con quali altri nodi lo confonde, ultimi scatti. Da
lì si rinomina (senza conferma: rinominare è sempre sicuro, regola 225), si
sposta a parole con `S` (regola 217), si unisce a un altro (regola 222) e si
archivia (regola 224).

In basso a sinistra il conto degli **scatti senza etichetta**, che ci riporta a
etichettarli (regola 235). In basso a destra, dopo uno spostamento, compare
«N nodi cambiati — riaddestra»: il riaddestramento viene **segnalato, non
lanciato** (regola 228).

### Pagella

Serve a una cosa sola: far sapere **cosa etichettare adesso** perché migliori
il più possibile, invece di etichettare a caso (regola 49). Tre strati, in
quest'ordine:

1. **la coda** — cose da fare, in ordine di quanto rendono. La prima riga è già
   la risposta, e ogni riga porta con sé il collegamento che ti ci manda;
2. **le corsie** — da nutrire, in crescita, in salute, ognuna con la frase che
   spiega perché un nodo sta lì. È l'unica delle tre che dice anche **dove non
   lavorare**;
3. **l'elenco** — tutti i nodi, tutti i numeri. È l'unico posto in cui ci si
   accorge se le stime qui sopra stanno mentendo.

Un nodo con troppo pochi esempi non riceve un voto ma la scritta «troppo pochi
esempi per dirlo», col numero grezzo accanto (regole 244, 245). All'inizio
quella scritta sarà su quasi tutte le righe: è il comportamento corretto, e la
regola 338 lo aveva previsto.

### Persone

I volti (tappa 5, regole 284-295). Prima si guarda l'archivio, e si fa da qui:
se i modelli dei volti non sono ancora in casa la pagina lo dice e li scarica
con un tasto — sono due file, in tutto una quarantina di megabyte — poi
**Cerca le facce** guarda una foto alla volta, con la barra e il tasto per
fermarsi. Si può fermare e riprende da dove era (regola 48).

Alla fine raggruppa da sola, perché costa un attimo: nessuno vorrebbe premere
un secondo tasto per una cosa che sarebbe successa comunque (regola 293). E se
non trova niente lo spiega lì — quanti riquadri ha proposto il modello e dove
sono finiti — invece di lasciare uno zero senza motivo.

Da riga di comando è lo stesso lavoro: `python -m officina volti`.

Poi il **mazzo dei nomi**: un gruppo alla volta, a schermo pieno, dal più
grande al più piccolo — i primi cinque minuti coprono quasi tutto l'archivio, e
si può smettere quando si vuole (regole 284, 285).

Di ogni gruppo si vedono i **volti più diversi fra loro**, non i più belli
(regola 286): i volti nitidi sono la parte migliore del gruppo e nascondono gli
errori. Si guardano foto brutte per potersi fidare di duecento foto belle.

- **Saltare** vuol dire «non adesso»: il gruppo torna in fondo al mazzo e resta
  utilizzabile come filtro (regole 82, 287). Per dire «non m'interessa» c'è una
  scelta separata (regola 46);
- un **nome già esistente** fa una domanda, non un'unione: «esiste già un
  Marco, 84 scatti. È lui?» (regola 290);
- i **forse-doppioni** non interrompono mai: vanno nel cassetto e si guardano
  quando si ha voglia, una coppia per volta (regole 288, 289). «Non so»
  rimanda in fondo e non cancella;
- un volto che non è suo si toglie e diventa un gruppo nuovo senza nome
  (regola 291); nessun volto viene cancellato;
- una persona si può mettere **a mano** su uno scatto dove una faccia non c'è —
  di spalle, di lontano, coperta. Il filtro la trova, e quello scatto non
  insegna niente a com'è fatto quel volto (regola 294).

I ritagli dei volti non finiscono mai su disco: si tagliano al volo
dall'originale, e il browser ha l'ordine di non tenerli in cache.

### Cerca

La ricerca a parole (regole 58, 137). Un campo solo e **due sorgenti**: quello
che hai etichettato tu, che è certezza, e quello che il modello crede di
riconoscere, che è un'ipotesi. Ogni risultato dice da dove viene.

I pezzi della frase che sono tuoi — nodi, persone, anni — vengono riconosciuti
e **restringono** insieme: «nodo_3 nel 2021» vuol dire tutti e due.

Sotto una certa soglia il programma **dice di no** invece di riempire lo
schermo: un motore di somiglianza ordina *tutte* le foto dalla più vicina alla
meno vicina, quindi un «nessun risultato» non esiste in natura e va deciso. I
tentativi restano lì, richiudibili.

La sicurezza si legge in **tre livelli, mai in percentuali** (regola 58).

**I risultati arrivano in due tempi** (regola 266). Le foto compaiono subito,
sulla frase com'è stata scritta. Intanto il modello linguistico locale la
traduce in inglese e la riscrive in due o tre modi (regole 137, 268), e quando
ha finito la lista si riassesta: sotto la riga «cerco» compare *chiesto anche
come*, con le frasi che ha usato e da dove vengono.

Quella seconda riga sta **sotto** e non in fila con le pillole, apposta: le
pillole sopra sono cose tue — una persona, un anno, un nodo — mentre quelle
frasi le ha scritte un modello, e le due cose non devono somigliarsi.

Chi non ha scaricato il modello linguistico ha solo il primo tempo, e la riga
lo dice: *forme fisse*. Si trova un po' meno, e niente si rompe.

### Misura

La schermata della tappa 2 (regole 105, 336). Tre riquadri, nell'ordine in cui
servono: **le impronte** (il passo pesante, una volta sola), **le tue
decisioni** (un centinaio di scatti divisi in due o tre mucchi, dal banco), e
**il confronto**, che scrive un rapporto fatto solo di numeri.

Il banco è uno scatto grande e i mucchi numerati: si preme il numero, e basta.
Lo **0** vuol dire «nessuno di questi» — un «no» detto, che vale quanto un «sì»
(regola 56); la **S** salta e lascia indeciso, che non è un «no» (regola 55).

Il trucco che dimezza il lavoro sta nella regola 129: se i mucchi si escludono a
vicenda, si creano dentro un **ramo «scegline uno»** e da quel momento ogni
scelta regala un «no» a tutti gli altri.

Tutti i dettagli in [La misura](la-misura.md).

### I video

La miniatura di un video adesso c'è davvero, per le due strade che il programma
conosce: direttamente se il video è fatto di JPEG, con il decodificatore se è
installato. Se non si può fare, la scheda dice «video» e la durata e non finge
(regola 89).

Sotto un video, la **striscia dei fotogrammi** (regola 124): non istantanee a
intervalli fissi, ma i momenti in cui la scena cambia davvero (regola 41).
Cliccandone uno la lastra grande lo mostra. Sono gli stessi momenti su cui sono
state calcolate le impronte, quindi la striscia dice anche *cosa ha guardato il
programma* — e nessuno di quei fotogrammi esiste su disco: si legge dal video
quando lo si guarda, come una foto HEIC diventa AVIF solo perché in mezzo c'è
un browser (regola 327).

La striscia compare dopo aver calcolato le impronte.

E per i video che il browser non sa aprire — quelli dell'iPhone, in HEVC —
adesso c'è **«Preparane una copia che si vede»** (regola 89). La copia si fa
quando la chiedi, non a tappeto: ricodificare tutto l'archivio sarebbe giorni
di macchina per dei video che magari non riaprirai mai, e quello che si
ricodifica è il video che stai guardando. Da lì in poi c'è, e il video si apre
come tutti gli altri.

Tre cose da sapere, e sono le tre che contano:

- **l'originale non viene toccato né sostituito**, mai. La copia sta nella
  cache accanto alle miniature: si butta quando vuoi e si rifà da sola;
- **la copia è peggiore dell'originale**, perché ricodificare butta via
  qualcosa. Serve a guardare, e basta: le impronte, i fotogrammi e il travaso
  verso il telefono continuano a leggere il file vero;
- serve il decodificatore (`pip install -r requirements-modelli.txt`), che è lo
  stesso che serviva già per i fotogrammi dei video. Se non c'è, la pagina lo
  dice invece di mostrare un tasto che non fa niente.

### Chi gli somiglia

Da ogni scatto (regola 16). Mostra i più vicini secondo l'impronta, con le
pillole per cambiare descrittore e inquadratura. Vale la pena guardarla anche
senza misurare niente: se i dieci più simili non c'entrano niente, nessuna
percentuale lo direbbe meglio.

### Salute

Un rapporto fatto solo di numeri (regola 112): quanti scatti, quante coppie
live, quanti file non trovati sul disco, quanto occupano le miniature e le
impronte, e l'elenco delle copie del database con la data. Non contiene nessun
nome di file, nessuna etichetta e nessun nome di persona: si può guardare e
mostrare senza pensarci.

C'è anche **l'elenco dei modelli**: uno per riga, con scritto a cosa serve, da
dove arriva, quanto pesa e con che licenza (regola 177), e accanto il tasto che
lo scarica se non c'è. È l'unico punto del programma che apre una connessione,
ed è dichiarato quanto lo era il comando: la riga dice cosa sta per succedere e
non parte finché non la premi tu (regola 74).

Il gettone di chi distribuisce i modelli — quelli che prima di lasciarsi
scaricare chiedono di accettare le loro condizioni — non è un campo di questa
pagina, ed è voluto: un gettone è una password, e si legge dalla variabile
d'ambiente `HF_TOKEN` come nel comando.

E c'è la tabella di **con quali modelli sono state calcolate le impronte**
(regola 43). È quella che rende possibile cambiare descrittore fra due anni: si
buttano via le impronte, si ricalcolano in una notte, e le etichette non se ne
accorgono perché sono attaccate agli scatti.

### Dispositivi: il telefono

È la voce **Dispositivi** della barra (regole 384 e 494), e da qui esce il pacchetto per il
Visore. Un telefono si aggiunge con il nome che si vuole — «iPhone», «Redmi» —
e da quel momento ha la sua cartella, il suo registro e la **sua** selezione:
iPhone e Redmi non si toccano mai.

La selezione parte da **tutto l'archivio** e si toglie (regola 360), perché è il
verso in cui si ragiona: «tutto tranne i video del 2015», non «aggiungi il 2019,
aggiungi il 2020, aggiungi...». Si sceglie per periodo, per ramo dell'albero — e
i figli seguono — e per persona, anche al contrario: *tranne le foto in cui c'è
X*, che è quello che serve prima di prestare il telefono a qualcuno.

**Non c'è un tasto «salva»** (regola 385): quello che si spunta è già salvato, e
fra sei mesi si ritrova com'era. A ogni spunta il conto nella colonna di destra
si rifà — quanti scatti, quanto pesano, quanti sono video e quanto pesano loro,
che periodo coprono — e sopra il tasto compaiono tutti gli avvisi: *non ci sta
per 5 GB*, *tolgo 1.204 foto*, *questo telefono ha ancora la password
precedente*. Il tasto dice cosa fa: «Prepara 28.740 scatti (41 GB) per iPhone».

Il primo travaso dura ore. Va avanti da solo mentre si cambia schermata, con una
fascia in alto che lo dice da qualunque pagina, e si può fermare: quello che ha
scritto resta, e al giro dopo riprende da lì (regole 191, 370). Alla fine
rilegge tutto e confronta le impronte, che è l'unico momento in cui ci si può
accorgere di un disco che sbaglia.

Poi **il cavo lo colleghi tu** e la cartella la copi tu: il programma non tocca
il telefono e non sa niente di driver (regola 368).

In fondo alla schermata c'è quello che il telefono ha riportato indietro —
preferiti e raccolte, l'unica cosa che il telefono possiede (regola 68) — e **il
diario**: dove, quando, per quanto e su quante foto hai usato il Visore
(regola 381). Le coordinate diventano il nome di un luogo dell'archivio quando
ce n'è uno abbastanza vicino, altrimenti restano numeri; nessuna richiesta esce
da questo computer per tradurle. Il diario si guarda e basta: il programma non
offre nessun modo di cancellarlo, e la
[guida della dismissione](dismissione.md) dice cosa lo porta via davvero.

Sul telefono, per adesso, non c'è ancora niente da aprire: le due app non sono
scritte. Quello che c'è è **il lettore del pacchetto in Kotlin** — la lingua
dell'app Android — che fa esattamente i passi che farà l'app, e che serve a
sapere che il pacchetto costruito qui si apre davvero da un'altra parte
(regola 386). Sta in [`visore/`](../visore/LEGGIMI.md) e non serve saperlo per
usare l'Officina.

### Dispositivi: l'altro computer

Sta nella stessa pagina del telefono, dietro «Altro computer», e stanno insieme
apposta: sono la stessa cosa fatta con l'altro cavo. Di là un pacchetto che
esce verso il telefono, di qua un pacchetto che va avanti e indietro fra il
fisso e lo ZenBook (regole 403-411).

Si sceglie **una volta sola** la cartella dove si scrivono e dove si vanno a
cercare i pacchetti — la chiavetta, di solito — e da quel momento la pagina se
la ricorda.

Poi ci sono due metà. A sinistra **farne uno da portare di là**: un tasto, e
dentro finisce solo quello che l'altra macchina non ha già visto. A destra
**quelli arrivati**: l'elenco dei pacchetti che ci sono nella cartella, con
scritto da quale computer vengono, di quando sono e quanti gesti portano.

Quell'elenco si legge **senza password**: si guarda solo la carta d'identità
del pacchetto, che non dice una parola su cosa c'è dentro l'archivio
(regola 106). La pagina si disegna anche col forziere chiuso.

Un pacchetto di un altro archivio non ha il tasto per applicarlo. Non è un
errore che compare dopo aver premuto: è un tasto che non c'è.

Mentre lavora si vede a che punto è, e alla fine dice cosa è cambiato in
parole: quante etichette, quanti nodi, quante persone hanno preso un nome,
quanti cuori sono arrivati. Se dalla fusione sono usciti due mucchi di volti
che potrebbero essere la stessa persona, la pagina lo dice e porta al
**cassetto**, dove si guardano affiancati — il programma segnala, non unisce
(regola 69).

Le stesse cose da terminale, per chi preferisce:

```bash
python -m officina sincronizza --chiamami "il fisso"
python -m officina sincronizza --dove D:\Scambio
python -m officina sincronizza --guarda D:\Scambio\da-il-fisso
python -m officina sincronizza --applica D:\Scambio\da-il-fisso
```

## Lavorare dallo ZenBook

Sul fisso si lancia `python -m officina avvia --rete` e si accende
l'interruttore nelle impostazioni.

Poi si apre `http://<indirizzo-del-fisso>:8080` sullo ZenBook. **La prima volta
non funziona**, ed è voluto: il programma registra chi ha bussato e lo respinge
(regola 189). Si torna sul fisso, in *Impostazioni → La rete*, e si dice «sono
io». Da quel momento passa.

Chi non è approvato non riceve una schermata di accesso: riceve un no. È la
differenza fra «protetto da password» e «invisibile» — e vale per l'ospite
sulla Wi-Fi come per la lampadina intelligente.

## I comandi

```bash
python -m officina avvia [--rete] [--porta 8080] [--non-aprire] [--finto]
python -m officina scorciatoia
python -m officina importa CARTELLA... [--solo-conta] [--finto]
python -m officina impronte [--descrittore NOME] [--tutti] [--quanti N]
                            [--intensita 50] [--fotogrammi] [--rifai] [--finto]
python -m officina misura [--scrivi FILE] [--scene CARTELLA] [--finto]
python -m officina modelli [--scarica tutti|volti] [--verifica] [--togli NOME]
                           [--rifai] [--chiave GETTONE] [--repo NOME]
                           [--repo-rilevatore NOME] [--repo-riconoscitore NOME]
                           [--file-rilevatore NOME] [--file-riconoscitore NOME]
                           [--finto]
python -m officina volti [--quanti 50] [--intensita 50] [--raggruppa-e-basta]
                         [--finto]
python -m officina doppioni [--quante N] [--solo-gruppi] [--finto]
python -m officina forziere [--accendi] [--spegni] [--stato] [--finto]
python -m officina finto DOVE [--quanti 120] [--leggero] [--seme N]
python -m officina dottore
python -m officina copie [--adesso] [--ripristina NOME] [--finto]
python -m officina pacchetto [--telefono NOME] [--dove CARTELLA] [--nuovo]
                             [--solo-conta] [--spazio] [--sistema] [--finto]
python -m officina leggi-pacchetto CARTELLA [--verifica] [--quanti N]
                                   [--scatto N] [--tira-fuori FILE]
python -m officina sincronizza [--dove CARTELLA] [--per NOME] [--chiamami NOME]
                              [--finto]
python -m officina sincronizza --guarda CARTELLA
python -m officina sincronizza --applica CARTELLA
```

Quasi tutti prendono `--finto` per lavorare sull'archivio finto invece che sul
proprio (regola 341). Quattro no, e per lo stesso motivo: non aprono un
archivio. `finto` lo **costruisce**, `dottore` guarda la macchina e non
l'archivio, `scorciatoia` mette un'icona sul desktop, e `leggi-pacchetto`
legge una cartella che gli si indica.

**Per usare il programma non serve nessuno di questi.** Sono per chi lo
installa, lo aggiorna o lo ripara: si apre con l'icona, e cartelle,
importazione, impronte, modelli, volti e i pacchetti fra i due
computer si fanno dalle pagine. `avvia` si apre
la finestra da solo; `--non-aprire` serve a chi lo lancia da uno script o lo
tiene acceso su una macchina senza nessuno davanti.

**`modelli --scarica` è l'unico comando del programma che apre una
connessione**, ed è dichiarato apposta (regola 74). Fuori da lì l'Officina
funziona a scheda di rete spenta.

## Il forziere

L'archivio può stare dentro un contenitore cifrato: senza la password, sul
disco c'è rumore (regole 331, 340).

```bash
python -m officina forziere --stato      # com'è messo
python -m officina forziere --accendi    # da qui in poi «avvia» chiede la password
python -m officina forziere --spegni     # torna una cartella in chiaro
```

Si accende **a mano, guardandolo**, ed è voluto: è la cosa più irreversibile
del programma. **Non esiste un «password dimenticata»** — se ci fosse una via
di recupero, quella via sarebbe anche la via di chi non deve entrare
(regola 106). Le foto originali restano fuori dal forziere: perdere la password
vuol dire perdere il lavoro di catalogazione, mai le fotografie.

Il momento giusto per accenderlo è quando ci sono le prime etichette vere:
prima c'è solo roba che si rifà in una notte, dopo ci sono mesi (regola 340).
Tutti i dettagli in [Come funziona dentro](come-funziona-dentro.md#il-forziere).

## Le copie di sicurezza

Il database viene copiato **a ogni chiusura** e la copia viene subito riaperta
e controllata (regole 42, 131). Se ne tengono trenta.

Per tornare indietro:

```bash
python -m officina copie                       # elenca, con la data
python -m officina copie --ripristina NOME     # riporta tutto a quel momento
```

Prima di ripristinare, il programma mette da parte lo stato attuale: anche il
ripristino si annulla (regola 168).

## Quello che il programma non fa mai

- **non tocca gli originali** — né li modifica, né li sposta, né li rinomina
  (regola 2);
- **non apre connessioni** — nessun font, nessun aggiornamento cercato, niente
  (regole 1, 320). L'unica eccezione è `modelli --scarica`, che si scrive
  apposta e si vede dal nome (regola 74);
- **non cancella niente da solo** — segnala e lascia decidere (regole 2, 280);
- **non manda notifiche fuori dal programma** (regola 78).

## Migliorare foto e video piccoli

Nella galleria seleziona le foto o i video e premi **Migliora** (oppure
**Migliora** nella pagina di una foto). Vanno in **Lavoro › Miglioramento**:
lì premi **Avvia**, e il computer li porta a FHD uno alla volta. Serve
SeedVR2, che si scarica da **Stato › La salute**.

Quando sono pronti, **Rivedi** mostra l'originale a sinistra e la migliorata a
destra: con la rotella ingrandisci, trascinando ti sposti, e i due lati si
muovono insieme. **Approva** (A) mette la migliorata al posto dell'originale,
che va nella cartella `Originali` accanto; **Rifiuta** (R) cancella la copia;
**Dopo** (freccia a destra) la lascia per la fine. Nei video i due lati
partono e si fermano insieme, e scegli da quale sentire l'audio.

### La sfida alla cieca fra SeedVR2 e LucidFlux

LucidFlux è un secondo modello per le foto: inventa più dettaglio di SeedVR2.
Si scarica a parte da **Stato › La salute** (circa 30 GB). Prima bisogna
accettare una volta la licenza di FLUX.1-dev sul sito di Hugging Face: se
manca, il programma lo dice e dà la pagina giusta.

Con tutti e due sul computer, le prime 100 foto che migliori le fanno
entrambi. In **Lavoro › Miglioramento** compare il riquadro «Sfida alla
cieca»: premi **Vota** e vedi tre riquadri uguali, l'originale al centro e le
due versioni ai lati, chiamate solo A e B. Rotella e trascinamento muovono
tutti e tre insieme; **L** apre sotto una lente ×4 sul punto del mouse.

Si vota con **1** (A), **2** (B), **3** (Pari) e **4** (Nessuna delle due).
Votare non tocca il disco: la versione scelta passa in «Da rivedere», dove si
approva come sempre. «Nessuna» cancella le due versioni. «Pari» aspetta la
fine. Alla fine premi **Com'è andata**: vedi i nomi, il conteggio, e scegli
quale modello usare da lì in avanti per le foto.
