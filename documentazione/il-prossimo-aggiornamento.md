# Il prossimo aggiornamento

*Regole 412-423. Il piano di quello che c'è da fare, nell'ordine in cui va
fatto, con scritto accanto quanto costa e come si vede se ha funzionato.*

Oggi il programma guarda le fotografie con dei modelli piccoli, una sola
occhiata per foto, e i volti li trova con un rilevatore di quelli semplici.
Questo aggiornamento cambia tre cose: **occhi migliori** (modelli grandi),
**più occhiate per foto** (la griglia), e **volti riconosciuti sul serio**.

Non è un aggiornamento che si fa in un pomeriggio: alla fine c'è un lavoro di
alcune notti sull'archivio intero. Per questo è diviso in blocchi che si
possono fermare in mezzo.

---

## Quello che è già fatto

**Il freno** (regola 412). La pausa era tagliata a trenta secondi e col
cursore al 50% la macchina lavorava al 67. Adesso aspetta tutto il tempo
dovuto, un secondo per volta, e il tasto «Ferma» risponde subito lo stesso.
Corretto, provato e già dentro.

**Il blocco 3, i modelli grandi.** DINOv3 e SigLIP 2 girano a trentadue bit,
PE-Core-G a sedici, la precisione sta dentro la versione dell'impronta, i pesi
si controllano appena caricati, e le impronte si conservano a trentadue bit
comunque. PE-Core-G è entrato, e è entrato **in prova**: la sfida con SigLIP 2
resta da correre.

**Il blocco 2, la griglia adattiva.** Otto caselle sul lato lungo, quadrate nei
pixel veri, con la migrazione che allarga il controllo sulla colonna
`inquadratura`. Si accende dalle Impostazioni, ed è spenta di partenza perché
costa notti. Come si sommano le quaranta caselle — massimo o media — sono
scritti tutti e due: quale sia meglio lo decide la misura, non un'opinione.

**Il blocco 1, il raddrizzamento delle facce.** Il conto sta in un file suo,
con le tre prove del piano più due che il piano non chiedeva, e con la pagina
«Le facce raddrizzate» da guardare con gli occhi (facce inventate, mai le tue).
SCRFD-10GF e AdaFace R100 ci sono, e ci sono **accanto** ai due di sempre, non
al loro posto: si scaricano da Stato, si accendono dalle Impostazioni, e finché
non lo fai non cambia niente. Il conto che legge le loro risposte è provato con
uscite note, senza avere i modelli. Resta da fare l'unica cosa che qui non si
poteva fare: **accenderli su una macchina vera e guardare**.

**Il blocco 4, le parole dentro le fotografie.** Florence-2-large, tabella sua,
passata sua che riprende da dove era, ricerca per lettera, e «esegue codice di
terzi» scritto nella sua scheda e mostrato nella pagina Salute.

---

## Blocco 1 — I volti

**Cosa cambia per te.** Il programma smette di dire «qui c'è una faccia» e
comincia a dire «questa faccia è la stessa dell'altra foto». I nomi che hai già
dato **restano**: si rifanno il ritrovamento dei volti e i gruppi automatici,
non le tue decisioni.

**Cosa si mette dentro.** SCRFD-10GF per trovare i volti, AdaFace R100 per
riconoscerli. La licenza di InsightFace non è per uso commerciale, e questo va
scritto nella scheda del modello insieme al peso e alla provenienza.

**Come si vede che funziona.** Il pezzo delicato è raddrizzare la faccia prima
di guardarla: se è storta di poco, il riconoscimento sbaglia e sembra che
funzioni. Tre prove:
1. una faccia finta con gli occhi in coordinate note, che deve uscire diritta
   al pixel giusto;
2. la stessa faccia ruotata e rimpicciolita deve dare la stessa impronta;
3. un confronto con OpenCV, una volta sola, per vedere che i due sono
   d'accordo.
Più una pagina che fa vedere una manciata di facce finte già raddrizzate, da
guardare con gli occhi (regola 114: facce inventate, mai le tue).

---

## Blocco 2 — La griglia adattiva

**Cosa cambia per te.** Oggi una fotografia viene guardata intera, e una cosa
piccola in un angolo si perde. Con la griglia viene guardata anche a pezzi: il
cane in fondo alla spiaggia diventa trovabile.

**Come si taglia** (regola 419): otto caselle sul lato lungo, quante servono sul
corto perché i ritagli restino quadrati nei pixel veri, un decimo di
sovrapposizione, 512 pixel per casella. In media 35-45 pezzi per fotografia:
48 su una foto verticale da telefono, 40 su un fotogramma da schermo, 16 su una
panoramica.

**Cosa va toccato prima.** La tabella delle impronte accetta solo tre parole
per dire da dove viene un ritaglio (`intera`, `persona`, `stretto`). Serve una
**migrazione nuova** che allarghi quel controllo — il file dello schema è la
versione 1 e non si modifica mai.

**La decisione che manca ed è da misurare** (regola 105): quando una foto ha
quaranta impronte invece di una, il classificatore come le mette insieme? Il
massimo (basta un pezzo che dica «cane») o la media (conta l'insieme)? Si prova
sui due modi e si tiene quello che sbaglia meno, non quello che suona meglio.

---

## Blocco 3 — I modelli grandi

**I tre modelli e come girano** (regola 414):

| Modello | Numeri | Precisione | Occupa |
|---|---|---|---|
| DINOv3 ViT-L | 0,3 mld | piena, 32 bit | 1,2 GB |
| SigLIP 2 so400m | 0,4 mld | piena, 32 bit | 1,6 GB |
| PE-Core-G14 | 1,9 mld | mezza, 16 bit | 3,8 GB |

I primi due nei 12 GB della scheda stanno larghi e non c'è ragione di buttare
via cifre. Il terzo a precisione piena sarebbe 7,6 GB di soli pesi e non ci
sta: costringerebbe a lavorare a due immagini per volta e a passare da nove a
venticinque notti.

**Tre cose da fare insieme ai modelli:**
- la precisione entra nella **versione** dell'impronta (regola 415), altrimenti
  un giorno mezzo archivio a 16 bit e mezzo a 32 vengono confrontati come se
  fossero uguali, in silenzio e per sempre;
- appena caricato un modello si **controlla** che i pesi siano davvero del tipo
  chiesto (regola 416): sbagliare il nome dell'impostazione non dà nessun
  errore, carica a precisione piena e riempie la scheda;
- le impronte si **conservano a 32 bit** anche quando sono calcolate a 16
  (regola 417): costa disco, che non manca, e zero tempo.

**La prova dei cento** (regola 414). Cento fotografie fatte nei due modi,
confrontate: dice se quei bit in più si vedono davvero. Costa un'ora.

**La sfida** (regola 420). SigLIP 2 e PE-Core-G sono parenti stretti e
probabilmente dicono la stessa cosa due volte. Trecento foto, una sera sola, e
esce quello che ha ragione. Se esce PE le notti scendono da nove-tredici a
circa quattro.

---

## Blocco 4 — Le parole dentro le fotografie

Florence-2-large (MIT, circa 1,5 GB) legge il testo che c'è nelle immagini: le
insegne, i cartelli, le targhe delle mostre. Passata a parte, tabella sua,
ricerca a parole.

**Una cosa va detta chiara** (regola 418). Gli altri tre modelli sono soltanto
numeri, e un file di numeri non «fa» niente. Florence-2 invece chiede di
scaricare **ed eseguire** codice Python di terzi su questa macchina. Non è
un'accusa — è codice pubblico di Microsoft — ma è l'unico punto del progetto in
cui il blocco totale poggia su una fiducia invece che su un fatto. Perciò: si
scarica una volta sola col comando dichiarato, dicendo prima cosa arriva; la
rete resta spenta dopo; e nella sua scheda c'è scritto «esegue codice di terzi»
mentre negli altri tre c'è scritto di no.

---

## Quanto dura

Nove-tredici notti per diecimila immagini, tre modelli, cursore al 50%, su una
RTX 3060 da 12 GB. Più circa tre notti per la precisione piena sui due piccoli.
Meno circa cinque se dalla sfida esce PE.

È un conto a mano e può sbagliare del doppio (regola 421). La stima vera la
misura il programma dopo una cinquantina di foto e la scrive sulla pagina: il
numero scritto qui serve a decidere **se** cominciare, non a sapere quando
finisce. E si può fermare a metà in qualunque momento: riprende da dove era.
