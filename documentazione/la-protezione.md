# La protezione

Il programma tiene in casa le foto di una vita e tutto quello che sai di
loro: chi c'è, dove, quando. Questa pagina dice da cosa si difende, in
parole semplici, e anche dove la difesa finisce.

## Gli aggiornamenti

- Un aggiornamento si installa **solo se è firmato** con la chiave del
  programma. Se qualcuno mettesse al suo posto un file diverso, anche con lo
  stesso nome e lo stesso numero di versione, il programma lo rifiuta.
- La costruzione su GitHub va in tre passi separati, e la firma parte solo
  dopo che **tu** hai premuto «Approva». Le azioni di GitHub usate sono fissate
  a una versione precisa, e le librerie si installano solo con la loro impronta.

## Il programma sul computer

- Si apre **solo dalla sua finestra**. A ogni avvio la finestra riceve una
  chiave che vive solo in memoria: un browser aperto a mano su
  `http://localhost:8080`, un altro programma o un altro utente dello stesso
  computer non entrano.
- Le scelte delicate — le impostazioni, il forziere, i dispositivi, il
  portatile, il telefono, l'altro computer, le cartelle da importare — si fanno
  solo dal computer stesso, mai da un altro dispositivo.
- Le pagine viaggiano con le intestazioni di sicurezza del browser: niente
  pagine altrui che incorniciano le nostre, niente codice da fuori, niente
  rimandi verso indirizzi esterni. I nomi scritti da te sono sempre mostrati
  come testo, mai come codice.
- Le password sbagliate rallentano chi prova a indovinare.

## La rete di casa

- **Di base è spenta**: il programma risponde solo al computer su cui gira.
- Accesa, parla **solo cifrato**, sulla porta `8443`, con un certificato fatto
  dal fisso. La prima volta il browser avvisa, e si confronta l'impronta
  SHA-256 con quella scritta nelle impostazioni.
- Ogni dispositivo entra solo dopo che l'hai **approvato con un codice di sei
  cifre**. Riceve una chiave sua, che il fisso conserva solo come impronta:
  chi prende in prestito l'indirizzo di un dispositivo approvato, senza la sua
  chiave, resta fuori.

## Il portatile come schermo del fisso

- Il codice per abbinare un portatile **nasce solo quando lo mostri** sul fisso.
- Cinque codici sbagliati cambiano il codice; **venti sbagli in tutto** chiudono
  la porta finché sul fisso non premi «Nuovo codice».
- Chi non entra legge sempre la stessa frase, sia che abbia sbagliato
  portatile sia che abbia sbagliato password: non impara niente.
- La regola di Windows che lascia passare il portatile vale **solo sulle reti
  private o di dominio**, mai su una rete pubblica come quella di un bar.

## Le foto che entrano

- Si aprono solo i formati d'immagine veri: un file che dice di essere una foto
  ma dentro è altro viene lasciato stare.
- Un XMP o un MOV rovinati non bloccano il programma; le coordinate GPS fuori
  dal mondo si scartano.
- «Raccogli» non sovrascrive mai un file che c'è già, e le cartelle non seguono
  scorciatoie che portano altrove.

## I modelli e le librerie

- Ogni modello si scarica da una revisione fissata e si controlla con la sua
  impronta: se cambia anche un byte, non si usa.
- Le librerie si installano senza leggere configurazioni esterne di `pip`.
- I pesi dei modelli si aprono solo con un motore delle reti neurali dalla
  versione 2.6 in su: prima, un file costruito apposta poteva far eseguire
  codice. Se il tuo è più vecchio, all'avvio il programma scarica da solo
  quello nuovo; se non ci riesce puoi entrare lo stesso, e riprova al
  prossimo avvio. `nvidia-smi` si cerca solo nel suo posto di Windows.

## Il telefono e l'altro computer

- Sulla chiavetta e sul telefono **non passa niente in chiaro**: i file hanno
  nomi a caso, che non dicono né la data né il nome della foto. I nomi veri
  stanno solo nel database cifrato.
- Ogni file è **legato al suo posto**: uno spostato o scambiato con un altro non
  si apre.
- La password diventa una chiave con conti più cari di prima, e il programma
  e l'app accettano solo i conti che conoscono.
- Nel pacchetto per l'altro computer, i dati della carta d'identità che
  decidono qualcosa sono ripetuti dentro la parte cifrata: se fuori sono stati
  ritoccati, il pacchetto non si apre.
- Un pacchetto fatto da una versione precedente si rifà: quello del telefono si
  riscrive tutto al primo travaso, quello per l'altro computer va rifatto
  sull'altro computer.
- L'app del telefono è esclusa dai backup di iCloud e di Google e dal passaggio
  dei dati a un telefono nuovo, e non si lascia fotografare.

## Le password nuove

Una password nuova deve avere **almeno dodici caratteri**. Lunga meglio che
complicata: tre parole che ricordi valgono più di otto caratteri strani. Le
password scelte prima continuano ad aprire quello che aprivano.

## Dove la difesa finisce

- **La grandezza dei file si vede.** Il contenuto è cifrato, ma chi trova la
  chiavetta può contare i file e vedere quanto pesa ciascuno.
- **Un pacchetto vecchio intero si apre ancora.** Chi avesse una copia completa
  di un pacchetto di prima, fatto con la stessa password, potrebbe rimetterla
  al posto di quella nuova: si aprirebbe, e mostrerebbe le foto di allora. Non
  si possono invece mescolare pezzi vecchi e pezzi nuovi.
- **Il programma di installazione non ha la firma di Windows.** La prima volta
  Windows può avvisare che l'editore è sconosciuto. Gli aggiornamenti, invece,
  sono controllati dalla firma del programma.
- **Chi ha già il controllo del computer** (un virus, o qualcuno seduto davanti
  con l'archivio aperto) vede quello che vedi tu: nessun programma può
  difendersi da questo. Il forziere protegge l'archivio quando è chiuso.
