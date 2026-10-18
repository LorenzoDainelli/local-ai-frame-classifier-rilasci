from __future__ import annotations


TESTO = """\
COME SONO FATTI I FILE DELL'ARCHIVIO SICURO

Questa chiavetta contiene una copia cifrata delle tue foto e dei tuoi video.
Senza la password non si legge niente: né le foto, né i nomi dei file, né i
nomi delle cartelle.


PRIMA PARTE: COME RIAVERE LE FOTO

1. Attacca la chiavetta a un computer con Windows.
2. Apri la chiavetta e fai doppio clic su «Recupera foto.exe». Non c'è niente
   da installare e non serve internet.
3. Scrivi la password dell'Archivio sicuro.
4. Scegli dove mettere le foto. Se non scegli, vanno nella cartella
   «Foto recuperate» dentro la tua cartella personale. Se lo spazio non
   basta, il programma te lo dice prima di cominciare.
5. Aspetta la fine. Ogni cartella che avevi messo nell'archivio torna fuori
   con il suo nome, le sue sottocartelle e le sue date.

Da sapere:
- Recupera foto legge soltanto: sulla chiavetta non cambia niente.
- Se qualcosa non va, accanto alle foto recuperate trovi il file
  «Cosa è successo nel recupero.txt», che racconta cosa è successo.
- Se la chiavetta fa i capricci, copia sul computer «Recupera foto.exe» e la
  cartella «Archivio sicuro», uno accanto all'altra, e fai doppio clic lì.
- Ogni file ha dei pezzi di riserva: i danni piccoli si sistemano da soli
  mentre leggi.
- Non spostare e non rinominare i file dentro «Archivio sicuro».


SECONDA PARTE: PER CHI SA PROGRAMMARE

Questa parte serve se un giorno Recupera foto non dovesse più funzionare: con
quello che c'è scritto qui chi sa programmare può leggere l'archivio da zero.

Servono AES-GCM con chiavi da 256 bit, scrypt, HKDF con SHA-256, BLAKE2b,
SHA-256, CRC-32 (quello di zlib) e SQLite. I numeri sono interi senza segno,
scritti con il byte più importante per primo (big-endian). Le cifre
esadecimali sono in lettere minuscole. I testi sono in UTF-8; i nomi di file
molto strani possono contenere i byte "surrogatepass" di Python (vedi il
punto 5), anche dentro i JSON.

In tutto il testo HKDF(segreto, uso, L) vuol dire: HKDF con SHA-256, senza
sale (cioè con 32 byte a zero come sale), info = "officina-sicuro" + un byte
0 + uso, lunghezza L byte. Se L non è scritta, è 32.


1. LE CARTELLE

  Archivio sicuro/
    chiave.json                     la chiave, chiusa con la password
    chiave.riserva.json             la sua copia
    chiavetta.json                  serve solo al programma
    contenuti/ab/<numero>.ofs       un file per ogni foto, video o nota
    elenco/fotografia-NNNNNNNN.ofs  l'elenco di nomi, cartelle e date

<numero> è fatto di 32 cifre esadecimali e "ab" sono le sue prime due.
NNNNNNNN è la generazione, scritta con otto cifre. I file che finiscono in
".nuovo" sono copie lasciate a metà: si ignorano.

Sul computer, accanto alle fotografie dell'elenco, ci sono anche i diari
(diario-NNNNNNNN.ofd e diario-NNNNNNNN.riserva.ofd). Sulla chiavetta i diari
non ci sono, perché lì la fotografia è già aggiornata.

Per riavere le foto bastano chiave.json (o la sua riserva), contenuti/ ed
elenco/.


2. LA CHIAVE

chiave.json è un testo JSON fatto così:

  {"tipo": "officina-archivio-sicuro-chiave", "versione": 1,
   "nome": <32 cifre esadecimali>,
   "porte": [{"numero": <16 cifre esadecimali>, "kdf": "scrypt",
              "n": 131072, "r": 8, "p": 1,
              "sale": <32 cifre esadecimali>,
              "nonce": <24 cifre esadecimali>,
              "chiusa": <96 cifre esadecimali>}]}

Per aprire una porta:

  K = scrypt(password in UTF-8, sale, N = n, r = r, p = p, 32 byte)
  A = "officina-archivio-sicuro-chiave" + byte 0 + "1" + byte 0 + numero
      + byte 0 + n + byte 0 + r + byte 0 + p
  S = AES-GCM decifra "chiusa" con chiave K, il nonce e dati associati A

In A tutto è testo ASCII: numero è scritto come nel file, n, r e p con le
cifre decimali. Con n = 131072 scrypt usa circa 128 MiB di memoria (con
262144 il doppio): molte librerie vanno avvisate, per esempio con maxmem in
Python.

Se AES-GCM rifiuta, la password non è quella di questa porta: se le porte
sono più di una, provale tutte. S è il segreto dell'archivio, 32 byte.
Controllo: HKDF(S, "nome", 16) in esadecimale deve essere uguale a "nome".


3. LE CHIAVI CHE NASCONO DAL SEGRETO

  K_contenuti = HKDF(S, "contenuti")
  K_file      = HKDF(K_contenuti, "contenuto" + byte 0 + i 16 byte del
                numero del file)
  K_diario    = HKDF(S, "diario")

Ogni file .ofs, sia in contenuti/ sia in elenco/, ha la sua K_file.


4. I FILE .ofs

L'intestazione occupa i primi 64 byte:

  byte  0-7   "OFSICURO"
  byte  8-9   versione, oggi 1
  byte 10-11  zero
  byte 12-27  numero del file (16 byte)
  byte 28-31  blocco: quanti byte della foto stanno in un blocco (65520)
  byte 32-35  pezzo: quanti byte ha un pezzo (4096)
  byte 36-37  gruppo (20)
  byte 38-39  passo
  byte 40-47  dimensione: quanti byte ha la foto originale
  byte 48-51  meta: quanti byte ha la parte delle informazioni
  byte 52-59  zero
  byte 60-63  CRC-32 dei byte 0-59

I numeri fra parentesi sono quelli di oggi, ma vanno sempre letti
dall'intestazione. Gli ultimi 64 byte del file sono una seconda copia
dell'intestazione.

Tutto è cifrato con AES-GCM e la chiave K_file. I dati associati sono sempre
i byte 0-59 dell'intestazione. Il nonce è di 12 byte: un tipo in 4 byte e un
indice in 8 byte. Il tipo è 0 per i blocchi della foto e 1 per le
informazioni. Ogni parte cifrata è 16 byte più lunga del suo testo.

I blocchi. La foto è divisa in max(1, dimensione / blocco arrotondato in su)
blocchi. Il blocco i ha "blocco" byte, tranne l'ultimo che ha quelli che
restano (anche zero). Il blocco i è cifrato con il nonce (0, i). I blocchi
cifrati, uno dopo l'altro, formano il nastro, lungo dimensione + 16 × blocchi
byte. Il nastro è tagliato in pezzi di "pezzo" byte; l'ultimo pezzo è
completato con zeri.

Le informazioni. Sia inizio = 64 + meta. Dal byte 64 fino a inizio c'è M, le
informazioni cifrate con il nonce (1, 0). Una copia uguale di M sta subito
prima dell'ultima intestazione, cioè negli ultimi meta + 64 byte del file,
tolti gli ultimi 64. Se una copia è rovinata, si usa l'altra. Decifrata, M
contiene: 4 byte con una lunghezza L, poi L byte di JSON, poi zeri.
Il JSON è

  {"dati": {...}, "impronte": {"blake2b": ..., "sha256": ...}}

e le impronte sono quelle della foto originale: BLAKE2b da 32 byte e
SHA-256, in esadecimale. Se tutte e due le copie di M sono rovinate, la foto
si legge lo stesso: mancano solo i dati e le impronte.

Le fasce. Sia fascia = gruppo × passo. I pezzi del nastro stanno in fasce di
"fascia" pezzi (l'ultima può averne meno), e ogni fascia è seguita dai suoi
pezzi di riserva: tanti quanti passo, ma non più dei pezzi della fascia. La
fascia f comincia al byte inizio + f × (fascia + passo) × pezzo, e il suo
pezzo k sta k × pezzo byte più avanti. Il file pesa in tutto
2 × inizio + (pezzi del nastro + pezzi di riserva) × pezzo.

Le riserve. Dentro una fascia, il pezzo k sta nella riga k / passo (divisione
intera) e nella colonna k mod passo. La riserva c è lo XOR di tutti i pezzi
della colonna c. Un pezzo rovinato si rifà così: la riserva della sua colonna
XOR tutti gli altri pezzi della stessa colonna. Si capisce che un pezzo è
rovinato perché AES-GCM rifiuta il suo blocco: allora si rifanno, uno alla
volta, i pezzi di quel blocco, finché il blocco si apre. Il passo lo sceglie
chi scrive: chi legge lo trova nell'intestazione.

Alla fine si controllano le impronte BLAKE2b e SHA-256 di tutta la foto.

I "dati" delle informazioni dicono cos'è il file:

  - una foto o un video copiato:
      {"fatti": [...], "scritto": momento}
  - un gemello, fatto dal controllo mensile, uguale ad altri file:
      {"gemello_di": [numeri], "fatti": [...], "scritto": momento}
  - una foto salvata solo in parte:
      {"salvato_da": numero, "buchi": [[da, a], ...], "fatti": [...],
       "scritto": momento}
    i blocchi da "da" ad "a" (compresi) mancavano e sono pieni di zeri
  - una nota: {"tipo": "nota", "scritto": momento}, a volte anche con
    "riassunto": true; i byte della "foto" sono una lista JSON di fatti
  - una fotografia dell'elenco: {"tipo": "fotografia", "generazione": N,
    "schema": 1, "scritto": momento}

I momenti sono secondi dal 1° gennaio 1970 (UTC). Ogni file si porta dietro
i fatti che lo riguardano (dove stava, come si chiamava, le sue date): così
l'elenco si può rifare anche dai soli file. I fatti sono spiegati al punto 6.


5. L'ELENCO

elenco/fotografia-NNNNNNNN.ofs è un file .ofs che contiene un database SQLite
intero (PRAGMA user_version = 1). Si usa quello con la generazione più alta
che si legge bene. Le tabelle sono queste.

  contenuti(numero, dimensione, blake2b, sha256, peso, testa, stato, perche,
            scritto, controllato)
      Un file .ofs per riga. testa è la sua intestazione di 64 byte. stato
      è uno di: buono, riparato, incompleto, rovinato, senza_informazioni.

  radici(id, percorso, aggiunta, tolta, cambiata)
      Le cartelle messe nell'archivio, con il loro percorso sul computer.

  posti(chiave, radice, percorso, tipo, contenuto, metadati, segni, visto,
        sparito)
      Ogni file, cartella o collegamento visto dentro una radice. percorso
      è relativo alla radice, con "/" fra le parti. tipo è file, cartella o
      collegamento. contenuto è il numero del file .ofs (solo per i file).
      visto è quando è stato visto, sparito quando non c'era più (vuoto se
      c'è ancora). segni sono parole su cose capitate durante la copia, per
      esempio "incompleto" o "in_uso".

  flussi(posto, nome, contenuto)
      I flussi nascosti di Windows di un file: il loro nome e il numero del
      file .ofs che li contiene.

  note(numero, scritto) e giri(radice, inizio, fine, problemi, contati)
      Servono solo al programma.

I testi che non si possono scrivere in UTF-8 (nomi di file molto strani)
sono salvati come BLOB, con i byte UTF-8 "surrogatepass" di Python.

metadati è un oggetto JSON:
  modifica, accesso, creazione   date in nanosecondi dal 1970
  attributi                      gli attributi del file di Windows
  permessi                       {"sddl": ...} su Windows, altrove
                                 {"modo": ..., "utente": ..., "gruppo": ...}
e per i collegamenti anche:
  collegamento                   "simbolico", "giunzione" o "altro"
  verso_cartella                 vero se punta a una cartella
  bersaglio                      dove punta
  rimando                        il numero del rimando di Windows

Come rifare le cartelle. Per ogni radice si prendono i suoi posti con
sparito vuoto. Se per lo stesso percorso ce n'è più di uno, vale quello con
visto più alto (a pari visto, quello aggiunto per ultimo). Per riavere le
cartelle come erano in un momento G, si prendono invece i posti con visto
non dopo G e sparito vuoto o dopo G. La cartella che esce si chiama come
l'ultima parte del percorso della radice; per un disco intero, «Disco C».
Su Windows i caratteri < > : " / \\ | ? * e quelli di controllo nei nomi
diventano "_"; un nome che finisce con un punto o uno spazio li perde e
prende un "_" in fondo; i nomi riservati (CON, PRN, AUX, NUL, COM1, LPT1 e
simili, anche con un'estensione) prendono un "_" davanti. Se un nome è già
preso, si aggiunge " (2)", " (3)" e così via: per i file prima
dell'estensione, per le cartelle in fondo.

I diari. Sul computer, dopo la fotografia, si leggono in ordine i diari con
generazione uguale o più alta. Un diario comincia con 64 byte:

  byte  0-7   "OFDIARIO"
  byte  8-9   versione, oggi 1
  byte 10-11  zero
  byte 12-27  numero del diario (16 byte)
  byte 28-35  generazione
  byte 36-51  prova: AES-GCM con K_diario, nonce = i primi 12 byte del
              numero, testo vuoto, dati associati "OFDIARIO" + numero +
              generazione (8 byte)
  byte 52-59  zero
  byte 60-63  CRC-32 dei byte 0-59

Poi vengono le righe, una dopo l'altra. Ogni riga ha 4 byte con la lunghezza
L, 4 byte con il CRC-32 di quei primi 4 byte più il corpo, e L byte di corpo.
Il corpo è un nonce di 12 byte seguito dal cifrato, che si apre con AES-GCM,
K_diario e dati associati "OFDIARIO" + numero + generazione (8 byte) +
posizione della riga (8 byte, la prima riga è la 0). Dentro c'è un JSON
{"fatti": [...]}. La copia .riserva.ofd ha le stesse righe: se una riga è
rovinata in una copia, si prende dall'altra.

Se nessuna fotografia si legge, si parte da un database vuoto e si leggono
tutti i diari (sul computer) e tutti i file di contenuti/. Per ognuno di
questi file si aggiunge un fatto "contenuto" fatto con la sua intestazione e
le sue impronte, poi i fatti che si porta dietro: quelli in "dati", oppure,
per le note, la lista dentro i byte.


6. I FATTI

Un fatto è un oggetto JSON e la parola "fatto" dice di che tipo è:

  radice     {id, percorso, tolta, quando}
             aggiunge la radice o ne cambia percorso e tolta
  contenuto  {numero, dimensione, blake2b, sha256, peso, testa, stato,
              perche, quando}
             aggiunge una riga a contenuti, se non c'è già (testa è in
             esadecimale, scritto = quando)
  stato      {numero, stato, perche, quando}
             cambia stato e perche di un contenuto (controllato = quando)
  posto      {chiave, radice, percorso, tipo, contenuto, metadati, segni,
              quando}
             aggiunge un posto, se la chiave non c'è già (visto = quando)
  sparito    {chiave, quando}
             mette sparito = quando, se era vuoto
  flusso     {posto, nome, contenuto}
             aggiunge un flusso
  nota       {numero, quando}
             aggiunge una nota

I fatti "ricordo" e "giro" servono solo al programma.
"""


def per_la_chiavetta() -> str:
    return "\ufeff" + TESTO.replace("\n", "\r\n")
