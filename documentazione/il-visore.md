# Il Visore

Il secondo programma del progetto: quello che sta sul telefono e serve a
guardare (regole 6, 250). Non etichetta, non addestra niente, non fa girare
nessun modello. Riceve dal PC un pacchetto cifrato via cavo, e da lì in poi vive
da solo, senza rete, per sempre (regole 7, 358).

## A che punto è

Questa guida descrive un programma che **non esiste ancora**, tranne una metà:
il lettore del pacchetto, che in Kotlin c'è. È scritta prima perché le decisioni
ci sono già tutte — sono le regole 356-383, più le quattro nate scrivendo il
lettore (386-389) — e perché chi scriverà le schermate, fra un mese o fra un
anno, deve trovarle raccontate una volta invece che sparse in trentadue regole.

| Pezzo | Stato |
|---|---|
| Le decisioni (regole 356-383) | **fatte** |
| Il pacchetto: formato, cifratura, costruzione, sul PC | **fatto** |
| Il telefono finto che lo rilegge (regola 383) | **fatto** |
| Le bozze delle otto schermate (regola 180) | **guardate**: otto scelte su otto (regole 392-401) |
| La schermata «Telefono» dell'Officina | **fatta** |
| Il lettore del pacchetto in Kotlin (regola 386) | **fatto** |
| Quello che il telefono scrive: cuori, raccolte, diario (regole 390, 391) | **fatto**, in Kotlin |
| Le schermate dell'app Android | **tutte e otto** dicono già cosa mostrare; manca il disegno, che vuole Android Studio ([come-si-costruisce-l-app.md](come-si-costruisce-l-app.md)) |
| L'app iOS | non cominciata, e richiede prima una VM macOS (regola 14) |

Il pacchetto si costruisce **già adesso**, da riga di comando, e si riapre col
telefono finto:

    python -m officina pacchetto --nuovo iPhone --sistema ios
    python -m officina pacchetto --telefono iPhone --dove D:\Visore-iPhone
    python -m officina leggi-pacchetto D:\Visore-iPhone --verifica

Le otto schermate esistono come **bozze da guardare**, non come codice:

    sviluppo/bozze/visore/indice.html

Si aprono con un doppio clic. Ogni schermata è disegnata alle due misure vere —
375 × 667 e 430 × 932 — con dentro l'archivio finto, e ognuna porta in fondo
**una decisione con tre bozze** (regola 180): la scelta si fa guardando, e
quando è fatta diventa una regola con un numero.

**Sono state prese tutte e otto**, e sono le regole 392-399 e 401. Due delle
prime sette non hanno scelto nessuna delle tre bozze: hanno preso quello che il
sistema fa già — l'intestazione del giorno e il posto del cuore — e da lì è nata
la regola 400, che dice quando si copia il sistema e quando invece si sceglie.
L'ottava, dove sta l'interruttore «solo qui», è tornata indietro una volta: le
prime tre bozze non andavano, e la scelta è stata fatta su altre tre.

Le bozze lasciate restano dove erano, spente, con scritto perché: una decisione
senza le alternative che aveva davanti non si può più rileggere.

E **il lettore del pacchetto esiste anche in Kotlin**, cioè nella lingua
dell'app Android (regola 386):

    gradle -p visore test

Sta in [`visore/`](../visore/LEGGIMI.md), fa gli stessi passi nello stesso
ordine del telefono finto in Python, e le sue prove aprono un pacchetto vero
tenuto nel repository come file di testo (regola 389). La prova che conta è che
i due lettori, scritti in due linguaggi, dicono del **medesimo** pacchetto la
stessa cosa campo per campo: è l'unico modo di scoprire un difetto del formato
prima di averlo copiato due volte.

E il giro si chiude nei due versi: il Kotlin scrive `ritorno.db` come lo
scriverà l'app — un cuore, una raccolta, una riga di diario — l'Officina lo
rilegge col programma vero, il travaso successivo se lo riporta dentro il
pacchetto come copia di scorta, e il Kotlin lo ritrova lì. Compreso il caso più
scomodo: un cuore tolto sul monitor grande sparisce anche dal telefono, e il PC
se ne accorge perché non gli torna più indietro.

Restano da scrivere le schermate. Adesso aspettano una scelta sola invece di
otto (regola 180): il formato non ha bisogno di guardare niente, una schermata
sì.

Finché una delle due app non avrà aperto un pacchetto vero su un telefono vero,
questa parte **non è finita** (regola 342). Quello che c'è oggi è il formato
provato contro due lettori che non sono un telefono. È molto, ma non è un
telefono.

## Cos'è, in due righe

**Due app native, una per telefono, che non costano niente** (regola 356): una
per iOS, una per Android. Non una pagina web dentro un guscio: un iPhone non
può tenere offline decine di GB dentro un browser, e quindi «pacchetto offline»
vuol dire app vera.

Android viene per prima, perché non richiede un Mac, non scade e si installa da
Windows.

## Il giro completo

### 1. Si prepara il pacchetto, sul PC

In **Dispositivi**, nel programma sul PC (regole 384 e 494). Si aggiunge un telefono con il nome che si vuole («iPhone»,
«Redmi»), e ognuno ha da quel momento la sua cartella, il suo registro e la sua
selezione.

Di partenza è selezionato **tutto l'archivio**, e si toglie (regola 360). Si
sceglie per nodo (spunte sull'albero, i figli seguono), per periodo (da data a
data, o «ultimo anno») e per persona — anche al contrario: *tutto tranne le
foto in cui c'è X*, che è ciò che serve prima di prestare il telefono a
qualcuno.

Mentre si tocca, il conto si aggiorna: quanti scatti, quanto pesano, **quanti
sono video e quanto pesano loro** — è quasi sempre lì che sta il peso — e che
periodo coprono. La selezione non si salva a mano: quello che si spunta è già
salvato, e fra sei mesi si ritrova com'era (regola 385). Sopra il tasto stanno tutti gli avvisi: *non ci sta per 5 GB*,
*tolgo 1.204 foto*, *questo telefono ha ancora la password precedente*. E il
tasto dice cosa fa: «Prepara 28.740 scatti (41 GB) per iPhone».

Il travaso dura ore la prima volta. Si può cambiare schermata e continuare a
lavorare: va avanti da solo, con un segno in alto che lo dice (regola 191). Si
può fermare e riprende da dove era. Alla fine **rilegge tutto e confronta le
impronte**: è l'unico momento in cui ci si può accorgere di un disco che
sbaglia.

### 2. Si copia col cavo

L'Officina scrive il pacchetto in una cartella sul disco; **il travaso vero lo
fai tu**, collegando il telefono e copiando quella cartella dentro l'app, nel
modo che quel telefono già conosce (regola 368). Il programma non tocca mai il
telefono: non deve sapere niente di driver, di protocolli, né di cosa succede se
si stacca il cavo a metà.

Sul telefono il pacchetto finisce **nello spazio privato dell'app**: è l'unico
posto in cui le foto non entrano nella galleria di sistema, non vengono
indicizzate e non le vede nessun altro programma.

### 3. Si apre l'app

Si scrive la password — la stessa dell'Officina (regola 115) — e si entra. Da
quel momento il telefono non ha più bisogno di niente: né del PC, né della rete.

### 4. Le volte dopo

Durano minuti, non ore: si manda solo il nuovo (regola 371). Le foto che non
rientrano più nella selezione si tolgono, e il PC dice quante prima di farlo.
Il database si riscrive intero ogni volta, perché pesa pochi MB e così non può
mai restare indietro rispetto alle foto.

E il cavo va **in tutti e due i versi**: all'inizio di ogni travaso il PC legge
dal pacchetto i preferiti e le raccolte che hai fatto sul telefono, e dice
quanti ne sono tornati.

## Cosa c'è dentro il pacchetto

Una cartella, non un file (regola 358). Si apre col cavo e si vede com'è fatta,
ma non cosa contiene:

```
Visore-iPhone/
    visore.json         la carta d'identita', in chiaro
    dati.db             etichette, nodi, persone, luoghi, date  (cifrato)
    foto/3f/3f9a...     gli originali, con un nome a caso      (cifrati)
    mini/c2/c2e1...     le miniature 640 px in JPEG             (cifrate)
    volti/8b04...       un ritaglio 320 px per persona          (cifrato)
    ritorno.db          cuori, raccolte e diario, scritti dal telefono
```

I nomi veri delle foto e le loro date stanno solo dentro `dati.db`, cifrati:
chi trova la cartella non sa né quando è stata scattata una foto né come si
chiamava. Un nome a caso resta lo stesso da un travaso all'altro, così non si
riscrive quello che è già lì. La carta d'identità, in chiaro, non contiene
nomi: dice al massimo quanti file non sono entrati, e i dettagli restano sul PC.

| Entra | Non entra |
|---|---|
| Gli originali interi, **video compresi**, senza mai toccare la qualità | Le probabili schermate |
| Il `.MOV` delle live photo, altrimenti i gesti non hanno niente da muovere | Gli scatti messi «fuori archivio» |
| Gli HEIC come sono: li aprono tutti e due i telefoni | Le persone senza nome (regola 157) |
| Le etichette valide, ciascuna con la sua origine | Le proposte incerte: si decidono sul PC |
| Le note che hai scritto sugli scatti | **Le impronte dei volti** (regola 364) |
| Il nome del luogo, già scritto dal PC | |
| Le coordinate GPS esatte (regola 365) | |

Le miniature le fa il PC una volta sola e le copia: un telefono che dovesse
rifarle decodificherebbe trentamila HEIC al primo avvio (regola 362).

## La cifratura

**Tutto** il pacchetto è cifrato: foto, video, miniature, database, e anche
quello che il telefono riscrive (regola 366). Stessa password del forziere,
stesso schema — `scrypt` per la chiave, AES-256-GCM a blocchi da un mega.

Ogni file è **legato al suo posto** nel pacchetto: il nome del file entra nel
controllo della cifratura, e un file spostato o scambiato con un altro non si
apre più. I conti della password sono più cari che nella prima versione
(`scrypt` con N = 65 536 per i pacchetti nuovi), e il programma e l'app
accettano solo i conti che conoscono: una carta d'identità ritoccata per far
girare il telefono a vuoto si ferma subito. Un pacchetto fatto con una versione
precedente si riscrive tutto, coi nomi a caso, al primo travaso.

Si cifra **file per file**, non tutto insieme come il forziere sul PC: il
forziere si apre tutto all'avvio, il telefono no — deve poter aprire la foto
numero quattordicimila senza toccare le altre, e saltare a metà di un video
senza decifrare tutto quello che viene prima.

**La chiave non si conserva da nessuna parte.** Si ricava dalla password a ogni
apertura e vive in memoria finché l'app è aperta; uscendo, sparisce. Un telefono
spento non contiene niente che possa aprire il pacchetto.

La password si riscrive all'apertura e dopo il blocco automatico — cinque
minuti di partenza, regolabile fra subito, 1, 5, 15 e mai. Una password
sbagliata non cancella niente e non conta niente: rallenta, un secondo, due,
quattro.

Se sul PC il forziere è spento (regola 351), il pacchetto **chiede comunque una
password**: il fisso sta in camera, il telefono esce di casa (regola 28).

### Se il telefono si perde

Il PC non può fare niente a distanza, e non è una mancanza: una cancellazione
da remoto vorrebbe dire un'app che ascolta internet, cioè la porta che tutto il
progetto tiene chiusa. La protezione è che **senza la password quel pacchetto è
rumore**.

Quello che si fa è cambiare la password del forziere e rifare i pacchetti. I
pacchetti già in giro restano leggibili con la password vecchia — sono cifrati,
non collegati — e l'Officina lo scrive fra gli avvisi invece di lasciartelo
scoprire.

Il pacchetto è inoltre **escluso dal backup di iCloud e di Google**, e dal
passaggio dei dati quando si cambia telefono: altrimenti l'archivio finirebbe su
un server altrui, cioè la cosa che il progetto esiste per evitare. Si rifà dal
PC in un'ora: non ha bisogno di backup. Sul telefono l'app non si lascia
fotografare: niente screenshot e niente anteprima nell'elenco delle app aperte.

Se il file che il telefono riscrive (`ritorno.db`) un giorno non si legge più,
l'app non lo sovrascrive: lo sposta accanto, intatto, e riparte da quello che
il PC sapeva all'ultimo travaso.

## I sette giorni di iOS

Senza l'account sviluppatore Apple (99 €/anno, escluso), un'app installata da sé
su iPhone **smette di aprirsi dopo sette giorni**. È un limite di Apple, non
del programma, e l'app scrive quanti giorni mancano invece di sorprenderti
(regola 357).

La distinzione che conta è questa, e va imparata una volta:

| | Cosa succede |
|---|---|
| **Rinnovare** la firma dal PC | l'app non viene mai tolta: dentro resta tutto |
| **Cancellare e reinstallare** | iOS butta via l'intera cartella dell'app — cioè il pacchetto, cioè decine di GB da ricopiare |

Per questo i preferiti hanno una **copia di scorta dentro il pacchetto**: se
un giorno l'app viene cancellata davvero, si ricopia il pacchetto e si ritrova
tutto com'era (regola 380).

Android non ha questo limite. È il motivo per cui viene per prima.

## Le quattro sezioni

In fondo: **Foto**, **Nodi**, **Persone**, **Cerca** (regola 259). Toccare la
sezione in cui sei già riporta in cima; se sei già in cima, indietro.

**Foto** è la griglia dei giorni: tre miniature per riga, quadrate.
L'intestazione del giorno **non è la stessa sulle due app** (regola 394): sul
telefono Apple è quella di Foto — data grande a sinistra, luogo e numero sotto
in piccolo, i comandi del giorno dietro i tre punti — e sul Redmi è quella di
Google Foto, una riga sola con la data a sinistra e il luogo in fondo. Nessuna
delle due resta incollata in cima mentre il giorno scorre, perché nessuno dei
due sistemi lo fa: a dire dove si è arrivati è la barra degli anni.
Dalle più recenti alle più vecchie,
e gli scatti senza data in un gruppo loro in fondo. Appoggiando il dito al bordo
destro compare la barra degli anni: dal 2026 al 2011 in un secondo. In cima, una
riga dice quante foto sono arrivate con l'ultimo travaso, e si tocca per vedere
solo quelle; un'altra porta ai preferiti e alle raccolte.

**Nodi** è l'albero, un piano per volta, nell'ordine che ha sul PC. I rami senza
foto nel pacchetto non compaiono. Dentro un nodo: i figli in una riga in cima,
poi le foto, comprese quelle dei figli — con un interruttore «solo qui», di cui
non è ancora deciso dove stia (è l'unica delle otto bozze ancora aperta).

**Persone** è una griglia di facce, da chi compare più spesso. Dentro: il nome,
quante foto, che periodo, e una riga **«spesso insieme a»** con le facce di chi
compare nelle stesse foto. Toccandone una si stringe a «tutte e due»: è il
filtro «io e mio fratello», con un gesto solo.

**Cerca** trova nomi di nodi, di persone, luoghi, date, le tue note — e le
parole preparate dal PC (più sotto).

I numeri contano sempre **le foto che ci sono nel pacchetto**, non quelle
dell'archivio: un numero che promette mille foto e ne apre cento è peggio di
nessun numero.

## I gesti sulla foto aperta

È l'unica parte del Visore che non si indovina, perché è l'unica inventata qui.
L'app la spiega la prima volta, e la spiegazione si rivede dalle impostazioni.

Il segno **`◎ LIVE`** sulla miniatura dice in anticipo quali foto si comportano
in modo diverso (regole 253, 375):

| Gesto | Su una live photo | Su una foto normale |
|---|---|---|
| **Tocco secco** | l'assaggio: parte, fa il giro, torna statica | mostra e nasconde i comandi |
| **Giù piano** | accende il movimento, che resta in loop **a mani libere** | niente |
| **Giù di scatto** | chiude e torna alla griglia | chiude e torna alla griglia |
| **Su** | alza le informazioni | alza le informazioni |
| **Pizzico** | ingrandisce | ingrandisce |

A distinguere «giù piano» da «giù di scatto» è la **velocità**, non la
pressione: l'iPhone non legge più la pressione dal 2018 (regola 255). Mentre
scendi **non compare niente** (regola 395): a dire che il gesto ha preso è la
foto, che comincia a muoversi sotto il dito. Se molli prima della fine torna
ferma, e non è successo niente.

Il loop **resta acceso** anche scorrendo alle foto successive: è la differenza
rivendicata contro l'iPhone, dove la live vive solo finché tieni premuto.
L'audio è muto, con un tasto per accenderlo.

I video partono da soli, muti, e ripartono da capo alla fine; nella griglia
invece restano fermi.

**La foto che si apre è sempre l'originale** (regola 260). Nei decimi di secondo
che servono a decifrarla si vede la miniatura ingrandita, che diventa nitida.

## Preferiti e raccolte

Sono l'unica cosa che il telefono possiede (regola 68). Il cuore si mette con un
tasto o col doppio tocco, e il tasto sta dove lo mette il sistema (regola 399):
sull'iPhone nella barra in basso che compare col tocco, sul Redmi in alto a
destra. Sopra la foto, comunque, non resta niente. Le **raccolte** sono elenchi di foto scelte a mano —
niente automatismi — e nascono dalla selezione nella griglia («Scegli» in cima,
e «tutte» accanto a un giorno).

Un travaso **non le tocca mai**, nemmeno completo: vivono in un archivio
separato, e non c'è modo di cancellarle per sbaglio.

Tornano al PC da sole, all'inizio del travaso successivo, e lì diventano un
filtro «preferiti» e delle raccolte accanto ai filtri salvati, con scritto da
quale telefono vengono. iPhone e Redmi restano separati: fondere due elenchi
divergenti non riesce mai bene (regola 69).

Il PC può anche **togliere** un cuore, e il pacchetto porta l'elenco di quelli
tolti — altrimenti un gesto fatto sul monitor grande verrebbe annullato dal
telefono al travaso dopo.

## La ricerca sul telefono non è quella del PC

Sul telefono non gira nessun modello, quindi la ricerca a parole dell'Officina
(«mare cappello di paglia») lì è impossibile. Invece di rinunciarci,
**l'Officina calcola in anticipo** quali di circa duemila parole comuni
somigliano davvero a ogni foto, e le mette nel pacchetto come testo (regola 378).

Perché sia una ricerca e non un'illusione:

- il vocabolario è **un file che si legge e si corregge a mano**;
- la soglia è alta: una foto può non avere nessuna parola;
- quelle parole **non compaiono mai fra le etichette**, perché non sono
  etichette: sono un indice per cercare;
- i risultati per somiglianza stanno in un **gruppo staccato**, che dichiara da
  dove viene.

E **sotto il campo c'è sempre una riga che dice cosa cerca davvero**. Senza,
«cappello di paglia» che non trova niente sembrerebbe un archivio vuoto o un
programma rotto.

## Il diario dell'uso

L'app chiede **un solo permesso**: la posizione, mentre è aperta. Serve a un
diario di dove, quando, per quanto e su quali foto la usi (regola 381). Sta
dentro il pacchetto cifrato, non esce mai dal telefono, torna al PC insieme ai
preferiti e si guarda in fondo alla schermata Telefono.

Due cose vanno dette chiaramente:

- **il programma non offre nessun modo di cancellarlo.** Disinstallare l'app o
  cancellare il pacchetto lo porta via comunque — vedi
  [Come si dismette](dismissione.md) — ma dal Visore non si svuota;
- **si può rifiutare il permesso**, e l'app funziona lo stesso: il diario segna
  soltanto quando e quanto, senza il dove.

È la sola parte del progetto che va nella direzione opposta a tutte le altre, ed
è una decisione presa sapendolo.

## Quando qualcosa non torna

| Cosa succede | Cosa fa l'app |
|---|---|
| Una foto non si apre | resta la miniatura e lo dice piano |
| Il telefono non sa aprire quel formato | idem: la miniatura c'è sempre, è JPEG |
| Il pacchetto è incompleto | una riga sola, che si legge una volta, e si continua |
| Il pacchetto non si apre affatto | una schermata sola: «ricopialo dal computer» |
| Il pacchetto è più nuovo dell'app | lo dice e tiene quello che aveva |
| Il pacchetto è più vecchio dell'app | lo apre lo stesso, e dice che ne esiste uno più recente |
| Password del forziere cambiata sul PC | il pacchetto vecchio vuole ancora quella vecchia, e il PC lo scrive |

Gli errori si dicono su **tre livelli e in tre posti** (regola 382): sullo
schermo, accanto alle foto, una frase in italiano — mai il dettaglio tecnico;
nelle impostazioni, in un registro corto, il dettaglio e il codice, che si vanno
a cercare solo quando serve e che non li legge chi ti guarda lo schermo in
treno.

## Quello che il Visore non fa mai

- **non modifica l'archivio** — quel codice non esiste proprio, quindi un tocco
  distratto in autobus non può fare danni (regole 68, 250, 373);
- **non apre connessioni** — non sa nemmeno come si fa, e su Android lo dichiara
  nel manifesto, dove chiunque può controllarlo (regole 1, 381);
- **non fa uscire una foto** — niente condivisione, niente salvataggio nella
  galleria, e gli screenshot sono bloccati (regole 50, 367). Per mandare una
  foto a qualcuno si passa dal PC: è una conseguenza accettata, non una
  dimenticanza. *Ed è una difesa parziale, perché basta una seconda
  fotocamera;*
- **non chiede permessi** oltre alla posizione, e quello si può rifiutare;
- **non manda notifiche**;
- **non propone niente da sé** — nessun «un anno fa oggi», nessun ricordo,
  nessuna raccolta automatica. L'archivio l'hai costruito tu, e il telefono è
  dove lo si gode, non dove un programma decide cosa è importante.

## Dove sono le decisioni

Tutte le scelte di questa guida hanno un numero: **regole 356-383**, sezione 25
di [`REGOLE.md`](../sviluppo/REGOLE.md#25-il-visore-le-decisioni). Undici regole più
vecchie sono state corrette da queste, e portano la nota che dice quale: 6, 7,
14, 50, 67, 68, 155, 251, 256, 259, 326.

Le **regole 384 e 385** sono nate dopo, scrivendo la schermata «Telefono»: dove
sta nella barra, e quando si salva la selezione. Stanno nella sezione 26, e la
384 corregge la 350 sul numero delle voci.

Quando una scelta di qui sembra strana, la spiegazione è lì.
