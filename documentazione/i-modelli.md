# I modelli

*Regole 74, 101, 174, 175, 177, 178, 329.*

Il programma usa modelli **addestrati da altri**, che non cambiano mai e non
imparano niente dalle tue foto. Servono a trasformare un'immagine in numeri; a
imparare le tue etichette ci pensa un altro pezzo, piccolo e tutto locale.

---

## L'unico momento in cui il programma tocca la rete

> **74.** I modelli pre-addestrati si scaricano con un comando separato e
> dichiarato, che verifica l'integrità di ciò che scarica. Da quel momento in
> poi il programma non tocca più la rete e funziona a scheda di rete spenta.

Le **librerie** si installano da riga di comando, perché installare una
libreria non si fa da una pagina web:

```bash
pip install -r requirements-modelli.txt
```

I **pesi** si scaricano dal programma, dalla pagina **Salute**: una riga per
modello — a cosa serve, da dove arriva, quanto pesa, con che licenza — e
accanto il tasto.

**Perché un tasto non tradisce la regola 74.** La regola non chiede che toccare
la rete sia *scomodo*: chiede che sia *voluto e visibile*, e che si verifichi
ciò che arriva. Una riga che dice cosa sta per scaricare, premuta da chi la sta
leggendo, è quel momento esattamente quanto lo era un comando scritto a mano —
e verifica le stesse cose. Fuori di lì, prima e dopo, il programma funziona a
scheda di rete spenta.

**Mentre arriva, si vede a che punto è** (regola 429). Sotto le righe di quel
che sta succedendo c'è una barra con la percentuale e, accanto, i GB davvero
arrivati: «43% — 4,2 GB di circa 9,7 GB». Il conto non lo dà la libreria che
scarica, lo dà il disco — ogni due secondi si guarda quanto è cresciuta la
cartella, pezzi a metà compresi — e per questo è vero anche quando la stima del
peso è sbagliata: la percentuale può sbagliare, i GB no. La barra si ferma a
99% finché il lavoro non è finito davvero, perché una barra piena sopra un
lavoro che continua è una bugia.

Serve a una cosa sola, e non è l'impazienza: **distinguere una rete lenta da
una rete caduta.** PE-Core sono venti minuti buoni, e senza un numero che si
muove non c'è modo di sapere se aspettare o riprovare.

Il gettone di chi distribuisce i modelli **non è un campo di quella pagina**.
Un gettone è una password, e si legge dalla variabile d'ambiente `HF_TOKEN`,
come nel comando: non passa mai per un modulo, per il registro o per un
messaggio d'errore.

Il comando c'è ancora, per chi preferisce, e fa la stessa cosa:

```bash
python -m officina modelli --scarica tutti
python -m officina modelli --scarica volti
```

Sono quattro librerie più il decodificatore dei video e OpenCV, che fa girare
i due modelli dei volti. `torchvision` sta nella
lista pur non sembrando necessario: prepara l'immagine prima che il modello la
veda, non arriva insieme a `torch`, e senza di lui il caricamento si ferma a
metà lamentandosi di una classe interna. Il programma lo controlla prima e lo
dice col suo nome.

**Se `pip` rifiuta una versione**, togli il numero e lascia solo il nome. Le
versioni di `requirements.txt` sono state installate e provate davvero; quelle
dei modelli no — pesano gigabyte e non sono passate per la macchina su cui il
programma è stato scritto. Sono state però controllate una per una contro
l'elenco di PyPI: esistono tutte. Sono fissate per la disciplina della regola
1, non perché il programma dipenda da quel numero preciso.

Vale lo stesso per i nomi dei due modelli: sono quelli giusti ad agosto 2026,
ma un modello può cambiare nome o chiedere di accettare le sue condizioni sul
sito di chi lo distribuisce prima di lasciarsi scaricare. Se succede, il
comando dice in italiano **quale** delle due è successa e cosa fare, e tutto
il resto del programma continua a funzionare.

Fuori da quel comando gli interruttori dell'*offline* sono accesi: se una
libreria provasse a controllare da sola se online c'è una versione più nuova,
fallirebbe invece di riuscire. Non è una promessa, è come è scritto il codice
(`officina/descrittori/torcia.py`, prime righe).

### Cosa viene verificato

Di ogni file scaricato si scrive quanto pesa e la sua impronta — la stessa
funzione che riconosce le foto (regola 39). Accanto ai pesi finisce una scheda
con il nome del modello, la data e la licenza.

```bash
python -m officina modelli --verifica
```

Rilegge tutto e ricalcola: un modello rovinato da un disco che invecchia si
scopre quando lo si controlla, non a metà di una notte di calcoli.

---

## Quali sono, e perché

### DINOv3 ViT-L/16 — lo sguardo visivo puro

- **si chiama:** `facebook/dinov3-vitl16-pretrain-lvd1689m`
- **pesa:** circa 1,2 GB · impronta di 1024 numeri
- **licenza:** DINOv3 License (Meta), uso personale consentito
- **chiede il permesso:** sì — bisogna avere un conto sul sito, accettare le
  condizioni e **dare a chi lo distribuisce il proprio recapito**, e la
  richiesta passa da un'approvazione che può metterci ore o giorni

I modelli di sola visione battono costantemente quelli visione+linguaggio sui
compiti immagine-contro-immagine: quasi-duplicati, ricerca inversa, e la
corrispondenza fine tra prodotti — che è letteralmente il caso degli oggetti
specifici in fondo all'albero (regola 174).

### SigLIP 2 so400m — lo sguardo che capisce anche le parole

- **si chiama:** `google/siglip2-so400m-patch14-384`
- **pesa:** circa 3,5 GB · impronta di 1152 numeri
- **licenza:** Apache 2.0, libera
- **chiede il permesso:** no — si scarica e basta

Standard aperto attuale per l'accoppiata immagine-testo. Due proprietà che
servono a questo progetto: è multilingue su 109 lingue, il che alleggerisce il
problema dell'italiano nella ricerca (regola 137); ed è addestrato con una
funzione che produce punteggi di somiglianza meglio calibrati (regola 175).

### PE-Core-G14 — il terzo sguardo, ed è in prova

- **si chiama:** `facebook/PE-Core-G14-448`
- **pesa:** 9,7 GB da scaricare · impronta di 1280 numeri
- **licenza:** Apache 2.0, libera
- **chiede il permesso:** no — si scarica e basta

Fa lo stesso mestiere di SigLIP 2 — immagini e parole nello stesso spazio — ma
con quasi due miliardi di numeri invece di quattrocento milioni. Due terzi del
lavoro di una notte se ne va qui dentro.

**Per questo non resta per diritto acquisito** (regola 420). I due si sfidano
su trecento fotografie, una sera sola, e quello che sbaglia di più esce. Se
esce questo, le notti passano da nove-tredici a circa quattro; se esce l'altro,
si sono risparmiate delle impronte inutili. In nessuno dei due casi si tengono
tutti e due «per sicurezza»: due modelli parenti che dicono la stessa cosa non
sono due opinioni, sono la stessa opinione contata due volte.

**Questo è l'unico che non si carica come gli altri due**, e vale la pena
sapere perché. Nel deposito da cui si scarica non c'è nessun file di
configurazione: c'è un unico file da 9,7 GB, in un formato che oltre ai numeri
può contenere istruzioni da eseguire. Costruirci sopra il modello richiedeva il
codice di chi l'ha fatto, che si prenderebbe da GitHub tirandosi dietro una
catena di pacchetti che nessuno legge davvero.

Non è andata così. Di quel codice serviva solo la metà che guarda le
immagini — meno di quattrocento righe — e quella è stata **copiata dentro il
programma**, con la sua licenza (Apache 2.0) e la sua attribuzione, invece che
installata. Sta in `officina/descrittori/pe_visione.py`, si può leggere tutta,
e non si muove. Le due librerie che si portava dietro sono sparite: il terzo
modello è entrato **senza aggiungere una sola riga** all'elenco dei pacchetti
da installare (regola 428).

Il file da 9,7 GB si attraversa una volta sola, con il lettore che le
istruzioni non le esegue — davanti a una si rifiuta di aprire il file. Subito
dopo i pesi vengono riscritti nel formato degli altri due, dove le istruzioni
non ci possono stare, e il file di partenza viene cancellato. Sul disco restano
circa 7,5 GB. Da quel momento PE-Core si accende come DINOv3 e SigLIP 2.

Della sua metà che legge le parole non c'è niente in casa: la ricerca a parole
passa da SigLIP 2, e tenere quattro giga di pesi che nessuno chiama vorrebbe
dire non sapere più cosa si ha (regola 74). Le impronte delle immagini sono le
stesse.

*Una nota onesta.* Anche così, questo modello non ha ancora girato su nessuna
macchina vera. Quello che si sa è che l'architettura è quella giusta — il conto
dei pesi torna al milione, 1,882 miliardi — e che i pezzi riscritti a mano
danno gli stessi numeri dell'originale, confrontati uno per uno. Quello che non
si sa lo dirà la prima notte: se qualcosa non torna, il messaggio è in italiano
col comando che rimedia, e gli altri due continuano a funzionare senza di lui.

### I volti: SCRFD e AdaFace

**SCRFD-10GF** trova le facce e **AdaFace R100** le riconosce, circa 266 MB in
due. Trovano facce piccole e di profilo, e reggono bene quelle sfocate e di
taglio, che nelle fotografie di casa sono la maggioranza.

- **licenza:** InsightFace, **uso non commerciale**. Per un archivio di
  famiglia va bene, e sta scritto perché «cosa ho in casa e cosa posso farci»
  deve avere una risposta senza doverla cercare (regola 177).
- **gira con:** `onnxruntime`. Il conto che legge le uscite di SCRFD è scritto
  in casa (`officina/volti/insight.py`) ed è provato senza i modelli.

Prima c'erano anche YuNet e SFace, più piccoli. Sono stati tolti (regola 495):
i nuovi fanno lo stesso lavoro e meglio. Se nella cartella dei modelli sono
rimasti i loro due file, il programma li cancella quando scarica i nuovi.

*Prima di misurare c'è il raddrizzamento*:
la faccia girata dritta dentro un quadrato di 112 pixel prima di essere
misurata. È il pezzo che se sbaglia di poco funziona lo stesso e dà il
risultato sbagliato, ed è per questo che ha un file suo, tre prove al pixel, e
una pagina — «Le facce raddrizzate», da Stato — dove lo si guarda con gli occhi
su facce inventate.

### SeedVR2 7B FP8 — quello che migliora foto e video

- **si chiama:** SeedVR2 7B, nella versione a otto bit preparata da
  `numz/ComfyUI-SeedVR2_VideoUpscaler`
- **pesa:** circa 9 GB da scaricare, fra pesi e decodificatore
- **licenza:** Apache 2.0, libera
- **esegue codice di terzi:** sì, ed è scritto nella sua riga

Porta foto e video piccoli alla misura FHD (regola 472). Nei video guarda più
fotogrammi insieme — pezzi da 41, e ognuno riparte dagli ultimi 4 del pezzo
prima — così i dettagli restano fermi invece di tremolare (regola 476).

Il suo codice è troppo per copiarlo in casa, quindi entra come dice la regola
477: 93 file scaricati a una versione precisa, ognuno con la sua impronta, e
se anche uno solo non corrisponde non entra niente. Le librerie che chiede
stanno in una parte separata, e tutto gira in un processo a parte, a rete
spenta. Un solo «Scaricalo» fa tutto: prima le librerie, poi il codice, poi i
pesi.

### CodeFormer — quello che sistema i volti nelle foto

- **si chiama:** `sczhou/CodeFormer` v0.1.0, più ParseNet per la sagoma
- **pesa:** circa 460 MB da scaricare
- **licenza:** S-Lab 1.0, **uso non commerciale**
- **esegue codice di terzi:** no — il codice è copiato in casa

Dopo SeedVR2 trova i volti con SCRFD (lo stesso dei volti, che si scarica
insieme se manca), li raddrizza, li ripulisce e li rimette nella foto
seguendo il contorno del viso: capelli, orecchie e sfondo restano quelli di
SeedVR2. Li sistema **tutti**, anche i più piccoli. La manopola fra
«somigliante» e «bello» sta a **0,7**, dalla parte di chi deve restare sé
stesso.

Il codice delle due reti è **copiato dentro il programma** (regola 428), in
`officina/miglioria/codeformer_rete.py`, con la sua licenza e l'attribuzione
nel file accanto. Prima di tenerlo è stato confrontato con l'originale sugli
stessi pesi: le uscite sono identiche. I due file dei pesi arrivano in un
formato che può contenere istruzioni: si attraversano una volta sola con il
lettore che non le esegue, si riscrivono in `safetensors`, e gli originali si
cancellano.

### FaceMe — quello che sistema i volti guardando le foto di riferimento

- **si chiama:** `modyu-liu/FaceMe`, costruito sopra RealVisXL 3.0 (SDXL), con
  il lettore dei volti di PhotoMaker e i due modelli antelopev2 di InsightFace
- **pesa:** circa 12 GB da scaricare
- **licenza:** Pi-Lab 1.0 e InsightFace, **uso non commerciale**
- **esegue codice di terzi:** no — i pezzi che servono sono copiati in casa

Serve ai volti che **nell'archivio hanno già un nome**, sia che l'abbia messo
tu sia che l'abbia proposto il programma e tu abbia dato un nome al gruppo.
Per ognuno prende le foto di riferimento di quella persona dalla sua cartella
(regola 478); se la cartella non c'è più usa i suoi volti già nell'archivio.
Fra quelle sceglie **4**, com'è stato addestrato: le più nitide fra quelle con
la testa girata più simile al volto da sistemare, e se sono meno di 4 le
ripete. I volti senza nome passano da CodeFormer.

Quando FaceMe e CodeFormer sono scaricati **si accendono da soli**: con FaceMe
i volti con un nome vanno a lui e gli altri a CodeFormer; con il solo
CodeFormer vanno tutti a CodeFormer. Nelle impostazioni si possono spegnere.

Ogni volto chiede circa 10-20 secondi sulla scheda: 50 passi di SDXL, sempre
con lo stesso seme, così la stessa foto dà sempre lo stesso risultato.

Il codice copiato (il miscelatore, il lettore di PhotoMaker e la correzione dei
colori) è in `officina/miglioria/faceme_rete.py`, con la licenza accanto; è
stato confrontato con l'originale e dà le stesse uscite. Anche la lettura
delle foto di riferimento è rifatta in casa, senza la libreria insightface, e
dà gli stessi volti e le stesse impronte. La frase fissa che FaceMe si aspetta
si calcola **una volta sola** allo scaricamento: dopo, i due lettori di testo
di SDXL si buttano, e sul disco restano un paio di GB in meno.

I file di antelopev2 arrivano da GitHub e si controllano con un'impronta
scritta nel programma; quelli presi da Hugging Face si controllano con
l'impronta che Hugging Face stesso dichiara per quella versione, e la versione
resta scritta accanto.

### Qwen3.5 9B — quello che legge, descrive e capisce la domanda

- **si chiama:** `Qwen/Qwen3.5-9B`
- **pesa:** circa 19 GB da scaricare, circa 8 GB sul disco dopo la compressione · non fa impronte
- **licenza:** Apache 2.0, libera
- **chiede il permesso:** no — si scarica e basta
- **esegue codice di terzi:** no — il suo codice sta dentro `transformers`
- **vuole:** una scheda video NVIDIA; compresso a 4 bit ne occupa circa 7 GB

Fa tre lavori che prima facevano due modelli piccoli, Florence-2 e Qwen3 0.6B.

- **Legge le scritte** dentro le foto: insegne, cartelli, menu, targhe, anche
  storte o scritte a mano. Sono l'unica cosa di una foto che si cerca **per
  lettera**: «trattoria del ponte» non assomiglia a niente, c'è scritto.
- **Scrive una frase breve** su ogni foto, in italiano: «due persone su una
  barca al tramonto». La ricerca la usa come le scritte, e trova anche quello
  che le impronte non colgono.
- **Capisce la domanda** della ricerca: la traduce in inglese, dove SigLIP è più
  preciso (regola 268), e la riscrive in due o tre modi.

Una sola domanda per foto dà sia la descrizione sia le scritte. Passata a parte,
tabelle sue (`scritte` e `descrizioni`), si accende quando vuoi tu e si può
fermare a metà: riprende da dove era.

**Perché compresso.** Intero pesa 19 GB e non entra in una scheda da 12. Dopo lo
scaricamento il programma lo comprime una volta sola a 4 bit (nf4); la parte che
guarda le immagini resta intera, per leggere meglio. Il modello intero si butta
e resta solo la copia compressa.

**Cosa non può fare, per costruzione.** Non decide niente e non crea etichette
(regola 271): scrive testo che si cerca, e basta. Tutto succede su questo
computer: le foto non escono mai.

*Una nota onesta.* Su Windows mancano due acceleratori che questo modello sa
usare (`flash-linear-attention` e `causal-conv1d`), quindi gira con la versione
più lenta di quei pezzi. Quanto più lenta lo dice la prima notte sul fisso.

### Disegnato a mano — il metro di paragone

- **pesa:** zero · impronta di 352 numeri
- **licenza:** è codice di questo progetto

**Non è intelligenza artificiale e non finge di esserlo.** È un conto sui
pixel: dove stanno i colori, in che direzione vanno i bordi, quanto è ruvida
ogni zona. Esiste per tre motivi, e ognuno vale da solo:

- fa girare **tutta** la catena della tappa 2 senza scaricare un byte, che è
  quello che chiede la regola 341 (prima il finto, poi il vero);
- è il metro con cui si legge il resto: *quanto meglio di un conto sui colori?*
- se un giorno le librerie non si installano più, o la scheda video muore, il
  programma continua a funzionare — peggio, e dicendolo.

*Sui suoi limiti, chiaramente:* non sa cosa sia un oggetto. Riconosce che due
foto sono state fatte nello stesso posto con la stessa luce, e sbaglia
sistematicamente ogni volta che la stessa cosa è fotografata in due condizioni
diverse.

---

## Con quanti bit

Un numero con la virgola si può tenere in memoria con **trentadue bit** o con
**sedici**. A sedici occupa la metà e si calcola quasi il doppio più in fretta;
in cambio si perdono le cifre in fondo. Su una scheda da 12 GB non è una
raffinatezza: è la differenza fra un modello che ci sta e uno che non ci sta.

| Modello | Numeri | Come gira | Occupa |
|---|---|---|---|
| DINOv3 ViT-L | 0,3 mld | trentadue bit | 1,2 GB |
| SigLIP 2 so400m | 0,4 mld | trentadue bit | 1,6 GB |
| PE-Core-G14 | 1,9 mld | sedici bit | 3,8 GB (7,5 sul disco) |

I primi due nei 12 GB ci stanno larghi e non c'è nessuna ragione di buttare via
delle cifre (regola 414). Il terzo a precisione piena sarebbe 7,6 GB di soli
pesi e non ci entra: costringerebbe a lavorare a due immagini per volta e a
passare da nove a venticinque notti.

Prima qui c'era una riga sola che decideva in base alla **scheda video**: se
c'era una GPU, sedici bit per tutti. Così due modelli su tre perdevano cifre
per niente. L'unica cosa che dipende ancora dalla macchina è il contrario:
*senza* scheda video i sedici bit non si usano, perché sul processore sono più
lenti e non più veloci.

**La precisione sta scritta dentro la versione dell'impronta** (regola 415):
`dinov3@2-f32`, `pecore@1-f16`. Non è pignoleria — la stessa immagine guardata
a sedici bit e a trentadue dà numeri diversi, e il programma decide cosa
rifare guardando nome e versione. Se la precisione non entrasse lì dentro, il
giorno in cui metà archivio venisse rifatto con l'altra impostazione i due
pezzi verrebbero confrontati come se fossero la stessa cosa: in silenzio, senza
nessun errore, e per sempre.

**Le impronte si conservano comunque a trentadue bit** (regola 417). Calcolare
a metà precisione e conservare a metà precisione sono due decisioni separate:
quello che esce dal modello grande viene riportato a trentadue prima di finire
nel database. Costa il doppio di disco, che non manca, e zero tempo — e le
impronte dei tre modelli restano confrontabili fra loro senza conversioni.

**E appena caricato, si controlla** (regola 416). Il nome dell'impostazione che
sceglie i bit è cambiato fra una versione e l'altra della libreria: `dtype` in
quelle nuove, `torch_dtype` in quelle vecchie. Passare quello sbagliato **non
dà nessun errore** — carica a precisione piena e va avanti. Innocuo su DINOv3,
fatale sul modello grande: riempie la scheda a metà della notte con un
messaggio che parla di memoria e non dice il vero motivo. Perciò dopo il
caricamento il programma guarda un peso vero e verifica che sia del tipo che ha
chiesto, e se non lo è si ferma subito.

---

## Perché due, e non uno

> **101.** Due famiglie di descrittori insieme: visivo puro e visione+linguaggio.
> *Costo:* il doppio del tempo di importazione, una volta sola. *In cambio:* è
> anche l'ensemble, ottenuto sul pezzo che non si riaddestra — due sguardi
> diversi sulla stessa immagine, senza pagare il triplo a ogni modifica.

È esattamente una delle cose che la misura della tappa 2 verifica. Se il
rapporto dice che tenerli tutti e due non cambia niente, la regola 101 va
rimessa in discussione (regola 343) — e la misura lo scrive da sola.

---

## Uno alla volta

> **329.** I modelli si accendono uno alla volta.

I due descrittori più i volti più il modello linguistico non stanno insieme in
12 GB di scheda, e non serve che ci stiano: l'importazione fa **una passata per
descrittore**. Il programma ne tiene acceso uno e libera la scheda prima del
successivo.

```bash
python -m officina impronte --tutti
```

Costa qualche minuto su una notte sola, e permette di tenere le versioni grandi
— che era il punto della regola 178.

---

## Quanto stressare la scheda

```bash
python -m officina impronte --intensita 50
```

Da 5 a 100 (regola 182). «Usare il 10% della scheda» non è un'impostazione che
esista: l'effetto si ottiene lavorando a intervalli con pause in mezzo. A 100
non si ferma mai; a 50 un pomeriggio diventa due; a 10 dieci notti invece di
una, con la scheda tiepida.

Se la scheda supera la soglia di temperatura, rallenta da sola e riprende
quando si è raffreddata (regola 181) — e lo dice, invece di lasciarlo scoprire
dal rumore delle ventole. La temperatura si legge solo se c'è `nvidia-ml-py`;
senza, il programma dice che non lo sa invece di inventare un numero.

---

## Se chiede il permesso

Alcuni modelli non si lasciano scaricare da chiunque: prima vogliono che si
accettino le loro condizioni, sul sito di chi li distribuisce. Non è una
protezione tecnica, è un contratto — ma finché non lo si firma, il download
risponde con un errore.

C'è un dettaglio che confonde e che vale la pena sapere in anticipo: **un
modello che chiede il permesso, a chi non ha una chiave, risponde che non
esiste.** È voluto. Non vuole nemmeno ammettere di esserci. Per questo il
messaggio di errore dell'Officina tratta le due cose insieme e manda a
guardare la pagina del modello, che scioglie il dubbio in due secondi: se si
apre e chiede di accettare qualcosa, è il permesso; se dice che non esiste
davvero, il modello ha cambiato nome e va corretta la scheda.

Accettate le condizioni, serve un gettone di lettura — si crea sul sito, nelle
impostazioni del proprio conto — e si passa al comando:

    python -m officina modelli --scarica dinov3 --chiave GETTONE

oppure, per non scriverlo nella riga di comando, nella variabile `HF_TOKEN`.

Quel gettone è una password, e viene trattato come tale: **non finisce da
nessuna parte.** Non nel registro, non nella scheda scritta accanto ai file,
non nei messaggi di errore — c'è una prova che glielo mette in mano apposta e
controlla che non ricompaia. Serve una volta, per quel download, e finisce lì.

---

## Se non ci sono

Tutto continua a funzionare. Le impronte si calcolano con il descrittore
disegnato a mano, la misura gira, la ricerca per somiglianza funziona — peggio,
e il programma lo dice in ogni schermata in cui conta.

```bash
python -m officina dottore
```

dice sempre cosa c'è e cosa manca, con il comando per rimediare.

---

## Dove stanno

I modelli scaricati stanno **accanto** ai due archivi, non dentro nessuno dei
due. Li usano sia l'archivio finto sia quello vero, e si scaricano una volta
sola.

Il motivo è quello che rende questa cartella diversa da tutte le altre: non
contiene niente di tuo. Sono pesi addestrati da altri su immagini di altri, e
si possono cancellare e riprendere in qualsiasi momento. Tenerne una copia
dentro ciascun archivio vorrebbe dire cinque gigabyte in doppio, e — molto
peggio — scaricarli da una parte e cercarli dall'altra.

Quello che invece **è** tuo, cioè ciò che il programma impara dalle tue
etichette (regola 103), sta in `imparato`, dentro l'archivio: si ricava dalle
tue scelte e da nessun'altra parte, e il giorno del contenitore cifrato ci
entra insieme al resto (regola 340).

Se hai scaricato un modello quando stava ancora dentro l'archivio, il
programma lo **sposta** all'avvio invece di rifartelo scaricare.

---

## Cosa non finisce mai nella cartella dei modelli

Niente che riguardi l'archivio. Sono pesi addestrati da altri su immagini di
altri: è **l'unica cartella del progetto il cui contenuto non è un dato
personale**, ed è anche l'unica che si può riscaricare invece che salvare.

```bash
python -m officina modelli --togli dinov3
```
