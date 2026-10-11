from __future__ import annotations


def perche_nessun_volto(passata, finto: bool) -> list[str]:
    conto = passata.rilevatore.conteggio
    righe = ["", "  Nessun volto. Da dove viene questo zero:"]
    righe += [f"      {riga}" for riga in conto.righe()]

    if conto.proposte == 0:
        if finto:
            righe += [
                "  Ma è l'archivio finto: dentro ci sono immagini generate dal",
                "  programma, non fotografie di persone. Qui zero è la risposta",
                "  giusta, non un guasto. Il banco di prova vero sono le tue foto.",
            ]
        else:
            righe += [
                "  Il modello non ha proposto nessun riquadro. Se in queste foto",
                "  ci sono delle persone, allora è un difetto: manda queste righe",
                "  a chi ha scritto il programma.",
            ]
    elif conto.poco_sicure == conto.proposte:
        righe += [
            "  Il modello ha visto qualcosa, ma sempre sotto la sicurezza che gli",
            f"  è stata chiesta ({passata.rilevatore.sicurezza_minima:.2f}). Si"
            " abbassa dalle Impostazioni,",
            "  «quanto deve essere sicuro prima di attribuire un volto»: generoso.",
        ]
    elif conto.troppo_piccole == conto.proposte:
        righe += [
            "  Le facce c'erano, ma tutte troppo piccole perché ci fossero",
            "  abbastanza pixel da riconoscerle. Succede con le foto di gruppo",
            "  da lontano.",
        ]
    return righe
