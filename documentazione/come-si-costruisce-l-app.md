# Come si costruisce l'app del telefono

Questa non è una guida per chi userà il Visore: è **l'elenco della spesa** per
chi lo costruisce, cioè per il PC Windows su cui gira l'Officina. Si fa una
volta sola, e serve prima che esista la prima schermata.

Si parla di **Android**, e viene prima per il motivo scritto nella regola 356:
non chiede un Mac, non chiede un account a pagamento e **non scade**. Per iOS
c'è l'ultima sezione, ed è un'altra storia.

## Cosa si installa sul PC

**Una cosa sola: Android Studio.** Si scarica da
[developer.android.com/studio](https://developer.android.com/studio), è
gratuito, e si porta dietro tutto il resto — Java, Gradle, il compilatore, gli
strumenti per parlare col telefono. Non serve installare Java a parte, né
Gradle a parte: quello che c'è dentro basta.

Durante l'installazione conviene lasciare spuntato l'**Android SDK** che
propone da solo. La prima apertura scarica qualche GB e ci mette un po': è
normale, e succede una volta.

**Cosa non serve, ed è il punto:**

| Non serve | Perché |
|---|---|
| Un account Google | Si può programmare e installare senza accedere a niente |
| Un account sviluppatore a pagamento | È Android: non esiste (regola 356) |
| Il Play Store | L'app si installa col cavo, non da un negozio |
| Una connessione, dopo | Serve solo per scaricare Android Studio la prima volta |
| Un rinnovo, mai | Su Android l'app installata resta installata (regola 357) |

Le prove del lettore in Kotlin girano già oggi, e non chiedono Android Studio:
per quelle basta Gradle (`gradle -p visore test`). Android Studio serve nel
momento in cui si comincia il modulo `telefono/`.

## Cosa si fa sul Redmi

Il telefono va messo in condizione di ricevere un'app dal PC. Sono tre
passaggi, tutti dentro le impostazioni, e nessuno di questi tocca le foto.

**1. Accendere le opzioni sviluppatore.**
*Impostazioni → Informazioni sul telefono → Versione MIUI* (o *Versione
HyperOS*, a seconda di quanto è nuovo), e **si tocca sette volte di seguito**.
Compare una scritta che dice che adesso si è sviluppatori. Non è un modo di
dire ed è la procedura ufficiale: Android le tiene nascoste così apposta.

**2. Accendere il debug USB.**
Le opzioni sviluppatore adesso ci sono, e stanno in *Impostazioni →
Impostazioni aggiuntive → Opzioni sviluppatore*. Dentro si accende **Debug
USB**. Sui telefoni Xiaomi c'è anche **Installazione via USB**, ed è quella che
serve davvero per far arrivare l'app dal PC: va accesa anche lei. Xiaomi a
volte chiede di essere connessi a internet e di avere un account Xiaomi per
attivarla — è una loro richiesta, una volta sola, e non riguarda né le foto né
il pacchetto.

**3. Il cavo.**
Serve un cavo USB **dati**, non uno di quelli da sola ricarica: se il telefono
si carica ma il PC non lo vede, quasi sempre è il cavo. Alla prima connessione
il telefono chiede *«Consentire il debug USB da questo computer?»*: si dice sì,
e conviene spuntare «consenti sempre».

Da quel momento, nella finestra di Android Studio, il Redmi compare nell'elenco
dei dispositivi in alto, e l'app ci arriva con un tasto.

## Il telefono finto, quando il Redmi non c'è

Android Studio sa fare un telefono finto in una finestra, e con quello si prova
tutto tranne l'ultima cosa. In alto a destra **Device Manager** → `+` →
*Create Virtual Device*; un **Pixel 8**, un'immagine di sistema **API 35**,
*Finish*. La prima volta si scarica qualche giga, poi parte in venti secondi.

Serve per disegnare: la griglia, i gesti, lo scorrimento, come sta il testo.
**Non** serve per la regola 342 — è un Pixel senza HyperOS sopra, e soprattutto
non ha dentro il pacchetto vero da decine di gigabyte. Finché un telefono vero
non ha aperto un pacchetto vero, quella parte non è finita.

## Come si controlla che sia tutto a posto

Il PC vede il telefono? Dentro Android Studio c'è già lo strumento, e da
`cmd.exe` è una riga:

```
%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe devices
```

Se risponde con una riga sotto `List of devices attached` che finisce per
`device`, è fatta. Se finisce per `unauthorized`, manca il sì sul telefono. Se
non c'è nessuna riga, è il cavo o il debug USB.

Questo comando **non guarda dentro il telefono**: chiede soltanto «ci sei?».

## Quello che viene dopo, in ordine

Con Android Studio installato e il Redmi collegato, il lavoro è questo, e in
quest'ordine (regola 386):

1. ~~**Nasce `telefono/`**~~, fatto: il terzo modulo di `visore/`, che dipende
   da `lettore` e **non** da `computer`. È così che si dimostra, guardando le
   dipendenze e non le intenzioni, che nel lettore non è entrato niente di
   buono solo per un PC. E accanto è nato `app/`, che è l'unico che parla di
   Android e l'unico che chiede l'SDK: entra nel progetto solo dove l'SDK c'è,
   così `gradlew test` continua a girare su qualsiasi macchina.
2. **Si chiude il buco dichiarato** (regola 387): il PC apre il database in
   memoria, SQLite di Android vuole un file. Il posto dov'è aperto è uno solo,
   `ApreIlBanco` in `visore/lettore/src/main/kotlin/visore/lettore/Banco.kt`, e
   la decisione si prende **col telefono in mano** — perché lì passa la
   password, ed è la cosa più delicata che c'è.
3. **Le otto schermate**, una per volta, dalle bozze scelte
   ([`sviluppo/bozze/visore/`](../sviluppo/bozze/visore/), regole 392-401), con le misure e le
   curve di casa Android (regola 400).
4. **Il pacchetto vero sul telefono vero**, col cavo. Non un pacchetto finto:
   quello vero, decine di GB.
5. E vale la regola 342 fino in fondo: **finché un telefono vero non ha aperto
   un pacchetto vero, questa parte non è finita.**

## E per iPhone

Stessa app, tre costi in più — e sono il motivo per cui Android viene prima
(regole 14, 356):

- **Un Mac, o una VM macOS.** Xcode compila solo su macOS, e non c'è
  scorciatoia: nessun modo di compilare un'app iOS da Windows. *Installarla* sul
  telefono, quello sì, si fa anche da Windows.
- **Il lettore riscritto in Swift.** È lavoro, non rischio: il formato è deciso
  e ha già due letture che si controllano a vicenda (regola 389), quindi la
  terza ha contro cosa essere verificata riga per riga.
- **I sette giorni.** Senza account sviluppatore (99 €/anno, escluso dalla
  regola 356) l'app smette di aprirsi dopo una settimana e va rifirmata dal PC.
  Non si nasconde: **l'app scrive quanti giorni mancano**, e dice anche che
  *rinnovare* non tocca niente mentre *cancellare e reinstallare* porta via il
  pacchetto — cioè decine di GB da ricopiare (regola 357).
