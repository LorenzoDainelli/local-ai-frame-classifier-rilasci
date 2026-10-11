# Come si dismette

Regola 116. Questo capitolo esiste perché il modo classico di lasciarsi dietro
dei dati è dimenticare i posti che il programma ha creato da solo.

Serve quando si vende o si dà via un computer, quando si cambia telefono, o
quando si smette di usare il programma.

## In che ordine

**1. Il pacchetto sul telefono** (quando esisterà, regola 7). Si disinstalla
l'app: porta via con sé il pacchetto cifrato, i preferiti e il diario dell'uso,
che vivono tutti nello spazio privato dell'app (regole 367, 381). Non resta
niente altrove sul telefono, e non c'è niente da cercare su iCloud o su Google:
il pacchetto è escluso dai backup apposta. **È anche l'unico modo di cancellare
il diario dell'uso**, che dall'app non si svuota — vedi
[Il Visore](il-visore.md#il-diario-delluso).

**2. Le copie di sicurezza esterne.** I due supporti fisici della regola 10.
Sono cifrati, ma cifrato non vuol dire cancellato: la password è scritta su
carta da qualche parte.

**3. L'archivio.**

| Sistema | Cartella da cancellare |
|---|---|
| Windows | `%LOCALAPPDATA%\Officina` |
| macOS | `~/Library/Application Support/Officina` |
| Linux | `~/.local/share/officina` |

Dentro c'è tutto: database, miniature, copie, modelli, registro. Se
`OFFICINA_ARCHIVIO` era impostata, la cartella è quella.

**4. L'elenco delle parole vietate.** `parole-vietate.txt` nella stessa
cartella. Contiene i nomi veri dei nodi e delle persone: è, in proporzione, il
file più sensibile di tutto il progetto.

**5. Il codice.** La cartella del repository. Non contiene dati (regola 1), ma
tanto vale.

**6. Le foto originali.** Il programma non le ha mai toccate né copiate
(regola 2): stanno dove sono sempre state, e vanno trattate a parte.

## Quello che il programma non ha creato altrove

Per non cercare dove non c'è niente:

- **niente nel registro di sistema** di Windows;
- **niente in cartelle temporanee** — le conversioni per il browser vivono in
  memoria e muoiono con la richiesta (regola 327);
- **niente accanto alle foto** — nessun file di appoggio, nessuna miniatura,
  nessun database nascosto nelle cartelle degli originali;
- **niente su nessun server**, perché non ce n'è nessuno (regola 1).

## Se il computer si vende senza cancellare il disco

Cancellare i file non basta su un disco a stato solido. Le difese vere sono due
e vanno messe prima, non dopo:

- la **cifratura del disco** attiva fin dal primo giorno (regola 9);
- il **contenitore cifrato** dell'archivio (regola 331).

Con entrambe attive, quello che resta sul disco dopo una cancellazione normale è
rumore. Senza, non lo è.
