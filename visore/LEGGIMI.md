# Il Visore, la parte che esiste

Qui dentro c'è **il lettore del pacchetto** e **le otto schermate**, scritti in
Kotlin (regola 386). Le otto decisioni di aspetto sono prese, guardando le tre
bozze per una in [`sviluppo/bozze/visore/`](../sviluppo/bozze/visore/) (regola 180); il formato
del pacchetto era deciso da un pezzo (regole 358, 366, 372).

Quello che manca è una cosa sola, ed è dichiarata: il pacchetto vero su Android
non si apre ancora (regola 387). Fino a quel giorno le schermate mostrano la
loro forma e non fingono di avere foto.

## Cosa sa fare

Quello che farà l'app quando la si apre, nello stesso ordine:

1. legge `visore.json`, la carta d'identità, che è l'unico file in chiaro;
2. se il pacchetto è più nuovo del programma **si ferma con una frase**, invece
   di leggersi a metà (regola 372);
3. trasforma la password in chiave con `scrypt` e la prova sul blocco di prova:
   sbagliata lo dice subito, senza aver aperto un solo file;
4. decifra il database **in memoria**, e non lo scrive in chiaro da nessuna
   parte;
5. da lì in poi risponde alle domande del telefono — i giorni, gli scatti,
   l'albero, le persone, «spesso insieme a», la ricerca — apre le foto e le
   miniature, tira fuori il `.MOV` di una live photo, salta a metà di un video
   senza leggere quello che viene prima (regola 376);
6. e rilegge tutto il pacchetto ricontrollando **le impronte una per una**: è il
   pacchetto che verifica se stesso, senza chiedere niente al PC.

## Cosa sa scrivere

Una cosa sola, ed è l'unica del pacchetto che non fa il PC: `ritorno.db`, dove
stanno i cuori, le raccolte e il diario (regole 68, 380, 381). È insieme il
magazzino del telefono e la busta che torna indietro — non c'è un secondo elenco
da tenere allineato (regola 391) — ed è cifrato come tutto il resto.

Ogni gesto scrive (regola 390): il cuore si mette con un tocco, e quel tocco
salva. Il file si scrive di fianco e si sposta alla fine, così un'interruzione
lascia intero quello di prima.

All'avvio ci sono tre casi e sono tutti normali: c'è già e si continua; non c'è,
e allora si riprende dalla copia di scorta che il pacchetto si porta dietro —
è la promessa «reinstallare non perde niente»; c'è ma non si apre, e allora si
riparte dalla scorta dicendolo una volta sola. In tutti e tre si applicano i
**cuori tolti dal computer**, che è la sola eccezione voluta alla regola 68.

## Com'è diviso, e perché

| Pezzo | Cosa c'è dentro | Da cosa dipende |
|---|---|---|
| `lettore/` | il formato, la cifratura, il pacchetto | niente, a parte `org.json` — che su Android è già nel sistema |
| `computer/` | il database aperto in memoria, e un comando per guardarci dentro | `lettore`, SQLite via JDBC |
| `telefono/` | quello che l'app dice: l'apertura, e la prima schermata | `lettore`, e nient'altro |
| `app/` | i pixel: le schermate disegnate con Compose | `telefono`, e l'SDK di Android |

`telefono/` dipende da `lettore` e **non** da `computer`. È così che si sa,
guardando le dipendenze e non le intenzioni, che nel lettore non è entrato
niente che sul telefono non ci sia — e non è una promessa: la controllano le
prove in [`prove/test_modulo_telefono.py`](../prove/test_modulo_telefono.py),
che leggono il file delle dipendenze e si rompono il giorno in cui qualcuno,
per fare in fretta, ci porta dentro il pezzo del computer.

`telefono/` **non** è un modulo Android, ed è voluto: qui dentro non c'è una
riga che parli di Android, e per questo le sue prove girano su qualsiasi
computer, anche uno appena acceso. Chi parla di Android è `app/`, che sta
sopra e dipende da lui — mai il contrario.

E `app/` entra nel progetto **solo dove l'SDK di Android c'è**: lo decide
`settings.gradle.kts`, guardando `local.properties` e le variabili d'ambiente.
Dove l'SDK non c'è, il modulo resta fuori dicendolo, e `gradlew test` prova
lo stesso il lettore e tutte le otto schermate. È questa la ragione della
divisione: la metà del Visore che si può provare senza niente non deve
diventare ostaggio di sei gigabyte di SDK.

Dentro c'è `Sessione`, che è l'avvio dell'app scritto una volta: si aprono il
pacchetto e `ritorno.db`, si tengono aperti finché l'app è aperta, si chiudono
insieme. Sopra ci staranno le schermate; sotto c'è il lettore, già provato; in
mezzo non c'è nient'altro, perché quello che manca è un modo di **mostrare**,
non un secondo modo di leggere.

L'unica cosa che a `Sessione` serve da fuori è la porta del database — chi sa
aprirlo dai byte — ed è esattamente il buco dichiarato qui sotto. Oggi al suo
posto c'è `PortaNonAncoraScelta`, che non fa finta di niente: si ferma con una
frase intera che dice che quella decisione non è stata presa.

E ci sono **le otto schermate**, tutte, nella parte che si può scrivere oggi:
quello che ognuna *dice* — quali gruppi, in che ordine, con che parole e con
che numeri. I pixel arrivano con Compose il giorno di Android Studio, e quel
giorno questi file non cambiano: è per questo che sono scritti a parte, ed è
per questo che si provano oggi, senza un telefono e senza un emulatore.

| File | Schermata | Le regole |
|---|---|---|
| `Apertura.kt` | la password, la firma, quando va male | 115, 357, 382, 392, 393 |
| `Giorni.kt` | la griglia dei giorni | 251, 363, 374, 394 |
| `FotoAperta.kt` | la foto aperta, i gesti, le informazioni | 253, 254, 375, 395, 399 |
| `Nodi.kt` | l'albero, e l'interruttore «solo qui» | 236, 377, 401 |
| `Persone.kt` | le facce, e «tutte e due» | 362, 364, 377, 396, 397 |
| `Cerca.kt` | la ricerca, e il vuoto che dice perché | 378, 398 |
| `Preferiti.kt` | preferiti, raccolte, e mentre si sceglie | 68, 69, 373 |
| `Sezioni.kt` | le quattro sezioni in fondo | 373 |

E adesso sono **disegnate tutte e otto**, in
[`app/src/main/kotlin/visore/app/`](app/src/main/kotlin/visore/app/): un file
per schermata, più `Telaio.kt` per i pezzi che stanno su più schermate — la
barra in fondo, la testa, la pillola, il posto di una foto — che così sono
scritti una volta sola.

Nel disegno non si decide niente: quante righe ha l'intestazione, cosa c'è
scritto, che numeri, quanto si aspetta dopo una password sbagliata. Lo dicono i
file di `telefono/`, e il disegno legge le loro risposte. Lo controlla
[`prove/test_modulo_app.py`](../prove/test_modulo_app.py), che si rompe il
giorno in cui **una qualunque frase** ricompare nei pixel — il segno è che una
frase ha uno spazio dentro, mentre un «<» o un «×» sono segni e restano lì.

Una cosa va detta: **non sono mai state compilate**. Il modulo `app/` chiede
l'SDK di Android, che sulla macchina dove sono state scritte non c'è. La prima
compilazione la farà Android Studio, ed è normale che lì escano fuori due o tre
correzioni.

Le miniature non ci sono: al loro posto c'è un rettangolo grigio, e non è
fretta. Le foto arrivano dal pacchetto, e il pacchetto si apre quando sarà
chiuso il buco qui sotto. Fino a quel giorno la schermata mostra la sua forma
senza fingere di avere foto — e i giorni che si vedono sono quelli
dell'archivio finto (regola 114).

Fra i due telefoni cambiano tre cose e sono scritte in tre posti soli
(regole 394, 399, 400, 392): l'intestazione del giorno, dove sta il cuore sulla
foto aperta, e la riga della firma — che sul Redmi non c'è perché lì non scade
niente. Tutto il resto è `Sistema.IPHONE` o `Sistema.ANDROID` che non cambia
nulla, ed è voluto.

*I tre buchi della regola 402 sono chiusi.* L'Officina scrive quante foto ha
portato l'ultimo travaso; i due lettori hanno imparato insieme `dettagli()` —
le etichette di uno scatto, ognuna con la sua origine — e la ricerca fra date e
note. Sono stati fatti **nei due lettori insieme**, Python e Kotlin, e la prova
incrociata li confronta riga per riga (regola 383): se rispondessero diverso,
l'app direbbe una cosa sull'iPhone e un'altra sul Redmi.

## I due calcoli scritti a mano

`scrypt` e `BLAKE2b` non ci sono né in Java né in Android, e le librerie che li
hanno pesano megabyte di codice che nessuno di noi ha letto, dentro un'app che
deve funzionare senza rete per vent'anni. Sono riscritti qui (regola 388) perché
reggono due prove insieme: stanno in un documento pubblico coi risultati attesi
(RFC 7914, RFC 7693), e **un errore non può passare inosservato** — una chiave
sbagliata di un bit non apre nessun pacchetto, un'impronta sbagliata dichiara
rovinate tutte le foto.

AES-256-GCM e SHA-256 invece si prendono dal sistema: sono i pezzi in cui una
versione scritta in casa sarebbe pericolosa davvero.

## Il buco dichiarato

Il PC apre il database del pacchetto in memoria. **SQLite di Android non sa
farlo**: vuole un file. Sono due strade, e sceglierne una oggi — senza un
telefono in mano — vorrebbe dire decidere al buio la cosa più delicata che c'è.

Quindi il posto in cui il database si apre è uno solo (`ApreIlBanco`, in
[`lettore/src/main/kotlin/visore/lettore/Banco.kt`](lettore/src/main/kotlin/visore/lettore/Banco.kt)),
e dietro c'è la strada del computer. Il resto del lettore chiede righe e riceve
righe. Il buco resta scritto lì dov'è, e non nascosto in mezzo al codice
(regola 387).

## Le prove

    gradle -p visore test

Girano da sole, in pochi secondi, e non chiedono né Python né un archivio:

* **i due calcoli** contro i numeri dei documenti pubblici;
* **un pacchetto vero**, piccolo e finto, che sta nel repository come file di
  testo (regola 389) — si apre, si verifica, si rovina un file apposta e la
  verifica lo trova, si sbaglia la password e non succede niente.

La prova che conta di più è che quello che ci legge il Kotlin è **identico**, campo
per campo, a quello che ci legge il telefono finto in Python. Il pacchetto di
prova si rifà con:

    python strumenti/pacchetto_di_prova.py --rifai

e va rifatto quando cambia il formato — cioè quando cambiano
`officina/telefono/formato.py` o `officina/telefono/cifratura.py`.

Dall'altra parte, `prove/test_visore_kotlin.py` costruisce un pacchetto **nuovo**
(con dentro una foto da più di un blocco, che il pacchetto piccolo non ha) e lo
fa aprire a questo lettore: è lì che si scopre il giorno in cui il costruttore
cambia e il lettore no. E chiude il giro nei due versi: fa mettere un cuore al
Kotlin, lo rilegge col programma dell'Officina, rifà il travaso e controlla che
il Kotlin lo ritrovi nella copia di scorta. Dove non c'è Gradle quelle prove si
saltano e lo dicono.

## Guardarci dentro a mano

    gradle -p visore :computer:installDist
    echo la-tua-password | visore/computer/build/install/computer/bin/computer D:\Visore-iPhone --verifica

La password si legge dall'ingresso standard e mai dalla riga di comando: una
riga di comando la vedono tutti i programmi del computer e finisce nella
cronologia del terminale (regola 115).

## Cosa manca

Le due app (regole 14, 356). Le otto decisioni sulle bozze, che erano la
condizione per cominciarle, sono prese tutte (regole 392-401). E vale la
regola 342 fino in fondo: **finché un telefono vero non ha aperto un
pacchetto vero, questa parte non è finita.**

Cosa serve sul PC e sul telefono per cominciare — cosa installare, cosa
accendere, e in che ordine — sta in
[`documentazione/come-si-costruisce-l-app.md`](../documentazione/come-si-costruisce-l-app.md).
