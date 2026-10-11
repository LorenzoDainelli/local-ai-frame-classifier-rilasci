# Cosa fa e a che punto è

La descrizione lunga, capitolo per capitolo, di quello che il programma sa
fare. Per installarlo basta la [pagina principale](../README.md).

## Cos'è

Due programmi (regola 6):

|  | **Officina** (PC) | **Visore** (telefono) |
|---|---|---|
| Cosa fa | importa, analizza, addestra, etichetta, riconosce i volti | mostra, filtra, cerca |
| Quanto si usa | 10% | 90% |
| Ha bisogno di AI? | sì, tutta | no, nessuna |

Qui c'è l'Officina. Il Visore arriva dopo (regola 14), ed è **due app**: una
per iOS e una per Android, senza account a pagamento e senza abbonamenti
(regola 356). Riceve dal PC un pacchetto cifrato via cavo e da lì vive offline,
senza collegarsi mai a niente (regole 7, 358).

## A che punto è

Le cinque tappe della sezione 24 delle regole ci sono tutte:
**1 — l'importazione** (regola 335), **2 — la misura** (regole 105, 336),
**3 — l'etichettatura** (regola 337), **4 — mappa, pagella e galleria**
(regola 338), **5 — le persone e i volti** (regola 339). E la cifratura
(regole 331, 340), costruita e provata, che si accende con un comando quando
si vuole.

«Scritte» però non vuol dire «finite». La regola 342 chiede tre prove: il giro
completo sull'archivio finto, **lo stesso giro sulle foto vere di chi lo usa**,
e i controlli della regola 73. La prima e la terza passano su tutte e cinque;
la seconda, oggi, solo sulle prime due. Quello che manca non è codice — è la
colonna di mezzo, ed è l'unica che non si può scrivere qui dentro.

Cosa fa già:

- legge HEIC, JPEG, PNG e i video QuickTime, **senza mai toccare gli originali**;
- riconosce ogni file dal contenuto, non dal percorso — quindi le cartelle si
  possono riorganizzare quando si vuole, e i doppioni si riconoscono da soli;
- unisce foto e `.MOV` della stessa live photo incrociando tre indizi;
- legge la data di scatto con il fuso orario, e dichiara «senza data» invece di
  inventarla;
- riconosce le probabili schermate e le mette in una domanda sola;
- fa le miniature in una cache buttabile e rigenerabile;
- mostra tutto in una galleria a mosaico con le proporzioni vere;
- propone una data per gli scatti che non ce l'hanno, dicendo sempre da dove
  l'ha ricavata;
- corregge in blocco: filtra, seleziona tutto, agisci;
- si accorge se un file sparisce dal disco, senza perdere le sue etichette;
- risponde solo al computer su cui gira, e sulla rete di casa solo ai
  dispositivi approvati uno per uno;
- si può interrompere e riprende da dove era;
- si apre con un doppio clic, in una finestra senza barra degli indirizzi, e la
  prima volta prepara tutto in sei passi e finisce con un tutorial.

E dalla tappa 2:

- calcola le **impronte numeriche** di ogni scatto a tre livelli di zoom — foto
  intera, soggetto, dettaglio — con il modello che preferisci, uno alla volta
  per non riempire la scheda video;
- prende dai video i fotogrammi **dove la scena cambia davvero**: un video
  fermo non produce cinquanta immagini identiche — e da lì nascono la
  miniatura dei video veri e la striscia navigabile sotto ogni video;
- mostra **chi somiglia a uno scatto**, che è il modo più diretto di capire se
  un descrittore funziona sulle tue foto;
- ha un **banco di prova** per dare in un pomeriggio le decisioni su cui
  misurare: uno scatto, un tasto;
- **confronta le scelte** — i due descrittori, il ritaglio contro la foto
  intera, il classificatore — e scrive un rapporto fatto **solo di numeri**,
  che si può mostrare a chiunque perché al suo interno non esiste un nome.

E dalle tappe 3, 4 e 5:

- **propone**: guarda l'impronta di uno scatto e dice quali nodi ci crede, con
  il *perché* fatto di scatti veri che si aprono — «assomiglia a 5 scatti che
  hai confermato». Il filo che separa le proposte credibili dalle ipotesi non
  è una percentuale: è la soglia del singolo nodo;
- **etichetta in un giro corto**: guardo, decido, passo al successivo, senza
  che la pagina si ricarichi mai. I tasti sono scritti dentro le pillole;
- ha la **mappa dell'albero** con fili e trascinamento, dove la disposizione la
  decide il programma e trascinare significa una cosa sola — *cambia posto* —
  con l'annulla che torna indietro per tutta la sessione;
- ha la **pagella**, che serve a una cosa sola: far sapere cosa etichettare
  adesso perché migliori il più possibile. E dice «troppo pochi esempi per
  dirlo» invece di inventare una percentuale;
- **trova le facce** e mette insieme quelle che si somigliano, poi le fa
  nominare un gruppo alla volta, dal più grande al più piccolo;
- **cerca a parole**, distinguendo sempre ciò che hai detto tu da ciò che il
  modello crede di riconoscere — e sotto una certa soglia dice di no, invece
  di riempire lo schermo;
- può chiudersi dentro un **contenitore cifrato**: senza la password, sul disco
  c'è rumore. Le foto originali restano fuori e intatte.

- **riscrive la domanda** prima di cercare, con un modello linguistico che
  gira qui (regola 137): traduce in inglese, dove il modello delle parole è più
  preciso, e chiede la stessa cosa in due o tre modi diversi. I risultati
  arrivano in due tempi — prima quelli sulla frase com'è scritta, poi la lista
  si riassesta — così non c'è mai uno schermo vuoto ad aspettare.

E dal Visore, per ora solo la metà che sta sul PC:

- **costruisce il pacchetto per il telefono** (regole 358-372): una cartella
  con le foto per anno e mese, coi loro nomi veri, le miniature già pronte e un
  database SQLite, **tutto cifrato file per file** con la stessa password del
  forziere. Si sceglie cosa entra — per ramo dell'albero, per periodo, per
  persona, e anche al contrario: *tutto tranne le foto in cui c'è questa
  persona* — e si sa quanto pesa **prima** di cominciare;
- e lo si prepara **guardandolo**, nella schermata «Telefono» (regola 384): la
  selezione si compone spuntando, e a ogni spunta il conto si rifà — quanti
  scatti, quanto pesano, quanti sono video e quanto pesano loro. Gli avvisi
  stanno tutti sopra il tasto, e il tasto dice cosa fa: «Prepara 28.740 scatti
  (41 GB) per iPhone». In fondo alla stessa schermata si legge cosa il telefono
  ha riportato indietro — preferiti, raccolte e il diario (regole 380, 381);
- dopo il primo travaso **manda solo il nuovo**, toglie quello che non ci va
  più dicendo prima quante foto sono, si interrompe e riprende, e alla fine
  **rilegge tutto e confronta le impronte**;
- **rilegge il pacchetto col telefono finto** (regola 383) — apre la carta
  d'identità, decifra il database, apre una foto, verifica: è la specifica
  eseguibile di quello che Swift e Kotlin dovranno fare;
- e **quella specifica adesso è eseguita anche in Kotlin** (regola 386), che è
  la lingua dell'app Android: in [`visore/`](../visore/) c'è il lettore del
  pacchetto — carta d'identità, `scrypt`, AES-256-GCM a blocchi, il database in
  memoria, le impronte ricontrollate una per una. I due lettori aprono lo stesso
  pacchetto e devono dire **la stessa cosa, campo per campo**: è l'unica prova
  che il formato regge finché un telefono vero non c'è;
- e il Kotlin sa anche **scrivere** quello che il telefono possiede — cuori,
  raccolte, diario (regole 380, 390) — nell'unico file del pacchetto che non è
  il PC a fare. Il giro si chiude davvero: il Kotlin mette un cuore, l'Officina
  lo rilegge, il travaso successivo se lo riporta dentro, e il Kotlin lo
  ritrova lì il giorno in cui l'app venisse cancellata e rimessa.

Cosa **non** fa ancora: l'app dell'iPhone, che aspetta un Mac (regola 14). Le
otto decisioni sulle bozze (regola 180) sono prese tutte — regole 392-401 — e le
otto schermate dell'app Android sono disegnate. Quello che resta è dichiarato e
non è una svista: il pacchetto vero su Android non si apre ancora (regola 387),
e le schermate non sono mai state compilate, perché l'SDK di Android sulla
macchina dove sono state scritte non c'è. Finché un telefono vero non avrà
aperto un pacchetto, quella parte non è finita (regola 342).

E una cosa detta senza girarci intorno: i **due modelli dei volti** non sono
mai stati eseguiti sulla macchina dove il programma è stato scritto — da lì non
si arrivava a chi li distribuisce. Il lavoro difficile — decodificare le nove
tabelle con cui il rilevatore risponde, raddrizzare la faccia sui cinque punti
del viso prima di misurarla — lo fa OpenCV, che è la libreria di chi quei
modelli li ha pubblicati. Quello che resta di nostro, e cioè i colori
nell'ordine giusto, le coordinate che tornano in frazioni del lato e l'impronta
normalizzata, è provato con un rilevatore finto. È il punto del programma dove
aspettarsi correzioni.

