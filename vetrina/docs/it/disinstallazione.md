# Disinstallazione

[← Indietro](../../README.it.md) · [English](../en/uninstalling.md)

## Togliere il programma

1. Chiudi Local AI Frame Classifier.
2. Apri **Impostazioni di Windows → App → App installate**.
3. Cerca **Local AI Frame Classifier**, premi **⋯** e scegli **Disinstalla**.

Se ne vanno il programma, il suo Python e le sue librerie.

## Cosa resta, e perché

Resta **l'archivio**: etichette, categorie, miniature, facce, i motori e i
modelli scaricati. È voluto, perché così una reinstallazione ritrova tutto
com'era e non riscarica gigabyte.

Le **foto** non sono mai state toccate e restano dove sono sempre state.

## Togliere tutto

Per cancellare anche l'archivio, dopo la disinstallazione cancella questa
cartella:

```
%LOCALAPPDATA%\Local AI Frame Classifier
```

Puoi incollare la riga nella barra degli indirizzi di Esplora file.
**Non si torna indietro**: etichette e categorie si perdono per sempre. Le foto
non sono in quella cartella e non vengono toccate.
