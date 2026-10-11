# La misura

*Tappa 2 del progetto — regole 105 e 336.*

> **105.** Le scelte architetturali si verificano sui dati reali, non si
> assumono. Prima di costruire tutto si misura su un campione: le due famiglie
> di descrittori, il ritaglio contro la foto intera, il classificatore leggero.
> Se una scelta non regge il confronto, si cambia e si scrive perché.

> **336.** È il momento in cui cambiare idea costa poco: un centinaio di scatti
> veri, un pomeriggio, non una notte. *Rimandare questa prova significa
> scoprire a metà progetto che servivano ritagli diversi — e a quel punto è una
> notte di ricalcolo più mezzo programma da rivedere.*

Questa tappa non aggiunge una funzione al programma. Aggiunge **un numero
accanto a ogni scelta**, prima che sopra quelle scelte venga costruito il
resto.

---

## Quanto ci mette

Misurato su un archivio finto di 120 scatti a misura vera (4032×3024), su un
processore senza scheda video:

| Passo | Tempo | Su 1300 scatti sarebbe |
|---|---|---|
| importazione | 102 s | ~18 minuti |
| impronte, descrittore disegnato | 51 s (476 ms per scatto) | ~10 minuti |
| il confronto | 3-7 s | uguale: dipende dagli esempi, non dall'archivio |

Le impronte occupano circa **11 kB per scatto** (tre inquadrature, conservate
intere — regola 172): 14 MB su 1300 scatti.

Con i due modelli grandi su una scheda video i tempi cambiano del tutto — è la
notte di cui parla la regola 16 — ma il resto resta identico, perché da lì in
poi si lavora sulle impronte e non sulle immagini.

## Cosa viene messo alla prova

| Domanda | Regole | Cosa si confronta |
|---|---|---|
| Servono due descrittori o ne basta uno? | 101, 174, 175 | DINOv3 contro SigLIP 2, e i due insieme |
| Il ritaglio serve davvero? | 37, 38 | foto intera, soggetto, dettaglio, e le tre insieme |
| Il classificatore leggero regge? | 103 | quattro livelli di prudenza |
| E la ricerca per somiglianza? | 16, 32 | quanti dei cinque più simili sono giusti |
| Un modello grande batte un conto sui colori? | — | il descrittore disegnato a mano, che costa zero |

L'ultima riga non è nelle regole ed è la più utile. Se un modello da trecento
milioni di parametri non batte cinquanta righe che contano i colori, la cosa da
sapere è quella — e la regola 343 dice cosa farne: *la regola vecchia resta
scritta e superata, e quella nuova dice cosa si è misurato e cosa è cambiato.*

---

## Il giro completo

### 1. Prima sul finto, sempre (regola 341)

```bash
python -m officina finto ~/archivio-finto --quanti 120
python -m officina importa --finto ~/archivio-finto
python -m officina impronte --finto
python -m officina misura --finto --scene ~/archivio-finto
```

`--scene` è una scorciatoia che esiste **solo per l'archivio finto**: le
immagini le ha disegnate il programma, quindi sa già in quale scena sta
ciascuna, e le etichette se le mette da solo. Serve a far girare tutto il giro
in due minuti prima di toccare una foto vera.

### 2. Poi sul vero

```bash
python -m officina impronte          # il passo pesante, una volta sola
python -m officina avvia
```

Poi la pagina **Misura**, che ha tre riquadri nell'ordine in cui servono.

**Le impronte.** Ogni scatto diventa una descrizione numerica (regola 16). È il
passo lento — con i modelli grandi e una scheda video, una notte per un
archivio intero; con il descrittore disegnato a mano, qualche minuto. Si può
interrompere e riprende da sola (regole 48, 277).

**Le decisioni.** Servono un centinaio di scatti divisi in due o tre mucchi.
Si preme *Apri il banco*: uno scatto per volta, e un tasto.

**Il confronto.** Qualche decina di secondi, e ne esce il rapporto.

---

## Il banco

Uno scatto grande al centro, i mucchi numerati a destra. Tutti i comandi sotto
la sola mano destra (regola 23):

| Tasto | Cosa fa |
|---|---|
| da **1** a **9** | mette lo scatto in quel mucchio |
| **0** | «nessuno di questi» — un «no» **detto**, che vale quanto un «sì» (regola 56) |
| **S** | salta: resta indeciso, che **non** è un «no» (regole 55, 75) |
| **← →** | avanti e indietro |
| **Esc** | torna alla pagina della misura |

Non è la schermata di etichettatura del progetto: quella arriva con la tappa 3
e ha l'albero, le proposte e il riaddestramento in sottofondo. Qui c'è il
minimo che serve per avere materiale su cui misurare, e niente di più.

### Il trucco che dimezza il lavoro

Se i mucchi si escludono a vicenda — una foto sta in uno solo — conviene
crearli **dentro un ramo «scegline uno»** (regola 129). Da quel momento ogni
scelta regala un «no» a tutti gli altri mucchi, senza che nessuno lo dica: un
tasto per scatto invece di tre.

I «no» regalati non vengono scritti da nessuna parte: si calcolano. Se un
domani il ramo smette di essere esclusivo spariscono da soli, invece di restare
in giro come etichette false messe dal programma.

### Gli scatti non arrivano in ordine di data

Arrivano **sparsi su tutto l'archivio**, per dimezzamenti successivi: il primo,
quello di metà, quelli a un quarto e a tre quarti, poi gli ottavi.

Non è un vezzo. Cento scatti consecutivi sono spesso due giornate, cioè
pochissimi gruppi indipendenti (regole 107, 77) — e una misura fatta su quelli
direbbe molto più su quelle due giornate che sull'archivio. La sequenza per
dimezzamenti ha una proprietà comoda: *qualunque* punto in cui ci si ferma
lascia un campione già spalmato, quindi non c'è nessun numero da decidere
prima.

### Quanti ne servono

Un nodo riceve un voto solo se ha **almeno cinque gruppi da una parte e cinque
dall'altra** (regola 244). Gruppi, non scatti: cinque foto della stessa raffica
valgono un esempio solo. Con due o tre mucchi, un centinaio di scatti bastano
abbondantemente.

Sotto i quaranta scatti decisi il programma **si rifiuta** di misurare. Non è
prudenza eccessiva: qualunque numero uscisse sarebbe un caso.

La pagina Misura mostra, mucchio per mucchio, quanti gruppi ci sono da una
parte e dall'altra e quanti ne mancano per un voto. Serve a non scoprire alla
fine di aver messo duecento scatti tutti nello stesso mucchio.

---

## Come si legge il rapporto

Il rapporto contiene **solo numeri**. Nessun nome di nodo, nessun nome di file,
nessun percorso — ed è costruito così apposta (regole 106, 112, 114): *si può
mostrare a chiunque*, ed è l'unico modo perché una misura del genere si possa
discutere senza che l'archivio esca di casa.

La promessa viene **verificata**, non creduta: prima di scrivere il file, il
programma lo rilegge e ci cerca dentro, uno per uno, i nomi veri dei nodi presi
dal database. Se ne trova anche uno, il file non si scrive (regola 110).

### Le due colonne

**azzecca** — quanto ci prende il classificatore su scatti che non ha mai
usato per imparare (regola 243). I «sì» e i «no» contano come due metà uguali:
con otto «sì» e duecento «no» un modello che risponde sempre «no» prenderebbe
il 96%, e contando le metà uguali prende il 50%, che è la verità. **A caso è
50%.**

**vicini** — quanti dei cinque scatti più simili a un «sì» sono anche loro
«sì». È la misura di come si etichetterà davvero (regola 32): si conferma un
esempio e il sistema propone i simili. **A caso è la quota di «sì» nel
campione**, che il rapporto scrive in cima.

I vicini della stessa raffica non contano, altrimenti qualunque descrittore
prenderebbe un voto alto per il motivo sbagliato (regole 107, 77).

### La riga da guardare per prima

> `scatti decisi 240 · gruppi indipendenti 198`

Se i due numeri sono molto diversi, molte di quelle foto sono la stessa scena e
tutti i numeri sotto valgono meno di quanto sembrino. Il rapporto lo dice da
solo quando succede.

---

## Se un numero smentisce una regola

Succede, ed è il motivo per cui questa tappa esiste. La regola 343 dice cosa
fare, e non è cancellare:

> La regola sbagliata non si cancella, si segna come **superata**, e quella
> nuova dice cosa si è misurato e cosa è cambiato. I numeri non si riusano.

Il costo del cambio resta basso per costruzione: le impronte si ricalcolano in
una notte (regola 43) e **le etichette non si toccano mai**, perché sono
attaccate agli scatti e non alle impronte.

Le misure fatte restano nel database, con la data e tutti i numeri, e il
rapporto si riscrive anche in forma di numeri puri accanto al file di testo.
Una misura che non si ritrova più non vale niente.

---

## Chi gli somiglia

Da ogni scatto si arriva alla pagina **Chi gli somiglia** (regola 16), che
mostra i più vicini secondo l'impronta scelta, con le pillole per cambiare
descrittore e inquadratura.

Vale la pena guardarla anche senza misurare niente: se i dieci più simili non
c'entrano niente, nessuna percentuale lo direbbe meglio.
