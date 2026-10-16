# Come funziona dentro

Questo documento serve a chi apre il codice fra sei mesi — cioè, quasi
sicuramente, a chi lo ha scritto. Non spiega riga per riga: spiega **dove stanno
le mani** e **perché i pezzi sono divisi così**.

Le regole citate sono quelle di [`sviluppo/REGOLE.md`](../sviluppo/REGOLE.md).

---

## La forma del programma

```
officina/
├── impostazioni.py     dove stanno le cose, e i valori di partenza
├── registro.py         il registro tecnico: solo codici e numeri
├── errori.py           errori con due facce: messaggio e codice
├── riga_di_comando.py  la riga di comando
│
├── archivio/           IL SOLO PUNTO DI ACCESSO AI DATI
│   ├── accesso.py      apri, chiudi, database, miniature
│   ├── schema.sql      le tabelle, con dentro il perché
│   ├── database.py     connessione e impostazioni di SQLite
│   ├── migrazioni.py   aggiornare senza perdere niente
│   └── copie.py        backup, verifica, ripristino
│
├── modello/            le domande che si fanno ai dati
│   ├── file_media.py   i file, riconosciuti dal contenuto
│   ├── scatti.py       gli scatti e il filtro della galleria
│   ├── nodi.py         l'albero
│   ├── luoghi.py       le coordinate raggruppate in posti (regola 344)
│   └── etichette.py    i tre stati e la propagazione agli antenati
│
├── immagini/           aprire senza toccare
│   ├── lettura.py      originale → copia di lavoro raddrizzata
│   ├── consegna.py     copia di lavoro → AVIF per il browser
│   └── fotogrammi.py   dai video, i momenti in cui la scena cambia
│
├── importazione/       la tappa 1
│   ├── scansione.py    guardare nelle cartelle
│   ├── impronta.py     l'identità di un file è il suo contenuto
│   ├── metadati.py     EXIF, date, fusi, luoghi, schermate
│   ├── quicktime.py    leggere dentro un .mov senza programmi esterni
│   ├── abbinamento.py  quale video appartiene a quale foto
│   ├── miniature.py    la cache buttabile
│   └── motore.py       mette tutto in fila, e sa riprendere
│
├── descrittori/        LA TAPPA 2 — immagine → numeri
│   ├── base.py         cos'è un descrittore, e la sua carta d'identità
│   ├── preparazione.py le tre inquadrature (regole 37, 38)
│   ├── disegnato.py    colori e bordi: nessun modello, e il metro di paragone
│   ├── grandi.py       DINOv3 e SigLIP 2 (regole 174, 175)
│   ├── torcia.py       scheda video, freno, e la rete che resta spenta
│   ├── scaricamento.py l'unico posto che apre una connessione (regola 74)
│   └── vettori.py      i byte di un'impronta, e i confronti
│
├── impronte/
│   └── motore.py       la passata: un modello alla volta, e riprende da sola
│
├── apprendimento/      il pezzo che impara dalle tue conferme
│   ├── esempi.py       da cosa impara un nodo (regole 36, 55, 129)
│   ├── gruppi.py       chi non deve finire da due parti (regole 107, 77)
│   ├── classificatore.py  regressione logistica, deterministica
│   └── pagella.py      quanto ci azzecca, misurato onestamente
│
├── misura/             LA TAPPA 2 — il confronto delle scelte
│   ├── banco.py        mette a confronto, con gli stessi esempi
│   └── rapporto.py     solo numeri, e il controllo che lo verifica
│
├── finto/              l'archivio che non esiste
│   ├── immagini.py     disegnare fotografie
│   ├── contenitore_video.py  scrivere un .mov vero
│   ├── etichette.py    le scene che il generatore conosce già
│   └── generatore.py   l'archivio completo, casi storti compresi
│
└── web/                il server e le pagine
    ├── server.py       l'app, chi può entrare, gli errori
    ├── strade/         le rotte, un file per zona
    │   ├── comune.py   le variabili che le zone si passano
    │   └── base.py     quello che serve a tutte le pagine
    ├── vista.py        filtro ↔ indirizzo, e i numeri detti a parole
    ├── templates/      le pagine
    └── statici/        CSS e JavaScript scritti a mano, zero npm
        └── css/schermate/  comune.css e un foglio per zona, nell'ordine di base.py
```

Accanto all'Officina, e non dentro, c'è l'altra metà del progetto — il lettore
del pacchetto per il telefono, in Kotlin perché quella sarà la lingua dell'app
Android (regola 386):

```
visore/
├── lettore/            il formato, e niente altro: nessuna libreria
│   ├── Scrypt.kt       il calcolo lento, scritto a mano (regola 388)
│   ├── Blake2b.kt      l'impronta con cui si riconosce un file (regola 39)
│   ├── Cifratura.kt    AES-256-GCM a blocchi da un mega (regola 366)
│   ├── Formato.kt      la carta d'identità e dove sta ogni cosa
│   ├── Banco.kt        LA PORTA SOLA da cui si apre il database (regola 387)
│   ├── Pacchetto.kt    l'apertura in quattro passi, e la verifica
│   └── Ritorno.kt      quello che il telefono possiede e riscrive (regola 390)
└── computer/           lo stesso lettore, aperto su un PC
    ├── BancoInMemoria.kt  SQLite dai byte: il database non tocca il disco
    └── Principale.kt      un comando che dice cosa c'è in un pacchetto
```

---

## Le cinque idee che spiegano tutto il resto

### 1. Un solo punto di accesso ai dati (regola 8)

`archivio/accesso.py` è l'unico file che apre il database e scrive le
miniature. Nessun altro modulo tocca la cartella dell'archivio.

È una disciplina noiosa mentre si scrive e vale esattamente una cosa: il giorno
in cui si accende il contenitore cifrato (regole 331, 340), **l'unico file che
cambia è quello**. La firma di `apri(password)` esiste già e la password viene
già portata in giro; oggi non serve a niente.

### 2. L'unità è lo scatto, non il file (regola 4)

Un `.HEIC` e il suo `.MOV` sono due righe in `file_media` e **una** in
`scatti`. Le etichette stanno sullo scatto.

L'abbinamento incrocia tre indizi — nome, istante, identificatore Apple — e
serve che due su tre concordino. Con uno solo il programma non indovina: mette
una riga in `segnalazioni` e chiede (regola 11).

`abbinamento.py` non tocca il database di proposito: è una funzione pura, così
i casi difficili si scrivono a mano nelle prove invece di doverli costruire in
un archivio.

### 3. L'identità di un file è il suo contenuto (regola 39)

L'impronta è un BLAKE2b dei byte. Da questa scelta discendono tre comportamenti
che sembrano scollegati e sono la stessa cosa:

- le cartelle si possono riorganizzare quando si vuole;
- lo stesso file in due posti è **un** file con due percorsi (regola 135);
- se una foto sparisce, le etichette restano e si ricollegano se torna
  (regola 96).

### 4. «Non ancora deciso» non si scrive (regola 55)

La tabella `etichette` ha solo `si` e `no`. Il terzo stato è **l'assenza della
riga**.

Non è un dettaglio del database: è la regola più sottile del progetto scritta
in una forma in cui non si può sbagliare. Non esiste un modo di leggere «non
deciso» come «no», perché non c'è niente da leggere.

### 5. Gli antenati non esistono nel database (regole 36, 220)

Etichettare «maglietta Tommy» dà un esempio anche a «magliette» e a «vestiti».
Quelle righe **non vengono scritte**: si calcolano risalendo l'albero quando
servono.

È il motivo per cui spostare un nodo non tocca nessuna etichetta, e per cui non
esiste il caso «propagazione rimasta indietro».

---

## Le cose che meritano un avvertimento

### Il registro non accetta testo libero (regola 72)

`registro.evento("codice", chiave=valore)` accetta numeri e **parole di un
vocabolario chiuso** definito in `registro.py`. Qualsiasi altra stringa diventa
`<omesso>`.

Serve una parola nuova? Si aggiunge al vocabolario — e in quel momento si è
costretti a chiedersi se è una parola che può stare su un disco in chiaro.

### Il lettore di QuickTime è scritto a mano

`importazione/quicktime.py` legge durata, misure, data con fuso e identificatore
di contenuto direttamente dagli atomi del file, senza ffprobe.

Il motivo non è l'orgoglio: ffprobe è un programma esterno da installare, da
aggiornare e da chiamare 1300 volte lanciando 1300 processi, per ottenere
quattro numeri che stanno in un formato documentato e semplice.

Quando arriverà l'estrazione dei fotogrammi (regola 41) servirà un
decodificatore vero — quello sì. Ma sarà per decodificare video, non per
leggere metadati.

### I fotogrammi dei video: due strade, e si dice sempre quale

`quicktime.campioni_jpeg` legge la tabella dei fotogrammi senza aprire un solo
byte di immagine, e funziona quando il video è motion JPEG — l'archivio finto,
e qualche vecchio file vero. I video dell'iPhone sono HEVC e vogliono un
decodificatore, che arriva con `av` (PyAV) insieme alle librerie dei modelli.

Se non c'è, `fotogrammi.prendi` **lo dice** e restituisce zero fotogrammi con
il motivo scritto in italiano, invece di mostrare un riproduttore rotto
(regola 89).

La scelta di *quali* fotogrammi tenere (regola 41) è farthest-point sampling su
una firma da 32×32 in bianco e nero: si tiene il primo, poi ogni volta il più
lontano da tutti quelli già tenuti, e ci si ferma quando anche il più lontano è
sotto una soglia. È così che un video statico non produce cinquanta immagini
identiche — e la prova `test_fotogrammi.py` lo verifica su un video costruito
apposta per essere fermo.

### Il riquadro del dettaglio non è un modello (regole 33, 37)

La regola 33 dice che i riquadri delle persone sono automatici, con un
rilevatore pronto. Quel rilevatore arriva con la tappa 5, insieme ai volti.
Fino ad allora i due riquadri si trovano **meccanicamente**, e il database
scrive quale metodo ha usato (`centrale`, `dettaglio`, un domani `rilevatore`).

Il riquadro del dettaglio è la finestra con più *passa-alto* dentro: si prende
una copia in bianco e nero a 192 pixel, se ne fa una versione sfocata, e si
guarda dove le due differiscono di più. Un orizzonte attraversa mezza fotografia
e riempirebbe di bordi qualsiasi misura fatta a occhio, ma è una figura grande e
sfumata e sparisce da sola; una scritta piccola no.

Non è un ripiego mascherato, ed è esattamente ciò che la misura della regola 105
verifica: se il ritaglio non batte la foto intera, il numero lo dice.

### Il classificatore fa sempre gli stessi passi

Nessun criterio di arresto che dipenda dai dati, nessun numero casuale, i pesi
partono da zero: due addestramenti sugli stessi esempi danno lo stesso identico
modello, sempre. Senza, sarebbe impossibile dire se un'etichetta nuova ha
migliorato le cose o se è cambiato il caso.

I «sì» e i «no» pesano uguale in totale anche quando sono tre contro duecento:
senza, il modo più facile per il modello di sbagliare poco sarebbe rispondere
sempre «no» — e sarebbe anche il più inutile.

### I due modelli grandi non sono mai stati eseguiti qui

Va detto, perché è il limite più onesto di questa tappa: **DINOv3 e SigLIP 2
non hanno mai girato sulla macchina su cui il programma è stato scritto.**
Pesano gigabyte, richiedono torch, e la regola 74 vieta di scaricarli se non
con un comando che l'utente scrive apposta. La prima volta che gireranno
davvero sarà sul computer di chi usa il programma.

Quello che si è potuto provare è l'impianto intorno, con un modello finto che
si comporta come quelli veri — la stessa idea dell'archivio finto (regola 111),
applicata a una libreria invece che ai dati. `test_descrittori_grandi.py`
verifica che le immagini arrivino a gruppi della misura scelta, che le impronte
escano normalizzate e della lunghezza dichiarata, che il modello si legga
**solo dal disco** (`local_files_only=True`, altrimenti la libreria andrebbe a
controllare online a ogni apertura), che chiudere liberi davvero, e che la
mezza precisione arrivi con il nome giusto.

Quest'ultima merita una riga. `from_pretrained` accetta qualunque parola in più
senza protestare: passare `dtype` a una libreria che vuole `torch_dtype` **non
dà errore** — carica il modello in precisione piena e basta. Su una scheda da
12 GB è la differenza fra un modello che ci sta e uno che non ci sta, e si
scoprirebbe a metà di una notte con un messaggio che parla di memoria.

### Il rapporto della misura si rilegge prima di scriverlo

`misura/rapporto.py` è costruito perché non *possa* contenere nomi: i nodi sono
numerati, i descrittori e le inquadrature vengono da un elenco chiuso nel
codice, i file non compaiono affatto.

Siccome «costruito perché non possa» è una promessa da verificare e non da
credere, `controlla()` rilegge il rapporto finito e ci cerca dentro, uno per
uno, i nomi veri presi dal database. Se ne trova anche uno, il file non si
scrive (regola 110). La prova `test_misura.py` pianta apposta dei nomi e
controlla che l'allarme suoni.

### La griglia si giustifica in JavaScript

Righe di altezza fissa (regola 198) **e** proporzioni vere senza tagliare niente
(regola 196) si ottengono scegliendo quante foto stanno in una riga: si sommano
le proporzioni finché la riga è piena, poi si calcola l'altezza che la fa
combaciare esattamente con la larghezza.

È un conto di due righe, e nessun trucco di CSS lo fa davvero — i vari
`flex-grow` sbagliano sempre l'ultima riga.

### I conteggi dei filtri si fanno nel modo ottuso (regole 302, 330)

Per ogni nodo si chiede al database «quanti ne resterebbero se aggiungessi
questo adesso». Una domanda per nodo.

Non è una svista: con «Oppure» e «tranne» un conteggio calcolato in modo furbo
vorrebbe dire tre cose diverse a seconda della combinazione. Così invece vuol
dire sempre e solo *cosa vedrei dopo aver cliccato*. Con qualche centinaio di
nodi sono millisecondi.

---

## Le prove

```bash
python -m pytest prove
```

Girano su foto finte generate al momento (regola 73). Le quattro che contano di
più:

| Prova | Cosa protegge |
|---|---|
| `test_originali_intatti.py` | gli originali non cambiano di un byte (regola 2) |
| `test_etichette.py` | «non deciso» non diventa mai «no» (regola 55) |
| `test_albero.py` | spostare un nodo non tocca le foto (regola 220) |
| `test_copie.py` | un backup si riapre davvero (regola 131) |
| `test_misura.py` | dal rapporto non esce nessun nome (regole 106, 112) |
| `test_descrittori_grandi.py` | l'impianto dei due modelli, provato senza scaricarli |
| `test_apprendimento.py` | la divisione fra esempi e verifica non bara (regole 107, 243) |
| `test_visore_kotlin.py` | il lettore in Kotlin e quello in Python leggono lo stesso pacchetto allo stesso modo (regole 383, 386) |

Se una di queste fallisce, non è un difetto da mettere in lista: è una regola
del progetto che si è rotta.

L'ultima chiama Gradle e si salta dove non c'è (lo dice). Il lettore Kotlin ha
anche prove sue, che girano da sole in pochi secondi e non chiedono Python:

```bash
gradle -p visore test
```

---

## Cosa c'era da fare, e dove è finito

| Cosa | Tappa | Regole | Oggi |
|---|---|---|---|
| etichettatura, proposte, riaddestramento | 3 | 337 | fatto: pagina Etichetta, tasto «Riaddestra» |
| mappa, pagella, galleria completa | 4 | 338 | fatto: Luoghi, Stato, Galleria |
| persone e volti | 5 | 339 | fatto: Persone, SCRFD + AdaFace, corpo e vestiti |
| cifratura del contenitore | quando nasce la prima cosa non ricostruibile | 340 | fatto: il forziere si accende dalle Impostazioni |

---

## Il forziere

*Regole 8, 9, 331, 340.*

> **340.** La cifratura si accende il giorno in cui nasce la prima cosa che non
> si può ricostruire.

Quel giorno è la tappa 3: prima ci sono solo impronte e miniature, che si
rifanno in una notte; dopo ci sono le etichette, che sono mesi di lavoro e non
si rifanno.

### Cosa c'è dentro, e cosa no

Dentro: il database, le miniature, quello che il programma ha imparato dalle
tue etichette, le copie, il registro. Tutto in un file solo, `reale.forziere`,
accanto alla cartella.

Fuori, e per sempre: **le tue foto.** Restano nella tua cartella, che il
programma legge e non tocca (regola 8). Perdere la password vuol dire perdere
il lavoro di catalogazione, mai le fotografie.

Fuori anche i modelli scaricati (regola 74): sono pesi addestrati da altri, non
contengono niente di tuo, e sono gli unici megabyte del progetto che si
riprendono con un comando.

### Come si accende

```bash
python -m officina forziere --accendi
```

A mano, guardandolo, e mai per sbaglio mentre si cerca qualcos'altro. Il
comando dice cosa sta per succedere e chiede la password due volte. Poi
**scrive, rilegge tutto per controllo, e solo se torna fuori la stessa cosa
cancella il chiaro**: un controllo in più che costa qualche secondo e che evita
l'unico incidente qui non rimediabile.

Da quel momento `avvia` chiede la password. `forziere --stato` dice com'è
messo; `forziere --spegni` torna a una cartella in chiaro.

### Come è fatto

- la chiave nasce dalla password con **scrypt** (n=32768, r=8, p=1), che sta
  nella libreria standard di Python: rendere una password una chiave costa
  apposta qualche decimo di secondo e qualche decina di megabyte di memoria,
  così provarne milioni al secondo non è possibile;
- si cifra con **AES-256-GCM**, a blocchi di 4 MB, perché un archivio di
  miniature pesa gigabyte e tenerlo in memoria è il modo di far fallire questa
  operazione sul portatile invece che sul fisso;
- ogni blocco porta autenticato **il proprio numero e se è l'ultimo**: tagliare
  il file a metà o rimescolare i blocchi non produce un archivio più corto,
  produce un errore. È la differenza fra «cifrato» e «cifrato bene»;
- il primo blocco non contiene dati: contiene una frase fissa, e serve solo a
  distinguere «la password è sbagliata» da «il file è rovinato». Sono due guai
  diversi che portano a due gesti diversi, e dire quello sbagliato manda a
  cercare nel posto sbagliato (regola 279).

L'unico file del programma che è cambiato per tutto questo è
`officina/archivio/accesso.py`, come la regola 8 aveva promesso: nessun altro
modulo sa che il forziere esiste.

### Non c'è nessun «password dimenticata»

E non è una dimenticanza: **se ci fosse una via di recupero, quella via sarebbe
anche la via di chi non deve entrare** (regola 106).

### Se il programma si chiude male

Un blackout mentre l'archivio è aperto lascia la cartella in chiaro sul disco,
con dentro un file `.forziere-aperto`. Alla riapertura il programma se ne
accorge, **tiene quella** — è la più recente — e la richiude alla chiusura
successiva. Il disco intanto è cifrato da Windows (regola 9).

### Serve una libreria in più

`cryptography`, e **solo** se il forziere si accende. Senza, tutto il resto
funziona e il programma lo dice col nome della libreria invece di rifiutarsi di
partire.
