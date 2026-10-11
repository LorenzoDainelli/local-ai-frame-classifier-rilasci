# Da riga di comando

Per chi sviluppa o preferisce il terminale. Chi usa il programma installato
non ne ha bisogno: tutto quello che c'è qui si fa anche dalle schermate.

## Dal codice sorgente

```bash
pip install -r requirements.txt
python -m officina scorciatoia
```

Due righe, e sono le ultime. `scorciatoia` mette l'icona sul desktop e nel menu
Start: da lì in poi si apre con un doppio clic, in una finestra sua senza barra
degli indirizzi.

La prima volta — e solo quella — dentro c'è una procedura guidata in quattro
passi: cosa succede e cosa non succede · dove sono le foto, con il conto prima
di decidere · l'elaborazione, che va avanti mentre guardi · si comincia, sul
primo scatto da etichettare. **Non c'è niente da copiare in un terminale.**

L'unica eccezione è il forziere, ed è scritta nella prima pagina: si accende da
riga di comando, guardandolo, perché è la cosa più irreversibile del programma
e non deve poter capitare mentre si scorre una pagina (regola 340).

Anche i modelli e i volti si fanno dalle pagine: i primi dal tasto in
**Salute**, con scritto sulla riga da dove arrivano, quanto pesano e con che
licenza; i secondi dal tasto in **Persone**.

## Se preferisci il terminale

C'è tutto, e fa le stesse cose:

```bash
# un archivio finto: nessuna foto vera, tutti i casi difficili
python -m officina finto ~/archivio-finto --quanti 120
python -m officina importa --finto ~/archivio-finto
python -m officina avvia --finto

# il passo pesante, una volta sola
python -m officina impronte --finto

# i volti, se hai scaricato i loro modelli
python -m officina volti --finto
```

Per le proprie foto si tolgono i `--finto`. I due archivi hanno database
separati e non si toccano mai (regola 341).

## La misura (tappa 2)

```bash
# 4. le impronte numeriche: il passo pesante, una volta sola
python -m officina impronte --finto

# 5. il confronto delle scelte, su etichette che il generatore conosce già
python -m officina misura --finto --scene ~/archivio-finto
```

Ne esce un rapporto fatto solo di numeri. Sulle proprie foto le etichette le dà
l'utente, dalla pagina **Misura** — un centinaio di scatti, un pomeriggio.

I modelli si scaricano a parte, ed è l'unico momento in cui il programma tocca
la rete (regola 74). Le librerie da riga di comando, i pesi dal tasto nella
pagina **Salute** — che dice, sulla riga, da dove arrivano, quanto pesano e con
che licenza:

```bash
pip install -r requirements-modelli.txt
```

Da terminale, se si preferisce:

```bash
python -m officina modelli --scarica tutti
python -m officina modelli --scarica volti
```

Senza, tutto funziona lo stesso con il descrittore disegnato a mano — che non è
intelligenza artificiale, è un conto sui colori, e serve anche come metro di
paragone.

## Il pacchetto per il telefono

```bash
# il telefono si dichiara una volta, col suo nome
python -m officina pacchetto --nuovo iPhone --sistema ios

# cosa succederebbe, senza farlo (regola 274)
python -m officina pacchetto --telefono iPhone --solo-conta

# il travaso vero: scrive una cartella, non tocca il telefono
python -m officina pacchetto --telefono iPhone --dove D:\Visore-iPhone

# il telefono finto lo riapre e verifica ogni impronta (regola 383)
python -m officina leggi-pacchetto D:\Visore-iPhone --verifica
```

Il pacchetto lo copi tu, col cavo, nello spazio dell'app: il programma non tocca
il telefono e non sa niente di driver (regola 368). La password è quella del
forziere; se il forziere è spento, il pacchetto ne chiede una lo stesso — il
fisso sta in camera, il telefono esce di casa.

Le stesse cose si fanno da **Dispositivi**, sul telefono, che è dove conviene farle:
lì la selezione si compone vedendo il conto scendere mentre si toglie, e il
travaso va avanti da solo mentre si continua a lavorare (regole 369, 384).

## I due computer

```bash
# come si chiama questo computer (una volta sola)
python -m officina sincronizza --chiamami "il fisso"

# fanne uno da portare di là: dentro solo quello che l'altro non ha visto
python -m officina sincronizza --dove D:\Scambio

# cosa c'è in un pacchetto, senza password e senza aprirlo
python -m officina sincronizza --guarda D:\Scambio\da-lo-zenbook

# applicalo
python -m officina sincronizza --applica D:\Scambio\da-lo-zenbook
```

Il pacchetto lo copi tu, sulla chiavetta: fra i due PC non passa niente, mai
(regole 403, 1). Chi arriva secondo non cancella il lavoro di chi era già lì —
si tiene la decisione più recente, e a parità decide il codice della macchina,
che è una moneta che cade dalla stessa parte su tutti e due i computer.

Le stesse cose si fanno da **Dispositivi › Altro computer**, che è dove conviene
farle: lì l'elenco dei pacchetti arrivati si legge senza password (regola 106) e
un pacchetto di un altro archivio non ha nemmeno il tasto per applicarlo.

