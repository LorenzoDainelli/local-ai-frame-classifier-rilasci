from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

from officina import VERSIONE, modelli_in_casa, registro
from officina.archivio import accesso, copie
from officina.errori import ErroreOfficina, perche_saltato
from officina.impostazioni import FINTO, REALE, posizione
from officina.prova import IN_PIU, SERVONO
from officina.volti import spiegazione


def _chiave_hf() -> str | None:
    from officina.programma import segreti

    return segreti.chiave_hf()


def _archivio(argomenti) -> str:
    return FINTO if getattr(argomenti, "finto", False) else REALE


def _apri(argomenti):
    from officina import forziere

    nome = _archivio(argomenti)
    cassa = forziere.per(posizione(nome))
    if not cassa.acceso or cassa.aperto:
        return accesso.apri(nome)

    parola = os.environ.get("OFFICINA_PASSWORD")
    if not parola:
        import getpass

        print()
        print(f"  L'archivio «{nome}» è dentro un forziere (regola 331).")
        try:
            parola = getpass.getpass("  Password: ")
        except (EOFError, KeyboardInterrupt):
            raise ErroreOfficina(
                "Qui non c'è nessuno a cui chiedere la password, e questo "
                "archivio è dentro un forziere. Se lo stai avviando da uno "
                "script, mettila nella variabile d'ambiente "
                "OFFICINA_PASSWORD.") from None
    return accesso.apri(nome, password=parola)


def comando_avvia(argomenti) -> int:
    import threading

    from officina import finestra

    _controlla_che_ci_sia_tutto()
    import uvicorn

    from officina.web import origine

    archivio = _apri(argomenti)
    di_rete = None
    if argomenti.rete:
        archivio.imposta("accesso_dalla_rete", True)
        di_rete = _apri_alla_rete(origine)

    print()
    print(f"  Officina {VERSIONE} — archivio «{archivio.dove.nome}»")
    print(f"  {archivio.dove.radice}")
    print()
    if di_rete is not None:
        print("  Aperto agli altri computer di casa (regola 190), solo cifrato:")
        print(f"  https://<indirizzo di questo computer>:{di_rete.porta}")
        print("  Passano solo gli indirizzi della rete locale (regola 189).")
    elif argomenti.rete:
        print("  Non sono riuscito ad aprirlo alla rete di casa.")
    else:
        print("  Raggiungibile solo da questo computer.")
        print("  Per aprirlo allo ZenBook: --rete")
    print()
    print(f"  {origine.indirizzo_per_entrare(f'http://localhost:{argomenti.porta}')}")
    print()

    if argomenti.apri:
        threading.Thread(target=_apri_la_finestra,
                         args=(finestra, argomenti.porta),
                         name="finestra", daemon=True).start()

    try:
        uvicorn.run("officina.web.server:app", host="127.0.0.1", port=argomenti.porta,
                    log_level="warning", access_log=False)
    finally:
        if di_rete is not None:
            origine.smetti_la_rete()
            di_rete.ferma()
        accesso.chiudi()
    return 0


def _apri_alla_rete(origine):
    from officina.programma import carta
    from officina.programma.servitore import PORTA_DELLA_RETE, per_la_rete

    try:
        servitore, impronta = per_la_rete(carta.casa() / "rete", PORTA_DELLA_RETE)
        servitore.parti()
    except Exception as guasto:
        registro.errore("riga_di_comando.rete_non_aperta", **registro.dove_si_e_rotto(guasto))
        return None
    origine.segna_la_rete(servitore.porta, impronta)
    return servitore


def _apri_la_finestra(finestra, porta: int) -> None:
    try:
        com_e_andata = finestra.apri_quando_e_pronto(porta)
    except Exception:
        com_e_andata = "niente"

    if com_e_andata == "finestra":
        print("  Aperta. Per fermare l'Officina, chiudi anche questa "
              "finestra nera.")
    elif com_e_andata == "browser":
        print("  Aperta nel browser. Per una finestra pulita, senza barra "
              "degli indirizzi, servirebbe Chrome o Edge.")
    else:
        print("  Non sono riuscito ad aprirla da solo: apri tu l'indirizzo "
              "qui sopra.")


def _controlla_che_ci_sia_tutto() -> None:
    mancanti = [pacchetto for modulo, pacchetto in SERVONO
                if importlib.util.find_spec(modulo) is None]
    if mancanti:
        raise ErroreOfficina(
            "Manca qualcosa che serve per partire: " + ", ".join(mancanti)
            + ". Si mette a posto con un comando solo:\n\n"
            "      pip install -r requirements.txt")


def riga_che_si_riscrive():
    stato = {"ultima": "", "larga": 0}

    def scrivi(riga: str) -> None:
        if riga == stato["ultima"]:
            return
        stato["ultima"] = riga
        stato["larga"] = max(stato["larga"], len(riga))
        sys.stdout.write("\r" + riga.ljust(stato["larga"]))
        sys.stdout.flush()

    def pulisci() -> None:
        if stato["larga"]:
            sys.stdout.write("\r" + " " * stato["larga"] + "\r")
            sys.stdout.flush()

    scrivi.pulisci = pulisci
    return scrivi


def comando_importa(argomenti) -> int:
    from officina.importazione.motore import Motore

    archivio = accesso.apri(_archivio(argomenti))
    motore = Motore(archivio)

    try:
        cartelle = [Path(c).expanduser().resolve() for c in argomenti.cartelle]
        if cartelle:
            piano = motore.prepara(cartelle)
            print(f"\n  {piano['file']} file da guardare "
                  f"({piano['byte'] / 1e9:.1f} GB)")
            print(f"  {piano['spazio'].a_parole()}")
            if not piano["spazio"].basta:
                print("  ATTENZIONE: lo spazio potrebbe non bastare (regola 132).")
            if argomenti.solo_conta:
                return 0
        elif motore.riprendi() is None:
            print("  Non c'è niente da riprendere. Indica una cartella.")
            return 1
        else:
            stato = motore.stato()
            print(f"\n  Riprendo dal file {stato.fatti + stato.saltati + 1} "
                  f"di {stato.totale} (regola 277)")

        scrivi = riga_che_si_riscrive()

        def mostra(stato) -> None:
            scrivi(f"  {stato.fatti + stato.saltati}/{stato.totale} "
                   f"· {stato.nuovi_scatti} scatti "
                   f"· {stato.coppie_live} live "
                   f"· {stato.quanto_manca()}")

        print()
        stato = motore.esegui(al_passo=mostra)
        print("\n")
        print(f"  Fatti: {stato.fatti} · saltati: {stato.saltati} "
              f"· scatti nuovi: {stato.nuovi_scatti} · coppie live: {stato.coppie_live} "
              f"· già presenti: {stato.gia_presenti}")
        if stato.saltati:
            print(f"  {stato.saltati} file non si sono aperti: li trovi in «Da guardare» "
                  "con scritto perché (regola 279).")
        print()
        return 0
    except KeyboardInterrupt:
        motore.ferma()
        print("\n\n  Fermato. Riprende da qui la prossima volta (regola 48).\n")
        return 0
    finally:
        accesso.chiudi()


def comando_finto(argomenti) -> int:
    from officina.finto import generatore

    dove = Path(argomenti.dove).expanduser().resolve()
    print(f"\n  Costruisco {argomenti.quanti} scatti finti in {dove}")
    print("  Nessun dato reale entra mai qui dentro (regole 111, 341).\n")

    rapporto = generatore.genera(dove, quanti=argomenti.quanti, seme=argomenti.seme,
                                 leggero=argomenti.leggero)
    print(f"  {rapporto.file_attesi} file, {rapporto.byte / 1e6:.1f} MB")
    print(f"  foto {rapporto.foto} · live {rapporto.coppie_live} · video {rapporto.video}")
    print(f"  schermate {rapporto.schermate} · senza data {rapporto.senza_data} "
          f"· doppioni {rapporto.doppioni} · rotti {rapporto.rotti}")
    print(f"\n  Adesso:  python -m officina importa --finto \"{dove}\"\n")
    return 0


def comando_impronte(argomenti) -> int:
    from officina.descrittori import SCHEDE, in_casa
    from officina.impronte.motore import Passata

    archivio = accesso.apri(_archivio(argomenti))
    try:
        quali = _quali_descrittori(argomenti, archivio)
        if not quali:
            print("\n  Nessun descrittore disponibile.")
            print("  I due grandi si scaricano con:  python -m officina modelli"
                  " --scarica tutti\n")
            return 1

        print()
        for nome in quali:
            carta = SCHEDE[nome]
            if not in_casa(nome, archivio.dove.modelli):
                print(f"  {carta.titolo}: non è in casa, lo salto.")
                continue

            passata = Passata(archivio, nome, intensita=argomenti.intensita,
                              fotogrammi_per_video=argomenti.fotogrammi)
            if argomenti.rifai:
                from officina.modello import impronte as magazzino
                with archivio.scrittura() as connessione:
                    quante = magazzino.togli_di(connessione, nome, carta.versione)
                print(f"  {carta.titolo}: buttate via {quante} impronte, si rifà.")

            da_fare = passata.quanti_mancano()
            if not da_fare:
                print(f"  {carta.titolo}: già fatto, niente da guardare.")
                continue

            quanti = argomenti.quanti
            if quanti and quanti < da_fare:
                print(f"  {carta.titolo} — {da_fare} scatti da guardare, "
                      f"ma mi fermo dopo {quanti} (--quanti)")
            else:
                print(f"  {carta.titolo} — {da_fare} scatti da guardare")
            if carta.va_scaricato:
                print(f"    carico il modello — {carta.byte_attesi / 1e9:.1f} GB, "
                      "ci mette un momento")
            scrivi = riga_che_si_riscrive()

            def mostra(avanzamento, _scrivi=scrivi) -> None:
                _scrivi(f"    {avanzamento.fatti + avanzamento.saltati}/"
                        f"{avanzamento.totale} · {avanzamento.impronte} impronte "
                        f"· {avanzamento.quanto_manca()}")

            try:
                fine = passata.esegui(al_passo=mostra, quanti_al_massimo=argomenti.quanti)
            except KeyboardInterrupt:
                passata.ferma()
                print("\n\n  Fermato. Riprende da qui la prossima volta "
                      "(regole 48, 277).\n")
                return 0

            print()
            print(f"    {fine.dove_gira}")
            print(f"    fatti {fine.fatti} · saltati {fine.saltati} "
                  f"· impronte {fine.impronte} · fotogrammi {fine.fotogrammi}")
            if fine.motivi_saltati:
                for motivo, quanti in sorted(fine.motivi_saltati.items()):
                    print(f"    {quanti} saltati: {perche_saltato(motivo)}")
            if fine.riposo_secondi > 1:
                print(f"    fermo {fine.riposo_secondi:.0f} secondi per tenere la "
                      f"scheda al {passata.intensita}% (regola 182)")
            if fine.pause_per_calore:
                print(f"    {fine.pause_per_calore} pause perché scaldava "
                      "(regola 181)")
            print()
        return 0
    finally:
        accesso.chiudi()


def _quali_descrittori(argomenti, archivio) -> list[str]:
    from officina.descrittori import SCHEDE, PREDEFINITO, pronti

    if argomenti.descrittore:
        if argomenti.descrittore not in SCHEDE:
            raise ErroreOfficina(
                f"Descrittore sconosciuto: «{argomenti.descrittore}». "
                f"Ci sono: {', '.join(SCHEDE)}."
            )
        return [argomenti.descrittore]
    if argomenti.tutti:
        return pronti(archivio.dove.modelli)
    disponibili = pronti(archivio.dove.modelli)
    return [disponibili[0]] if disponibili else [PREDEFINITO]


def comando_misura(argomenti) -> int:
    from officina.misura import banco, rapporto as resoconto

    archivio = accesso.apri(_archivio(argomenti))
    try:
        if argomenti.scene:
            if archivio.dove.nome != FINTO:
                raise ErroreOfficina(
                    "Le etichette dalle scene esistono solo per l'archivio "
                    "finto: sull'archivio vero le decisioni le prendi tu, ed è "
                    "tutto il senso della misura (regola 105). Aggiungi --finto."
                )
            from officina.finto import etichette

            messe = etichette.metti(archivio, Path(argomenti.scene).expanduser())
            print(f"\n  Messe {messe.etichette} etichette su {messe.nodi} nodi "
                  "di prova (regole 111, 114).")

        print("\n  Misuro. Ogni confronto usa gli stessi esempi e la stessa "
              "divisione (regola 107).")
        scrivi = riga_che_si_riscrive()

        def mostra(cosa: str) -> None:
            scrivi(f"    {cosa}")

        misurato = banco.misura(archivio, al_passo=mostra)
        scrivi.pulisci()

        testo = resoconto.come_testo(misurato)
        print(testo)

        dove = Path(argomenti.scrivi).expanduser() if argomenti.scrivi else None
        if dove is None:
            giorno = misurato.fatta_il[:10]
            dove = Path.cwd() / f"misura-{giorno}.txt"
        with archivio.lettura() as connessione:
            resoconto.scrivi(misurato, connessione, dove)
        print(f"  Scritto in {dove}")
        print(f"  e gli stessi numeri in {dove.with_suffix('.json')}, "
              "per riconfrontarli fra mesi (regola 343).")
        print("  Dentro ci sono solo numeri: nessun nome di nodo, nessun nome "
              "di file (regole 106, 112).")
        print("  È stato riletto e controllato prima di scriverlo.\n")

        with archivio.scrittura() as connessione:
            connessione.execute(
                "INSERT INTO misure (fatta_il, archivio, scatti, gruppi, nodi, "
                "rapporto) VALUES (?, ?, ?, ?, ?, ?)",
                (misurato.fatta_il, archivio.dove.nome, misurato.scatti,
                 misurato.gruppi, len(misurato.nodi),
                 resoconto.come_json(misurato)),
            )
        return 0
    finally:
        accesso.chiudi()


def comando_modelli(argomenti) -> int:
    from officina.descrittori import scaricamento

    SCHEDE = modelli_in_casa.tutte_le_carte()
    dove = posizione(_archivio(argomenti)).modelli
    dove.mkdir(parents=True, exist_ok=True)

    from officina.volti import scaricamento as volti_scaricamento

    if argomenti.togli == "volti":
        print("\n  Tolto." if volti_scaricamento.togli(dove)
              else "\n  Non c'era niente da togliere.")
        print()
        return 0

    from officina.corpi import scaricamento as corpi_scaricamento

    if argomenti.togli == "corpi":
        print("\n  Tolto." if corpi_scaricamento.togli(dove)
              else "\n  Non c'era niente da togliere.")
        print()
        return 0

    if argomenti.togli:
        carta = _una_scheda(argomenti.togli)
        print("\n  Tolto." if scaricamento.togli(carta, dove)
              else "\n  Non c'era niente da togliere.")
        print("  Si riscarica quando serve: è l'unica cosa del progetto di "
              "cui questo sia vero.\n")
        return 0

    if argomenti.verifica:
        print("\n  Rileggo ogni file e ricalcolo la sua impronta (regola 74).\n")
        for carta in SCHEDE.values():
            if not carta.va_scaricato:
                continue
            esito = scaricamento.verifica(carta, dove)
            print(f"  {carta.titolo}: {esito['stato']} "
                  f"({esito['controllati']} file controllati)")
            for guasto in esito["guasti"]:
                print(f"      rovinato: {guasto}")
            for mancante in esito["mancanti"]:
                print(f"      manca:    {mancante}")
        volti = volti_scaricamento.verifica(dove)
        print(f"  Volti: {volti['dettaglio']}")
        corpi = corpi_scaricamento.verifica(dove)
        print(f"  Corpi: {corpi['dettaglio']}")
        print()
        return 0

    if argomenti.scarica == "volti":
        print("\n  Questo è l'unico comando che apre una connessione "
              "(regole 1, 74).")
        print("  La licenza di questi due modelli è per **uso non "
              "commerciale** (regola 177).\n")
        try:
            rapporto = volti_scaricamento.scarica(
                dove,
                fonti=_fonti_dei_volti(argomenti),
                al_passo=lambda t: print(f"  {t}"),
                rifai=argomenti.rifai,
                chiave=argomenti.chiave or _chiave_hf())
        except ErroreOfficina as errore:
            print(f"\n  {errore}\n")
            return 1
        if rapporto.gia_c_erano:
            print("  I modelli dei volti c'erano già.")
        print()
        return 0

    if argomenti.scarica == "corpi":
        print("\n  Questo è l'unico comando che apre una connessione "
              "(regole 1, 74).")
        print("  SAM 3 chiede di aver accettato la sua licenza su Hugging Face.\n")
        try:
            rapporto = corpi_scaricamento.scarica(
                dove, al_passo=lambda t: print(f"  {t}"), rifai=argomenti.rifai,
                chiave=argomenti.chiave or _chiave_hf())
        except ErroreOfficina as errore:
            print(f"\n  {errore}\n")
            return 1
        if rapporto.gia_c_erano:
            print("  I modelli del corpo c'erano già.")
        for nome, impronta in corpi_scaricamento.impronte_sha256(dove).items():
            print(f"  sha256 {nome} {impronta}")
        print()
        return 0

    if argomenti.scarica:
        quali = (list(SCHEDE) if argomenti.scarica == "tutti"
                 else [_una_scheda(argomenti.scarica).nome])
        print("\n  Questo è l'unico comando che apre una connessione "
              "(regole 1, 74).")
        print("  Dopo, il programma funziona a scheda di rete spenta.\n")
        andati_male, arrivati = [], 0
        for nome in quali:
            carta = SCHEDE[nome]
            if not carta.va_scaricato:
                continue
            try:
                rapporto = scaricamento.scarica(
                    carta, dove, al_passo=lambda t: print(f"  {t}"),
                    chiave=argomenti.chiave or _chiave_hf())
            except ErroreOfficina as errore:
                andati_male.append(carta.titolo)
                print(f"\n  {errore}\n")
                continue
            arrivati += 1
            if rapporto.gia_c_era:
                print(f"  {carta.titolo}: c'era già.")
        if andati_male and len(quali) > 1:
            coda = (" Gli altri sì." if arrivati else
                    " Il descrittore disegnato a mano non si scarica: c'è già,"
                    " e fa girare tutto lo stesso.")
            print(f"  Non sono arrivati: {', '.join(andati_male)}.{coda}")
        print()
        return 1 if andati_male else 0

    print("\n  I modelli (regole 74, 101, 177)\n")
    _dillo_dei_volti(dove)
    for carta in SCHEDE.values():
        esito = scaricamento.stato(carta, dove)
        segno = "c'è" if esito["in_casa"] else "da scaricare"
        peso = (f"{esito['byte'] / 1e9:.1f} GB" if esito["in_casa"] and esito["byte"]
                else f"~{carta.byte_attesi / 1e9:.1f} GB" if carta.va_scaricato
                else "—")
        print(f"  {carta.titolo}")
        a_cosa_serve = (f"impronta di {carta.dimensione} numeri"
                        if carta.dimensione else "la ricerca a parole")
        print(f"      {segno} · {peso} · {a_cosa_serve}")
        print(f"      licenza: {carta.licenza}")
        if carta.va_scaricato:
            print(f"      si chiama: {carta.identificatore}")
        print()
    print(f"  Stanno in: {dove}")
    print("  Fuori dai due archivi, perché non sono un dato tuo: li usano "
          "sia il finto sia il vero.")
    print("  Per scaricarli:  python -m officina modelli --scarica tutti\n")
    return 0


def _una_scheda(nome: str):
    carte = modelli_in_casa.tutte_le_carte()
    if nome not in carte:
        raise ErroreOfficina(
            f"Modello sconosciuto: «{nome}». Ci sono: {', '.join(carte)}.")
    return carte[nome]


def comando_doppioni(argomenti) -> int:
    from officina.doppioni import motore as doppioni

    archivio = _apri(argomenti)
    try:
        passata = doppioni.Passata(archivio)
        mancano = passata.quante_mancano()
        if mancano and not argomenti.solo_gruppi:
            print(f"\n  Guardo {mancano} immagini che non ho ancora guardato.")
            avanzamento = passata.esegui(quante_al_massimo=argomenti.quante)
            print(f"  Guardate {avanzamento.guardate}, "
                  f"non riuscite {avanzamento.saltate}.")
        elif mancano:
            print(f"\n  Restano {mancano} immagini mai guardate: "
                  f"i gruppi qui sotto non le comprendono.")

        fatti = doppioni.gruppi(archivio)
        if not fatti:
            print("\n  Nessun doppione: nessuna immagine somiglia a un'altra "
                  "abbastanza da poter essere la stessa.\n")
            return 0

        quante = sum(gruppo.quante for gruppo in fatti)
        print(f"\n  {len(fatti)} gruppi, {quante} file in tutto.")
        print("  Il primo di ogni riga è quello che pesa di più.\n")
        for numero, gruppo in enumerate(fatti, start=1):
            come = "identiche" if gruppo.identiche else f"a {gruppo.distanza_massima} bit"
            print(f"  {numero:3d}. {gruppo.quante} file, {come}: "
                  + ", ".join(str(quale) for quale in gruppo.file_id))
        print("\n  Sono i numeri dei file. Niente è stato toccato.\n")
        return 0
    finally:
        accesso.chiudi()


def comando_dottore(argomenti) -> int:
    from officina.descrittori import scaricamento, torcia
    from officina.immagini import consegna

    SCHEDE = modelli_in_casa.tutte_le_carte()

    capacita = consegna.capacita()
    print(f"\n  Officina {VERSIONE}")
    print(f"  Python {sys.version.split()[0]} su {sys.platform}")
    print()
    print(f"  legge HEIC ....... {'si' if capacita['heic'] else 'NO'}"
          f"{'' if capacita['heic'] else '   <- installa pillow-heif (regola 51)'}")
    print(f"  scrive AVIF ...... {'si' if capacita['avif'] else 'NO'}"
          f"{'' if capacita['avif'] else '   <- le foto andranno al browser in JPEG'}")
    print(f"  scrive WebP ...... {'si' if capacita['webp'] else 'no'}")
    print()

    for modulo, pacchetto in SERVONO:
        c_e = importlib.util.find_spec(modulo) is not None
        print(f"  {(modulo + ' ').ljust(17, '.')} {'si' if c_e else 'NO'}"
              f"{'' if c_e else f'   <- manca: pip install {pacchetto}'}")
    print()

    print("  In più, per i modelli (si installano a parte, regola 74):")
    for modulo, a_cosa_serve, _dove in IN_PIU:
        c_e = importlib.util.find_spec(modulo) is not None
        print(f"  {(modulo + ' ').ljust(17, '.')} {'si' if c_e else 'no'}"
              f"   {a_cosa_serve}")
    print(f"      senza: pip install -r {IN_PIU[0][2]}")
    print()

    macchina = torcia.macchina()
    print(f"  calcolo .......... {macchina.a_parole()}")
    gradi = torcia.temperatura()
    if gradi is not None:
        print(f"  temperatura ...... {gradi} gradi")
    print()

    for nome, carta in SCHEDE.items():
        cartella = posizione(REALE).modelli
        esito = scaricamento.stato(carta, cartella)
        print(f"  modello «{nome}»: "
              + ("in casa" if esito["in_casa"] else "da scaricare"))
    print("      per scaricarli: python -m officina modelli --scarica tutti")
    print()

    for nome in (REALE, FINTO):
        dove = posizione(nome)
        c_e = dove.database.exists()
        peso = dove.database.stat().st_size if c_e else 0
        stato = f"c'è · {peso / 1e6:.1f} MB" if c_e else "non ancora creato"
        print(f"  archivio «{nome}»: {stato}")
        print(f"      {dove.radice}")
        if c_e:
            for riga in _impronte_di(nome):
                print(f"      impronte {riga}")
    print()
    return 0


def _impronte_di(nome: str) -> list[str]:
    from officina.modello import impronte as magazzino

    try:
        archivio = accesso.apri(nome)
        with archivio.lettura() as connessione:
            righe = magazzino.avanzamento(connessione)
        return [f"«{riga['descrittore']}» versione {riga['versione']}: "
                f"{riga['impronte']} su {riga['scatti']} scatti"
                + (f", ne mancano {riga['mancano']}" if riga["mancano"] else "")
                for riga in righe] or ["nessuna ancora calcolata"]
    except Exception:
        return ["non leggibili adesso"]
    finally:
        accesso.chiudi(con_copia=False)


def comando_copie(argomenti) -> int:
    dove = posizione(_archivio(argomenti))

    if argomenti.ripristina:
        copia = copie.ripristina(dove, argomenti.ripristina)
        print(f"\n  Ripristinata la copia del {copia.quando}.")
        print("  Lo stato di prima è stato messo da parte: si torna indietro.\n")
        return 0

    if argomenti.adesso:
        archivio = accesso.apri(_archivio(argomenti))
        try:
            copia = archivio.copia_adesso("manuale")
            print(f"\n  Copia fatta e verificata: {copia.nome}\n")
        finally:
            accesso.chiudi(con_copia=False)
        return 0

    elenco = copie.elenco(dove)
    print(f"\n  {len(elenco)} copie (se ne tengono {copie.QUANTE_SE_NE_TENGONO}, regola 42)\n")
    for copia in elenco:
        print(f"  {copia.quando:<28} {copia.motivo:<24} {copia.byte / 1e6:6.1f} MB  {copia.nome}")
    print()
    return 0


def comando_forziere(argomenti) -> int:
    import getpass

    from officina import forziere

    nome = _archivio(argomenti)
    dove = posizione(nome)
    cassa = forziere.per(dove)

    if argomenti.stato or not (argomenti.accendi or argomenti.spegni):
        print()
        print(f"  Archivio «{nome}»: {cassa.stato().a_parole()}")
        if cassa.acceso:
            print(f"  {cassa.file}")
            print(f"  {cassa.stato().peso / 1e6:.1f} MB")
        else:
            print()
            print("  Per accenderlo:  python -m officina forziere --accendi"
                  + ("  --finto" if nome == FINTO else ""))
            print()
            print("  Da quel momento senza la password l'archivio non si apre,")
            print("  e non esiste nessun modo di recuperarla. Le foto originali")
            print("  restano fuori dal forziere: quelle non si perdono mai.")
        print()
        return 0

    if argomenti.accendi:
        if cassa.acceso:
            print("\n  Questo archivio ha già un forziere.\n")
            return 1
        print()
        print("  Sto per chiudere l'archivio dentro un forziere cifrato.")
        print()
        print("  Da quel momento, senza la password, l'archivio non si apre —")
        print("  e non esiste un «password dimenticata»: se ci fosse una via di")
        print("  recupero, quella via sarebbe anche la via di chi non deve")
        print("  entrare (regola 106).")
        print()
        print("  Le foto originali NON entrano qui dentro e restano intatte")
        print("  nella tua cartella: perdere la password vuol dire perdere il")
        print("  lavoro di catalogazione, mai le foto.")
        print()
        print("  Lunga meglio che complicata: tre parole che ricordi valgono")
        print("  più di otto caratteri strani. Almeno dodici caratteri.")
        print()
        parola = getpass.getpass("  Scegli la password: ")
        ancora = getpass.getpass("  Scrivila di nuovo:  ")
        if parola != ancora:
            print("\n  Le due non coincidono. Non ho toccato niente.\n")
            return 1
        accesso.chiudi(con_copia=False)
        print()
        print("  Ci metto un momento: scrivo, rileggo tutto per controllo, e")
        print("  solo se torna fuori la stessa cosa cancello il chiaro.")
        stato = cassa.accendi(parola)
        print()
        print(f"  Fatto: {cassa.file.name}, {stato.peso / 1e6:.1f} MB.")
        print("  Da adesso «avvia» chiede la password.")
        print()
        return 0

    if not cassa.acceso:
        print("\n  Questo archivio non ha un forziere.\n")
        return 1
    parola = os.environ.get("OFFICINA_PASSWORD") or getpass.getpass("  Password: ")
    accesso.chiudi(con_copia=False)
    cassa.spegni(parola)
    print()
    print("  Forziere spento: l'archivio è di nuovo una cartella in chiaro.")
    print("  Il disco resta cifrato da Windows (regola 9), ma chi apre il")
    print("  computer acceso adesso vede tutto.")
    print()
    return 0


def _fonti_dei_volti(argomenti) -> dict:
    from dataclasses import replace

    from officina.volti import rilevatore, scaricamento

    fonti = dict(scaricamento.DA_DOVE)
    per_uno = {
        rilevatore.FILE_RILEVATORE: ("repo_rilevatore", "file_rilevatore"),
        rilevatore.FILE_RICONOSCITORE: ("repo_riconoscitore", "file_riconoscitore"),
    }
    for nome, (chiave_repo, chiave_file) in per_uno.items():
        fonte = fonti[nome]
        repo = (getattr(argomenti, chiave_repo, None)
                or getattr(argomenti, "repo", None) or fonte.repo)
        file = getattr(argomenti, chiave_file, None) or fonte.nome_sul_sito
        cambiata = (repo != fonte.repo) or (file != fonte.nome_sul_sito)
        altro_file = file != fonte.nome_sul_sito
        fonti[nome] = replace(
            fonte, repo=repo, nome_sul_sito=file,
            provata=fonte.provata and not cambiata,
            sha256="" if altro_file else fonte.sha256,
            byte=0 if altro_file else fonte.byte,
            licenza="" if altro_file else fonte.licenza,
            riserve=() if cambiata else fonte.riserve)
    return fonti


def _dillo_dei_volti(dove) -> None:
    from officina.volti import rilevatore, scaricamento

    ci_sono = scaricamento.gia_in_casa(dove)
    stato = "ci sono" if ci_sono else "da scaricare"
    print(f"  Volti (rilevatore + riconoscitore) — {stato}")
    print("      per trovare le facce e riconoscerle (regole 33, 339)")
    for nome, fonte in scaricamento.DA_DOVE.items():
        print(f"      {scaricamento.come_si_chiama(nome)}: {fonte.repo}"
              + (f" — licenza {fonte.licenza}" if fonte.licenza else ""))
    if not ci_sono:
        print("      python -m officina modelli --scarica volti")
    if not rilevatore.c_e_onnxruntime():
        print("      manca anche «onnxruntime»: "
              "pip install -r requirements-modelli.txt")
    print()


def comando_volti(argomenti) -> int:
    from officina.modello import persone
    from officina.volti import gruppi, motore, rilevatore

    archivio = _apri(argomenti)
    try:
        if argomenti.raggruppa_e_basta:
            with archivio.scrittura() as connessione:
                fatto = gruppi.raggruppa(connessione)
            print(f"\n  {fatto.a_parole()}\n")
            return 0

        manca = rilevatore.cosa_manca(archivio.dove.modelli)
        if manca:
            print(f"\n  {manca}\n")
            return 1

        passata = motore.Passata(archivio, intensita=argomenti.intensita)
        quanti = passata.quanti_mancano()
        print(f"\n  {quanti} scatti da guardare"
              + (f", ma mi fermo dopo {argomenti.quanti} (--quanti)"
                 if argomenti.quanti else ""))
        print()

        scrivi = riga_che_si_riscrive()
        passata.esegui(
            al_passo=lambda a: scrivi(
                f"  {a.fatti + a.saltati}/{a.totale} · {a.volti} volti"),
            quanti=argomenti.quanti)
        scrivi.pulisci()
        print(f"  {passata.avanzamento.a_parole()}")
        if passata.avanzamento.volti == 0 and passata.avanzamento.fatti:
            for riga in spiegazione.perche_nessun_volto(
                    passata, bool(getattr(argomenti, "finto", False))):
                print(riga)

        with archivio.scrittura() as connessione:
            fatto = gruppi.raggruppa(connessione)
        print(f"  {fatto.a_parole()}")

        with archivio.lettura() as connessione:
            resta = persone.quanti_da_guardare(connessione)
        if resta["senza_nome"]:
            print(f"\n  {resta['senza_nome']} gruppi aspettano un nome: "
                  "aprili dall'Officina, in «Persone».")
        print()
        return 0
    finally:
        accesso.chiudi()


def comando_scorciatoia(argomenti) -> int:
    from officina import finestra

    fatti = finestra.crea_scorciatoia()
    print()
    if not fatti:
        print("  Non sono riuscito a creare il collegamento, e non so dirti")
        print("  perché. L'Officina si apre comunque così:")
        print()
        print("      python -m officina avvia")
        print()
        return 1
    print("  Fatto. Adesso l'Officina si apre da qui:")
    print()
    for dove in fatti:
        print(f"      {dove}")
    print()
    print("  Doppio clic e parte. Si apre una finestra sua, senza barra degli")
    print("  indirizzi, e dietro resta una finestra nera ridotta a icona: è")
    print("  il programma che gira, e chiudendola l'Officina si ferma.")
    print()
    return 0


def comando_pacchetto(argomenti) -> int:
    from officina.modello import telefoni
    from officina.telefono import costruzione, formato, selezione

    with _apri(argomenti) as archivio:
        connessione = archivio.connessione

        if argomenti.nuovo:
            with archivio.scrittura() as scrivi:
                telefoni.crea(scrivi, argomenti.nuovo, argomenti.sistema)
            print(f"\n  Aggiunto «{argomenti.nuovo}» ({argomenti.sistema}).\n")
            return 0

        elenco = telefoni.elenco(connessione)
        if not argomenti.telefono:
            print()
            if not elenco:
                print("  Non c'è ancora nessun telefono. Si aggiunge così:")
                print()
                print("      python -m officina pacchetto --nuovo iPhone "
                      "--sistema ios")
                print()
                return 0
            print("  I telefoni di questo archivio:")
            print()
            for riga in elenco:
                quanti, peso = telefoni.peso_del_pacchetto(connessione,
                                                           riga["id"])
                quando = riga["ultimo_travaso_il"] or "mai"
                print(f"      {riga['nome']}  ({riga['sistema']})  "
                      f"{quanti} file, {selezione.a_misura(peso)}, "
                      f"ultimo travaso: {quando}")
            print()
            return 0

        telefono = telefoni.per_nome(connessione, argomenti.telefono)
        if telefono is None:
            raise ErroreOfficina(
                f"Non c'è nessun telefono che si chiama «{argomenti.telefono}». "
                "Si aggiunge con --nuovo.")

        if argomenti.spazio is not None:
            with archivio.scrittura() as scrivi:
                telefoni.dichiara_spazio(scrivi, telefono["id"],
                                         int(argomenti.spazio * 1_000_000_000))
            telefono = telefoni.per_nome(connessione, argomenti.telefono)

        dove = Path(argomenti.dove or telefono["cartella"]
                    or formato.nome_cartella(telefono["nome"]))

        travaso = costruzione.Travaso(
            archivio, telefono["id"], dove,
            _parola_del_pacchetto(archivio, argomenti),
            quando_cambia=_a_che_punto)
        piano = travaso.prepara()

        print()
        print(f"  Pacchetto per «{piano.telefono}» in {dove}")
        print(f"  Selezione: {piano.scelta.a_parole()}")
        print(f"  {piano.stima.a_parole()}")
        if piano.ripresa:
            print("  C'è un travaso lasciato a metà: riprendo da lì.")
        print(f"  {piano.a_parole()}")
        if piano.saltati:
            print(f"  {len(piano.saltati)} scatti non entrano: "
                  f"{piano.saltati[0].perche}")
        ci_sta = piano.stima.ci_sta_in(telefono["spazio"])
        if ci_sta is False:
            manca = piano.stima.peso - telefono["spazio"]
            print(f"  NON CI STA per {selezione.a_misura(manca)}: stringi la "
                  "selezione, oppure fai spazio sul telefono.")
        elif ci_sta is None:
            print("  Quanto spazio ha questo telefono non lo so: se vuoi che "
                  "te lo dica, scrivilo con --spazio.")
        print()

        if argomenti.solo_conta:
            print("  Mi fermo qui: era solo un conto (regola 274).")
            print(f"  Per farlo davvero:  {piano.stima.sul_tasto(piano.telefono)}")
            print()
            return 0

        esito = travaso.esegui(piano)

    print()
    print(f"  Scritti {esito.scritti} file "
          f"({selezione.a_misura(esito.peso)}), tolti {esito.tolti}, "
          f"riletti e verificati {esito.verificati}.")
    if esito.tornato.c_era:
        print(f"  Dal telefono è tornato: {esito.tornato.a_parole()}")
    for saltato in esito.saltati[:10]:
        print(f"  Non entrato — {saltato.posto}: {saltato.perche}")
    if len(esito.saltati) > 10:
        print(f"  ...e altri {len(esito.saltati) - 10}.")
    for guasto in esito.guasti[:10]:
        print(f"  NON TORNA — {guasto}")
    print()
    if esito.completo:
        print("  Il pacchetto è completo. Adesso collega il telefono e copia")
        print(f"  la cartella {dove} nello spazio dell'app.")
    else:
        print("  Il pacchetto è dichiarato INCOMPLETO: l'app non lo aprirà")
        print("  credendo che sia finito. Rilancia il comando per riprendere.")
    print()
    return 0 if esito.completo else 1


def comando_leggi_pacchetto(argomenti) -> int:
    import getpass

    from officina.telefono import lettore, selezione

    dove = Path(argomenti.cartella)
    parola = os.environ.get("OFFICINA_PASSWORD") or getpass.getpass(
        "  Password del pacchetto: ")

    with lettore.apri(dove, parola) as pacchetto:
        detto = pacchetto.informazioni()
        print()
        print(f"  Pacchetto di «{detto['telefono']}» — formato "
              f"{detto['versione_formato']}, fatto da Officina "
              f"{detto.get('versione_officina', '?')}")
        if not pacchetto.completo:
            print("  ATTENZIONE: dichiarato incompleto. Quello che c'è si "
                  "guarda lo stesso (regola 156).")
        print(f"  {pacchetto.quanti()} scatti, {len(pacchetto.nodi())} nodi, "
              f"{len(pacchetto.persone())} persone")
        giorni = pacchetto.giorni()
        if giorni:
            print(f"  {len(giorni)} giornate, dalla più recente: "
                  f"{giorni[0]['giorno'] or 'senza data'} "
                  f"({giorni[0]['quanti']} scatti)")
        print()

        if argomenti.scatto:
            riga = pacchetto.scatto(argomenti.scatto)
            grezzo = pacchetto.originale(argomenti.scatto)
            print(f"  Scatto {riga['id']}: {riga['posto']}")
            print(f"  {riga['genere']}, {riga['giorno'] or 'senza data'}, "
                  f"{selezione.a_misura(len(grezzo))} aperti davvero")
            print(f"  impronta {riga['impronta'][:16]}...")
            if argomenti.tira_fuori:
                pacchetto.tira_fuori(argomenti.scatto, Path(argomenti.tira_fuori))
                print(f"  Rimesso in chiaro in {argomenti.tira_fuori}")
            print()

        if argomenti.verifica:
            print("  Rileggo tutto e confronto le impronte. Ci vuole un po'.")
            esito = pacchetto.verifica(solo=argomenti.quanti)
            print(f"  {esito.a_parole()}")
            for guasto in esito.guasti[:20]:
                print(f"    {guasto.posto}: {guasto.perche}")
            print()
            return 0 if esito.tutto_a_posto else 1
    return 0


def comando_sincronizza(argomenti) -> int:
    from officina.modello import cambiamenti
    from officina.sincronia import costruzione, fusione, lettore

    if argomenti.guarda:
        carta = lettore.sbircia(Path(argomenti.guarda))
        print()
        print(f"  Pacchetto da «{carta.mittente_nome}», archivio "
              f"«{carta.archivio}»")
        print(f"  Cambiamenti: {carta.quanti_cambiamenti} "
              f"(dal {carta.dal_seriale + 1} al {carta.al_seriale})")
        print(f"  File: {carta.quanti_file}, miniature: "
              f"{carta.quante_miniature}")
        print(f"  Stato: {'intero' if carta.completa else 'INTERROTTO'}")
        if carta.note:
            print(f"  Note: {len(carta.note)}")
        print()
        return 0

    with _apri(argomenti) as archivio:
        connessione = archivio.connessione
        mia = cambiamenti.questa_macchina(connessione)

        if argomenti.chiamami:
            with archivio.scrittura() as scrivi:
                cambiamenti.rinomina_macchina(scrivi, mia["id"],
                                              argomenti.chiamami)
            print(f"\n  Questo computer adesso si chiama "
                  f"«{argomenti.chiamami}».\n")
            return 0

        if argomenti.applica:
            esito = fusione.fondi(
                archivio, Path(argomenti.applica),
                _parola_del_pacchetto(archivio, argomenti),
                avanzamento=lambda fatti, totale: _a_che_punto(
                    "file", fatti, totale))
            _racconta_la_fusione(esito)
            return 0

        altre = cambiamenti.altre_macchine(connessione)

        if not argomenti.dove:
            print()
            print(f"  Questo computer si chiama «{mia['nome']}».")
            print(f"  Cambiamenti scritti finora: "
                  f"{cambiamenti.quanti_da_mandare(connessione)}")
            print()
            if altre:
                print("  Le altre macchine che conosco:")
                for riga in altre:
                    da_mandare = cambiamenti.quanti_da_mandare(
                        connessione, riga["mi_ha_vista_fino_a"])
                    print(f"      {riga['nome']}  —  da mandarle: "
                          f"{da_mandare} cambiamenti")
            else:
                print("  Non conosco ancora nessun'altra macchina: il primo")
                print("  pacchetto le porta tutto, ed è quello grosso.")
            print()
            print("  Per farne uno:")
            print()
            print("      python -m officina sincronizza --dove C:\\pacchetti")
            print()
            print("  Per applicarne uno arrivato dall'altro computer:")
            print()
            print("      python -m officina sincronizza --applica "
                  "C:\\pacchetti\\Officina-da-...")
            print()
            return 0

        per_id = None
        if not argomenti.per and len(altre) == 1:
            per_id = altre[0]["id"]
            print(f"\n  Lo faccio per «{altre[0]['nome']}», l'unica altra "
                  "macchina che conosco.")
        elif argomenti.per:
            trovate = [r for r in altre
                       if r["nome"].lower() == argomenti.per.lower()]
            if not trovate:
                raise ErroreOfficina(
                    f"Non conosco nessuna macchina che si chiama "
                    f"«{argomenti.per}». La conoscerò quando mi arriverà un "
                    "suo pacchetto.")
            per_id = trovate[0]["id"]

        fatto = costruzione.costruisci(
            archivio, Path(argomenti.dove),
            _parola_del_pacchetto(archivio, argomenti), per_macchina_id=per_id,
            avanzamento=lambda fatti, totale: _a_che_punto("file", fatti, totale))

        print()
        print(f"  Fatto: {fatto.cartella}")
        print(f"  {fatto.carta.quanti_cambiamenti} cambiamenti, "
              f"{fatto.carta.quanti_file} file, "
              f"{fatto.carta.quante_miniature} miniature")
        if fatto.note:
            print(f"  {len(fatto.note)} originali non erano più sul disco: "
                  "le etichette viaggiano lo stesso (regola 96).")
        print()
        print("  Adesso portala sull'altro computer come preferisci.")
        print()
        return 0


def _racconta_la_fusione(esito) -> None:
    print()
    print(f"  Pacchetto da «{esito.mittente}», "
          f"cambiamenti dal {esito.dal_seriale + 1} al {esito.al_seriale}.")
    print()
    if not esito.qualcosa_e_cambiato:
        print("  Non c'era niente di nuovo: l'avevo già letto tutto.")
        print()
        return
    print(f"  Fotografie nuove: {esito.file_nuovi} — di cui arrivate col "
          f"pacchetto: {esito.originali_copiati}, "
          f"con la miniatura già pronta: {esito.miniature_copiate}")
    print(f"  Impronte prese così come stavano: {esito.impronte_prese}")
    print(f"  Nodi: {esito.nodi_creati} creati, "
          f"{esito.nodi_rinominati} rinominati, {esito.nodi_spostati} spostati, "
          f"{esito.nodi_cestinati} cestinati")
    print(f"  Etichette: {esito.etichette_messe} messe, "
          f"{esito.etichette_tolte} tolte")
    if esito.etichette_perse:
        print(f"  {esito.etichette_perse} etichette in arrivo sono state "
              "scartate perché qui c'era una tua decisione più forte "
              "(regole 404, 405).")
    if esito.nodi_risorti:
        print(f"  {esito.nodi_risorti} nodi sono tornati in vita perché qui "
              "li avevi usati dopo (regola 407).")
    if esito.persone_nominate:
        print(f"  {esito.persone_nominate} persone hanno preso il nome che gli "
              "avevi dato sull'altro computer.")
    if esito.persone_da_guardare:
        print(f"  {esito.persone_da_guardare} coppie di persone sono finite nel "
              "cassetto: le guardi affiancate e decidi tu (regola 408).")
    if esito.cuori_arrivati:
        print(f"  {esito.cuori_arrivati} cuori dal telefono, col nome del "
              "telefono attaccato (regola 409).")
    if esito.gesti_gia_visti:
        print(f"  {esito.gesti_gia_visti} cambiamenti li avevo già visti: "
              "riletti e lasciati stare.")
    for nota in esito.note:
        print(f"      · {nota}")
    print()


def _parola_del_pacchetto(archivio, argomenti) -> str:
    import getpass

    gia = archivio.parola_del_forziere
    if gia:
        return gia
    dalla_variabile = os.environ.get("OFFICINA_PASSWORD")
    if dalla_variabile:
        return dalla_variabile
    print()
    print("  Questo archivio non ha un forziere, ma il pacchetto si cifra")
    print("  comunque: il fisso sta in camera, il telefono esce di casa.")
    print("  Sarà la password che l'app ti chiederà a ogni apertura.")
    print()
    parola = getpass.getpass("  Password del pacchetto: ")
    ancora = getpass.getpass("  Scrivila di nuovo:      ")
    if parola != ancora:
        raise ErroreOfficina("Le due non coincidono. Non ho toccato niente.")
    return parola


def _a_che_punto(fase: str, fatti: int, totale: int) -> None:
    if totale and (fatti % 25 == 0 or fatti == totale):
        print(f"\r  {fase}: {fatti} di {totale}   ", end="", flush=True)
        if fatti == totale:
            print()


def costruisci_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="officina",
        description="Officina — il classificatore locale di foto e video.",
    )
    parser.add_argument("--versione", action="version", version=f"Officina {VERSIONE}")
    comandi = parser.add_subparsers(dest="comando", required=True)

    avvia = comandi.add_parser("avvia", help="apre l'archivio e accende il server")
    avvia.add_argument("--porta", type=int, default=8080)
    avvia.add_argument("--non-aprire", dest="apri", action="store_false",
                       help="non aprire la finestra da solo")
    avvia.add_argument("--rete", action="store_true",
                       help="rendi raggiungibile dagli altri computer di casa (regola 190)")
    avvia.add_argument("--finto", action="store_true", help="usa l'archivio finto")
    avvia.set_defaults(funzione=comando_avvia)

    importa = comandi.add_parser("importa", help="importa una o più cartelle")
    importa.add_argument("cartelle", nargs="*")
    importa.add_argument("--finto", action="store_true")
    importa.add_argument("--solo-conta", action="store_true", dest="solo_conta",
                         help="dice cosa ha trovato e si ferma lì (regola 274)")
    importa.set_defaults(funzione=comando_importa)

    finto = comandi.add_parser("finto", help="costruisce l'archivio finto (regola 111)")
    finto.add_argument("dove")
    finto.add_argument("--quanti", type=int, default=120)
    finto.add_argument("--seme", type=int, default=1)
    finto.add_argument("--leggero", action="store_true",
                       help="immagini piccole: per le prove, non per guardare")
    finto.set_defaults(funzione=comando_finto)

    impronte = comandi.add_parser(
        "impronte", help="calcola le impronte numeriche (regole 16, 329)")
    impronte.add_argument("--finto", action="store_true")
    impronte.add_argument("--descrittore", help="dinov3 | siglip2 | disegnato")
    impronte.add_argument("--tutti", action="store_true",
                          help="uno dopo l'altro, liberando la scheda (regola 329)")
    impronte.add_argument("--intensita", type=int, default=None,
                          help="da 5 a 100: quanto stressare la scheda (regola 182)")
    impronte.add_argument("--fotogrammi", type=int, default=None,
                          help="quanti fotogrammi per video (regola 41)")
    impronte.add_argument("--quanti", type=int, default=None,
                          help="fermati dopo tanti scatti: per provare")
    impronte.add_argument("--rifai", action="store_true",
                          help="butta via le impronte di questo modello e le rifà")
    impronte.set_defaults(funzione=comando_impronte)

    misura = comandi.add_parser(
        "misura", help="confronta le scelte sui tuoi dati (regole 105, 336)")
    misura.add_argument("--finto", action="store_true")
    misura.add_argument("--scrivi", metavar="FILE",
                        help="dove scrivere il rapporto")
    misura.add_argument("--scene", metavar="CARTELLA",
                        help="solo per l'archivio finto: prendi le etichette "
                             "dalle scene disegnate dal generatore")
    misura.set_defaults(funzione=comando_misura)

    modelli = comandi.add_parser(
        "modelli", help="scarica e verifica i modelli — l'unico che tocca la rete")
    modelli.add_argument("--finto", action="store_true")
    modelli.add_argument("--scarica", metavar="NOME",
                         help="dinov3 | siglip2 | volti | corpi | tutti")
    modelli.add_argument("--verifica", action="store_true",
                         help="rilegge i file e ricontrolla le impronte")
    modelli.add_argument("--togli", metavar="NOME")
    modelli.add_argument("--chiave", metavar="GETTONE", default="",
                         help="per i modelli che chiedono di accettare le loro "
                              "condizioni; in alternativa la variabile HF_TOKEN")
    modelli.add_argument("--rifai", action="store_true",
                         help="riscarica anche quello che c'è già")
    modelli.add_argument("--repo",
                         help="una pagina che abbia tutti e due i file dei volti")
    modelli.add_argument("--repo-rilevatore", dest="repo_rilevatore",
                         help="la pagina da cui prendere il rilevatore")
    modelli.add_argument("--repo-riconoscitore", dest="repo_riconoscitore",
                         help="la pagina da cui prendere il riconoscitore")
    modelli.add_argument("--file-rilevatore", dest="file_rilevatore",
                         help="il nome del file del rilevatore sul sito")
    modelli.add_argument("--file-riconoscitore", dest="file_riconoscitore",
                         help="il nome del file del riconoscitore sul sito")
    modelli.set_defaults(funzione=comando_modelli)

    volti = comandi.add_parser(
        "volti", help="trova le facce e mette insieme quelle che si somigliano")
    volti.add_argument("--finto", action="store_true")
    volti.add_argument("--quanti", type=int,
                       help="fermati dopo tot scatti: per provare")
    volti.add_argument("--intensita", type=int,
                       help="da 5 a 100 (regola 182)")
    volti.add_argument("--raggruppa-e-basta", action="store_true",
                       dest="raggruppa_e_basta",
                       help="non guardare niente di nuovo, rifai solo i gruppi")
    volti.set_defaults(funzione=comando_volti)

    doppioni_cmd = comandi.add_parser(
        "doppioni", help="le foto che sembrano la stessa, ricompressa")
    doppioni_cmd.add_argument("--finto", action="store_true")
    doppioni_cmd.add_argument("--quante", type=int,
                              help="fermati dopo tot immagini: per provare")
    doppioni_cmd.add_argument("--solo-gruppi", action="store_true",
                              dest="solo_gruppi",
                              help="non guardare niente di nuovo, rifai solo i gruppi")
    doppioni_cmd.set_defaults(funzione=comando_doppioni)

    dottore = comandi.add_parser("dottore", help="cosa sa fare questa macchina")
    dottore.set_defaults(funzione=comando_dottore)

    scorciatoia = comandi.add_parser(
        "scorciatoia", help="mette l'icona dell'Officina sul desktop")
    scorciatoia.set_defaults(funzione=comando_scorciatoia)

    copie_cmd = comandi.add_parser("copie", help="elenca, fa e ripristina le copie")
    copie_cmd.add_argument("--finto", action="store_true")
    copie_cmd.add_argument("--adesso", action="store_true", help="fai una copia adesso")
    copie_cmd.add_argument("--ripristina", metavar="NOME",
                           help="riporta l'archivio a una copia datata (regola 168)")
    copie_cmd.set_defaults(funzione=comando_copie)

    forziere_cmd = comandi.add_parser(
        "forziere", help="il contenitore cifrato: accendilo, spegnilo, guardalo")
    forziere_cmd.add_argument("--finto", action="store_true")
    forziere_cmd.add_argument("--accendi", action="store_true",
                              help="chiudi l'archivio dentro un forziere (regola 340)")
    forziere_cmd.add_argument("--spegni", action="store_true",
                              help="torna a un archivio in chiaro")
    forziere_cmd.add_argument("--stato", action="store_true",
                              help="dimmi soltanto com'è messo")
    forziere_cmd.set_defaults(funzione=comando_forziere)

    pacchetto = comandi.add_parser(
        "pacchetto", help="prepara il pacchetto per il Visore (regola 368)")
    pacchetto.add_argument("--finto", action="store_true")
    pacchetto.add_argument("--telefono", metavar="NOME",
                           help="per quale telefono; senza, li elenca")
    pacchetto.add_argument("--dove", metavar="CARTELLA",
                           help="dove costruirlo; senza, dove l'ultima volta")
    pacchetto.add_argument("--nuovo", metavar="NOME",
                           help="aggiungi un telefono e fermati")
    pacchetto.add_argument("--sistema", default="android",
                           choices=("ios", "android"))
    pacchetto.add_argument("--spazio", metavar="GB", type=float,
                           help="quanto spazio ha quel telefono, quando "
                                "Windows non sa dirlo (regola 369)")
    pacchetto.add_argument("--solo-conta", action="store_true",
                           dest="solo_conta",
                           help="dice cosa farebbe e si ferma lì (regola 274)")
    pacchetto.set_defaults(funzione=comando_pacchetto)

    leggi = comandi.add_parser(
        "leggi-pacchetto",
        help="il telefono finto: apre un pacchetto e ci guarda dentro "
             "(regola 383)")
    leggi.add_argument("cartella")
    leggi.add_argument("--verifica", action="store_true",
                       help="rilegge tutto e confronta le impronte")
    leggi.add_argument("--quanti", type=int,
                       help="verifica solo i primi tot scatti")
    leggi.add_argument("--scatto", type=int, metavar="N",
                       help="apri davvero uno scatto e dimmi com'è andata")
    leggi.add_argument("--tira-fuori", dest="tira_fuori", metavar="FILE",
                       help="rimetti quello scatto in chiaro in un file")
    leggi.set_defaults(funzione=comando_leggi_pacchetto)

    sincronizza = comandi.add_parser(
        "sincronizza",
        help="il pacchetto che viaggia fra i due PC (regole 403-411)")
    sincronizza.add_argument("--finto", action="store_true")
    sincronizza.add_argument("--dove", metavar="CARTELLA",
                             help="dentro quale cartella costruirlo")
    sincronizza.add_argument("--per", metavar="NOME",
                             help="per quale macchina; così non rimanda "
                                  "quello che ha già")
    sincronizza.add_argument("--applica", metavar="CARTELLA",
                             help="applica un pacchetto arrivato dall'altro "
                                  "computer (regole 404-411)")
    sincronizza.add_argument("--guarda", metavar="CARTELLA",
                             help="dice cosa c'è in un pacchetto, senza "
                                  "password e senza aprirlo")
    sincronizza.add_argument("--chiamami", metavar="NOME",
                             help="come si chiama questo computer")
    sincronizza.set_defaults(funzione=comando_sincronizza)

    return parser


def principale(argomenti: list[str] | None = None) -> int:
    parser = costruisci_parser()
    scelte = parser.parse_args(argomenti)
    try:
        return scelte.funzione(scelte)
    except ErroreOfficina as errore:
        print(f"\n  {errore.messaggio}\n", file=sys.stderr)
        registro.errore("avvio.errore")
        return 1
    except KeyboardInterrupt:
        print()
        return 130
