# La sincronizzazione fra due computer

> **Questo documento è nato come preventivo, e adesso non lo è più.** I sei
> blocchi sono fatti: il registro, il pacchetto, la fusione, la prova lunga e
> la schermata. Le parti scritte al futuro sono rimaste com'erano, con sotto
> un riquadro **Fatto** che dice com'è andata davvero e cosa si è scoperto
> scrivendolo — perché la differenza fra le due cose è la parte che vale.
>
> **Quello che resta da fare non è codice.** Nessuno ha ancora fatto girare
> tutto questo sull'archivio **vero**, su due computer veri, con decine di
> gigabyte in mezzo. Fino a quel giorno l'archivio vero sta su una macchina
> sola, e la prima volta la si fa con una copia di sicurezza fresca a
> portata di mano.

---

## Il problema, in quattro righe

L'archivio vive su un computer. Se ne compare una copia su un secondo
computer e si lavora su tutte e due, i due database cambiano le stesse righe
in modi diversi. Ricopiare una cartella sull'altra non è sincronizzare: è
sovrascrivere, e il lavoro fatto dall'altra parte sparisce **senza nessun
messaggio d'errore**. È il guasto peggiore che questo progetto possa avere,
perché le etichette sono l'unica cosa qui dentro che non si può rifare con
un comando.

## Cosa non cambia mai

Internet non c'entra. Un ospite che sente «sincronizzazione» pensa al cloud,
a un account, a un server di qualcun altro. Qui no: si parla di due dischi
in casa, collegati da un cavo o dalla rete locale. La regola 106 resta
intera — le fotografie e i nodi non escono dalle macchine del proprietario,
in nessun momento e in nessuna forma. Il codice della fusione si scrive e si
prova sull'archivio **finto** (regole 111, 158, 341), che non contiene
niente di nessuno.

---

## Quello che c'è già, e vale

Tre pezzi del progetto lavorano già nella direzione giusta. Non sono
un dettaglio: sono metà del lavoro.

**L'identità sta nel contenuto, non nel numero di riga.** `file_media.impronta`
è l'impronta del contenuto ed è unica (regola 39). I percorsi stanno in una
tabella a parte, possono essere tanti (regola 135) e possono sparire senza
portarsi via le etichette (regola 96). Questo è esattamente ciò che serve per
dire «questa foto qui e quella là sono la stessa» su due macchine che non
hanno mai avuto gli stessi numeri di riga.

**Un pezzo di registro esiste già.** `storico_etichette` scrive `azione`
(messa, tolta, cambiata) con `avvenuto_il` (regola 40). È già un diario
datato della tabella più importante di tutte.

**Il travaso col telefono è lo stesso problema, già risolto una volta.**
La regola 380 dice: «Preferiti e raccolte tornano al PC da soli, all'inizio
di ogni travaso, in un secondo SQLite piccolo e cifrato che il telefono
scrive nel pacchetto: nessun collegamento, lo stesso cavo nell'altro verso.»
E tutto si aggancia all'impronta, non al numero. La forma della soluzione
c'è già, provata: un pacchetto piccolo che viaggia sul cavo e si fonde
all'arrivo.

## Quello che c'è già, ed è contro

**La regola 69: «fondere due elenchi divergenti non riesce mai bene.»**

Non è una frase buttata lì: è scritta nel codice come motivo per cui iPhone
e Redmi restano separati invece di essere fusi. Il progetto ha già deciso
una volta, in un caso più facile di questo, che la fusione automatica non si
fa.

E il caso del telefono è più facile davvero, perché è **asimmetrico**: il
telefono possiede solo i cuori e le raccolte, il PC possiede tutto il resto,
e non si contendono niente. Due PC che etichettano sono **simmetrici**:
tutti e due possono cambiare tutto. È la stessa forma, ma con il problema
vero dentro.

Questo non vuol dire che non si fa. Vuol dire che si fa **decidendo le
regole a mano, una per una, e scrivendole** — non lasciando che se la cavi
il codice.

---

## Quello che manca

### 1. Il registro delle modifiche (schema versione 11)

Oggi il database dice *com'è adesso*, non *quando ogni cosa è diventata
così*. Senza quello non si può decidere niente. Serve una tabella nuova che
segni, per ogni cambiamento che conta: quale tabella, quale riga (agganciata
all'impronta o al nome, non al numero), che cambiamento, quando, e **su
quale delle due macchine**.

Le migrazioni del database arrivano oggi alla versione 10. Questa sarebbe la
11, e come tutte le altre non tocca i dati che ci sono già: si aggiunge.

Serve anche un nome per ogni macchina, deciso una volta e scritto
nell'archivio: senza, «chi ha fatto questa modifica» non ha risposta.

> **Fatto.** La versione 11 c'è: tabelle `macchine` e `cambiamenti`, e ogni
> gesto sulle etichette e sull'albero ci lascia una riga. Due scelte, prese
> scrivendolo, che vale la pena sapere. La prima: nel registro finiscono i
> numeri di riga *di questa macchina*, e la traduzione in impronta e in
> percorso di nodo la farà il pacchetto al momento di partire — scrivere
> succede a ogni clic, tradurre una volta per travaso. La seconda: **le
> proposte della macchina non entrano nel registro**, solo quello che decidi
> tu, ed è la regola 411 applicata (ciò che si rifà da solo non si trasporta).

### 2. Il pacchetto che viaggia

Una cartella, sulla forma di quella del telefono: dentro c'è il registro
delle modifiche da un certo momento in poi, l'albero, gli scatti, le
impronte numeriche — e **le foto vere**, perché la domanda 1 è stata decisa
così (regola 403). Si porta sull'altra macchina e si legge.

> **Fatto.** `officina/sincronia/`, e il comando
> `python -m officina sincronizza --dove <cartella>`. Tre cose vale la pena
> saperle.
>
> **La cifratura è quella del telefono, la stessa riga per riga.** Un secondo
> formato di cifratura sarebbe stato un secondo posto in cui sbagliare.
>
> **Il pacchetto si difende da solo.** La dimensione in chiaro di ogni file è
> scritta e firmata dentro il file: uno tagliato a metà non si apre, dice di
> appartenere a un file più lungo. E la carta d'identità resta dichiarata
> «interrotto» finché chi scrive non ha finito. Vuol dire che il trasporto può
> essere qualunque cosa — LocalSend, una chiavetta, un cavo: il peggio che può
> fare è consegnare qualcosa che non si apre, mai qualcosa di sbagliato che si
> apre.
>
> **Sulla chiavetta non passa niente in chiaro.** I file hanno nomi a caso, che
> non sono né le impronte né i nomi delle foto, e ognuno è legato al suo posto:
> uno spostato o scambiato non si apre. Il database del pacchetto si costruisce
> in memoria e si cifra prima di toccare il disco. I campi della carta
> d'identità che decidono qualcosa — chi l'ha mandato, da quale archivio, da che
> punto a che punto del registro, quando — sono ripetuti dentro la parte
> cifrata, e se fuori non coincidono il pacchetto non si apre: è manomesso. Un
> pacchetto fatto da una versione precedente del programma va rifatto, e
> l'elenco dei pacchetti lo dice.
>
> **La prima sincronizzazione è grossa, tutte le altre no.** Ogni pacchetto
> porta in fondo l'elenco delle impronte che il mittente possiede; chi lo
> legge se lo segna, e nel pacchetto di ritorno salta quei file. Le righe che
> li descrivono partono lo stesso — pesano cento byte, e se intanto è cambiata
> una data così arriva.

### 3. Le regole dei conflitti

Il cuore del lavoro, ed è tuo, non mio. Le domande sono più avanti.

> **Fatto.** `officina/sincronia/fusione.py`, e da riga di comando
> `python -m officina sincronizza --applica <cartella>`. Tre cose vale la
> pena saperle, perché non erano ovvie prima di scriverlo:
>
> * **chi vince si decide guardando il registro, non le etichette.** Un'etichetta
>   dice *cos'è* adesso; il registro dice *quando l'hai decisa tu*. Sono due
>   informazioni diverse, e senza la seconda la regola 404 non ha niente da
>   confrontare;
> * **rinominare, per l'altra macchina, era indistinguibile dal creare.** Sotto
>   la regola 406 un nodo *è* il suo percorso: cambiare nome ne fa un altro. Ci
>   voleva una colonna in più — da dove partiva — scritta nell'istante del
>   gesto, quando l'informazione c'è ancora (schema versione 13). Senza,
>   sull'altro PC ti ritrovavi il nome vecchio e il nome nuovo, con le
>   fotografie divise fra i due;
> * **quello che ricevo non entra nel mio registro.** Il registro è l'elenco dei
>   gesti *di questa macchina*: se ci finisse anche il ricevuto, al pacchetto
>   dopo glielo rimanderei indietro come se fosse mio.
>
> **Persone e cuori (regole 408, 409) sono arrivati col blocco 6**, e
> viaggiano in un modo diverso da tutto il resto: come **stato**, non come
> storia. La ragione sta in cosa è una persona — un mucchio di volti, e i
> mucchi li fa il programma su ogni macchina per conto suo. Le due macchine
> non hanno mai avuto lo stesso mucchio e non c'è nessun numero da
> confrontare: quello che hanno in comune sono le fotografie. Quindi la
> domanda che il programma si fa è una sola: *le fotografie in cui di là c'è
> Anna, qui in quali mucchi stanno?* In uno solo e senza nome, prende il nome;
> in due o più, i due mucchi **restano due** e la coppia finisce nel cassetto
> dove li guardi affiancati. È la regola sei per intero: il programma segnala,
> non unisce.

### 4. La prova

Due archivi finti, fatti divergere apposta con tutti i casi delle domande,
fusi, e controllati riga per riga. Più il caso brutto: il pacchetto letto
due volte, o a metà, o nell'ordine sbagliato. Questo pezzo di lavoro pesa
quanto tutti gli altri messi insieme, e non si taglia: se la fusione ha un
errore, l'errore mangia le etichette in silenzio.

> **Fatto.** `prove/test_sincronia_giro_lungo.py`. La domanda che queste prove
> fanno non è «funziona?» ma **«dopo un po' di andirivieni i due computer
> dicono la stessa cosa?»**, e si chiede confrontando un *ritratto* di ogni
> archivio: l'albero per intero e, per ogni fotografia, in quali nodi sta e con
> che stato. Se i due ritratti sono identici i due PC sono copie l'uno
> dell'altro; se no, la differenza dice quale etichetta si è persa.
>
> **Ha trovato un difetto che nessuna prova corta poteva trovare.** Quando due
> decisioni opposte portano lo stesso identico secondo, la fusione teneva
> «quella che c'è già» — che sembra la scelta prudente e invece è l'unica
> sbagliata: di qua resta la mia, di là resta la sua, e i due archivi restano
> diversi **per sempre**, senza che niente lo segnali. Un pacchetto solo non lo
> mostra: ci vuole il giro intero. Adesso il pareggio si rompe con l'unica cosa
> che le due macchine vedono uguale — il codice della macchina, nato a caso una
> volta sola: vince il più piccolo. Non è una regola sul merito, è una moneta
> che cade dalla stessa parte su tutti e due i computer.
>
> **E un buco che nessuno vedrebbe.** Un pacchetto che dice «porto i
> cambiamenti dal 40 al 90», applicato da una macchina che di quella lì è
> arrivata solo al 12, scriveva «visto fino a 90» sopra ventotto gesti mai
> arrivati: persi in silenzio, per sempre. Succede il giorno che si ripristina
> una copia di sicurezza vecchia. Adesso si ferma e lo dice, e il rimedio è
> rifare il pacchetto sull'altra macchina.
>
> **Una cosa che invece va bene così:** le due macchine *non* hanno le stesse
> etichette indovinate dal programma, e non devono averle. Quelle non viaggiano
> di proposito (regola 411, ciò che si rifà da solo non si trasporta): ognuna
> rifà le proprie col proprio modello, che è identico. Il ritratto guarda solo
> le decisioni tue.
>
> **Un aggiusto piccolo, da riga di comando:** se conosci una macchina sola, il
> pacchetto è per lei anche senza scrivere `--per`. Serviva davvero: è solo
> sapendo *a chi* si manda che si può mandare la metà, e senza, la seconda
> sincronizzazione pesava come la prima.

### 5. La faccia

Il pulsante, l'avanzamento, e la pagina dei volti da unire.

> **Fatto.** In **Dispositivi**, «Altro computer» sta accanto al telefono
> — e stanno insieme perché sono la stessa cosa fatta con l'altro cavo: una
> cartella cifrata che esce da una macchina ed entra in un'altra, e in mezzo
> ci porti tu quello che vuoi.
>
> Da lì si fa il pacchetto e si applica quello arrivato, senza toccare la riga
> di comando. La cartella si scrive una volta e resta. I pacchetti trovati lì
> dentro si elencano leggendo solo la loro carta d'identità, che non ha bisogno
> della password e **non dice una parola su cosa contiene l'archivio**
> (regola 106): la pagina si disegna anche col forziere chiuso. Uno di un altro
> archivio — il finto contro il vero — non ha il tasto per applicarlo: non è un
> errore da mostrare dopo, è un tasto che non compare.
>
> **Le note si mostrano tutte e per esteso.** Sono i casi in cui il programma
> ha fatto una cosa che non gli avevi chiesto: un nodo tornato in vita
> (regola 407), una persona che qui è divisa in due. Nasconderle dietro un
> numero vorrebbe dire che il giorno che succede sembra un guasto.
>
> **La pagina dei volti da unire c'era già**: è il cassetto dei «forse»
> (regola 289). Il blocco 6 non ne ha fatta una seconda — ci ha portato dentro
> il lavoro, che è diverso e migliore. Quando una fusione ci mette qualcosa, la
> schermata lo dice e ti manda lì.

---

## Le decisioni prese

Le nove risposte del proprietario. Sono le regole nuove del progetto: il
codice della fusione fa questo e non altro.

**Una correzione, prima.** La prima versione di questo documento portava come
esempio di litigio «di qua l'hai messa in Mare, di là in Montagna». Non è un
litigio: `etichette` ha `UNIQUE (scatto_id, nodo_id)`, cioè una fotografia sta
in tanti nodi insieme. Mare e Montagna diventano due righe diverse e si
fondono senza toccarsi. Il litigio vero è più stretto: **stessa foto, stesso
nodo, stati opposti.**

### 1. Cosa viaggia — tutto, bit per bit

I due computer sono copie identiche: etichette, nodi, persone, miniature,
impronte e le fotografie originali. È la scelta più pesante — decine di
gigabyte a ogni sincronizzazione e lo spazio doppio — ed è anche la più
chiara: non esiste il caso «su questa macchina questa cosa non c'è», che è il
caso in cui tutti gli altri programmi di sincronizzazione si perdono.

**Aggiunto dopo, perché mancava davvero:** viaggiano anche **le
impostazioni** — ma solo quelle che vogliono dire la stessa cosa sui due
computer: quante proposte vedi in colonna, se avvisare oltre il quarto
livello, quanti fotogrammi per video, la prudenza sui volti. Restano di
ciascuna macchina quelle che dipendono dalla macchina (regola 28): quanto
spingere la scheda video, lo schermo su cui giudichi i colori, il blocco
automatico, la forma dei filtri e della barra. E fra due valori diversi
decide la stessa regola delle etichette, la 404: vince quello cambiato dopo.
Se nessuno dei due porta una data — succede per gli archivi nati prima — vince
quello che è stato *deciso* contro quello rimasto com'era; se sono state
decise tutte e due, non si sceglie al posto tuo: si tiene quella di qui e la
schermata te lo dice (regola 69).

*Conseguenza pratica, da affrontare prima di cominciare:* decine di gigabyte
vogliono o un disco esterno o la rete di casa. Sulla rete di casa il progetto
sa già parlare (regola 189, i dispositivi approvati), e resta tutto dentro
casa: internet non c'entra comunque.

### 2. Stessa foto, stesso nodo, «sì» di qua e «no» di là — vince la più recente

Il registro sa quando ogni etichetta è stata toccata: sopravvive l'ultima. È
la regola facile da spiegare, «l'ultima parola è quella buona», e non chiede
niente all'utente. Dipende dagli orologi, e per questo c'è la 8.

### 3. Utente contro sistema — vince sempre l'utente

Se su una macchina l'ha deciso una persona e sull'altra l'ha indovinato il
programma, vince la persona, **anche se è più vecchia**. Questa regola sta
sopra la 2: la data decide solo fra due etichette della stessa origine. La
macchina non sovrascrive mai una scelta dell'utente (regole 18, 130, 313).

### 4. Lo stesso nodo creato due volte — stesso nome e stesso padre, è uno solo

«Vacanze 2026» creata su tutte e due le macchine sotto lo stesso ramo è un
nodo solo, e le fotografie delle due macchine finiscono insieme. Due nodi con
lo stesso nome sotto rami diversi restano giustamente due: due «Nonna» in due
posti diversi dell'albero non sono la stessa cosa.

### 5. Nodo cancellato di qua, usato di là — vince l'uso

Il nodo torna in vita, con dentro le fotografie nuove, e il programma dice che
era stato cancellato. Il motivo è asimmetrico e va scritto: **cancellare per
sbaglio si rimedia in un secondo, trenta etichette perse non si rimediano.**
Questa è l'unica risposta delle nove che sceglie di disobbedire a un comando
esplicito dell'utente, e lo fa apposta.

### 6. Le persone — si segnalano come «forse», non si fondono

Le due persone restano due, e il sospetto finisce in `forse_stessa_persona`,
la tabella che esiste già per questo. Il proprietario unisce guardando i due
volti affiancati. È la regola 69 rispettata invece che aggirata.

### 7. I cuori dal telefono — viaggiano, col nome del telefono attaccato

La riga del cuore arriva a tutte e due le macchine, ma resta legata al
telefono che l'ha messo: iPhone e Redmi non si fondono (regola 69). Il travaso
vero lo fa sempre e solo la macchina a cui è attaccato il cavo.

### 8. Gli orologi — si controllano, e se non tornano ci si ferma

Il pacchetto porta scritta l'ora della macchina che l'ha fatto. Se all'arrivo
l'altra è fuori di più di qualche minuto la fusione **non parte**, e lo dice in
italiano. Meglio fermarsi che fondere male in silenzio: senza questa, la
risposta 2 diventa una lotteria.

### 9. Chi fa il lavoro pesante — nessun ruolo fisso, ma non si rifà mai due volte

Le impronte viaggiano nel pacchetto come tutto il resto: se una fotografia ha
già la sua impronta, l'altra macchina non la ricalcola (regola 16; la regola 43
sa già con quale modello è stata fatta). Nessuna delle due macchine è «il
server»: chi ha tempo macina.

**L'addestramento invece non si ricicla, e non serve.** Il classificatore
leggero lavora su impronte già calcolate — «qualche centinaio di
moltiplicazioni su qualche decina di numeri: secondi, non minuti» — e parte da
zero facendo sempre gli stessi passi, quindi due addestramenti sugli stessi
esempi danno **lo stesso identico modello**. Arrivate le etichette, l'altra
macchina se lo rifà in pochi secondi e ottiene una copia identica, non simile.
Ciò che costa e va conservato sono le impronte; ciò che si impara da esse si
rifà.

---

## In quanti blocchi si fa

| | Blocco | Cosa contiene | Stato |
|---|---|---|---|
| 1 | Le decisioni | Le nove risposte qui sopra, ora regole 403-411. | **fatto** |
| 2 | Il registro | Schema versione 11, il nome della macchina, e la scrittura del registro a ogni modifica. | **fatto** |
| 3 | Il trasporto | Il pacchetto: scriverlo e rileggerlo. Chi lo porta da un PC all'altro resta fuori dal programma, di proposito. | **fatto** |
| 4 | La fusione | Le nove regole del blocco 1, in codice. | **fatto** (persone e cuori a parte) |
| 5 | La prova | Due archivi finti fatti divergere apposta su tutti e nove i casi, più i casi brutti: pacchetto letto due volte, a metà, nell'ordine sbagliato. | **fatto** |
| 6 | La faccia | Il pulsante, l'avanzamento, e la pagina dei volti da unire (risposta 6). | **fatto** |

I blocchi 2 e 3 sono lavoro dritto: si sa già cosa fare. Il 4 e il 5 sono la
parte che decide se la cosa funziona o no, e il 5 pesa quanto tutti gli altri
messi insieme.

Del 5 il blocco 4 si è già portato via un pezzo: le sedici prove di
`prove/test_sincronia_fusione.py` fanno divergere due archivi veri — non finti,
due database davvero — e li fondono, una prova per regola. Quello che resta al
blocco 5 è il giro lungo: l'archivio finto intero, i due sensi, e i casi brutti
messi in fila.

**Le nove risposte sono anche regole numerate: 403-411**, nella sezione 30 di
`sviluppo/REGOLE.md`. Questo documento si può riscrivere; quelle no (regola 164). Se un
giorno le due versioni non dicono la stessa cosa, quella buona è la regola.

---

## Cosa fare nel frattempo

Il secondo computer lavora con l'archivio **finto** (`--finto`). Non è un
ripiego: è il motivo per cui l'archivio finto esiste. Con quello si
programma, si provano le schermate, si fa girare il Visore nell'emulatore e
si misura. L'archivio vero resta su una macchina sola, dove non può
divergere da niente.

Il giorno in cui la sincronizzazione esiste, questo non va disfatto: si
aggiunge. Quel giorno adesso è arrivato per il codice ma non per l'archivio
vero: il primo giro vero si fa con calma, guardando cosa dice la schermata, e
con una copia di sicurezza fatta poco prima. Non perché ci si aspetti che
vada male — le prove dicono di no — ma perché la cosa che si sta muovendo è
l'unica di tutto il progetto che non si può rifare con un comando.
