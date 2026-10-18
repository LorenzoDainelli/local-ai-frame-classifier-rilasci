from __future__ import annotations

from strumenti.letture_larghe import come_e_andata, guarda

PERDONATE = {
    "doppioni_gruppi": (2,
        "La tabella è a chiave (firma, file_id) e senza rowid, cioè è già "
        "ordinata per firma: il raggruppamento non chiede nessuna tavola "
        "d'appoggio, e infatti il piano non ne nomina. E contare quanti "
        "gruppi ci sono vuol dire guardarli tutti. Sono due domande diverse "
        "sulla stessa tabella: la pagina dei gruppi ancora da decidere, e il "
        "conto di quanti sono in tutto e quanti già decisi. Il conto era due "
        "volte — il totale e i decisi, ognuno col suo — ed è diventato uno. "
        "L'altra, l'elenco, c'era sempre stata: il soprannome «g» la "
        "nascondeva allo strumento, che leggeva il piano e trovava «SCAN g» "
        "senza sapere chi fosse g."),
    "etichette": (2,
        "Due conti sulle etichette messe da te: quante ne hai messe (schermata "
        "/stato) e se sono cambiate da quando la bottega delle proposte si è "
        "addestrata. Erano tre — il terzo, la stessa domanda senza il filtro "
        "sull'origine, l'ha chiusa senza volerlo la migrazione 22, che "
        "allargando `etichette_per_nodo` gliel'ha resa coperta: 30,2 "
        "millesimi di secondo contro 24,9. Questi due no, perché "
        "l'origine nell'indice non c'è. Misurati su un archivio finto di "
        "duecentomila scatti e quattrocentomila etichette: 38,2 e 23,7 "
        "millesimi. Un indice parziale su `creata_il` li portava a 21,6 e "
        "5,2, ma pesava 11,66 MB su un archivio di 69 — il diciassette per "
        "cento del posto per guadagnarne trentacinque. Prezzo sbagliato "
        "accanto a quello della migrazione 22, che per otto MB e mezzo ne ha "
        "guadagnati quattrocentosettanta. La scelta è di non pagarlo."),
    "scatti": (5,
        "Cinque domande. La terza è larga davvero: quanti scatti non sono "
        "finiti, cioè senza tipologia, senza persone o senza luogo. Per "
        "saperlo bisogna guardarli tutti, e il numero sta in alto in "
        "Etichetta e in Luoghi. Si tiene in memoria finché l'archivio non "
        "cambia, come il conto degli scatti senza etichetta.\n"
        "Le altre due sembrano larghe e non lo sono.\n"
        "La prima è «qual è il primo scatto in archivio», sulla schermata "
        "di benvenuto: cammina sulla chiave primaria e si ferma al primo che "
        "trova. Il piano dice SCAN perché non sa quando si fermerà, ma non "
        "c'è nessuna tavola d'appoggio e l'ordine è quello della chiave.\n"
        "La seconda è «quali scatti hai già deciso tu», e serve ai ripassi: "
        "si legge una volta e poi si risponde per ogni nodo con una ricerca "
        "binaria, invece di rifare la domanda per ognuno. È la stessa scelta "
        "già fatta per le etichette, e per lo stesso motivo. Gira solo "
        "quando c'è almeno un ripasso aperto.\n"
        "Le ultime due sono di «Tempo e mappa», e sono larghe davvero: le "
        "barrette dei mesi contano tutti gli scatti con la data, e i punti "
        "della mappa leggono tutte le posizioni per raggrupparle. Su "
        "duecentomila scatti finti, sparsi apposta perché nessuno cada vicino "
        "a un altro, fanno 137 e 500 millesimi di secondo la prima volta, e 0,1 "
        "le volte dopo: si tengono in memoria finché l'archivio non cambia, "
        "come il conto degli scatti non finiti. Due indici parziali apposta "
        "le portavano a 75 e 390 solo dopo un ANALYZE, e senza ANALYZE SQLite "
        "non li sceglieva nemmeno: troppo poco per tre megabyte in più e una "
        "scrittura in più a ogni scatto."),
    "file_media": (2,
        "«Le ultime ventiquattro con la miniatura», mentre l'importazione "
        "va. Il piano dice SCAN, ma è un `ORDER BY id DESC LIMIT 24` e `id` "
        "è la chiave: SQLite cammina all'indietro sulla chiave e si ferma "
        "alla ventiquattresima — non c'è nessuna tavola d'appoggio nel "
        "piano, e non ci sarebbe modo di fermarsi se dovesse ordinare. "
        "Ventiquattro righe lette, non duecentomila.\n"
        "La seconda è l'elenco dei file spariti dal disco. Su un archivio "
        "vero parte dall'indice parziale dei percorsi spariti e tocca "
        "soltanto quelli: misurata su duecentomila file, 125 millesimi di "
        "secondo sono diventati 0,1. Qui la tabella ha una manciata di righe "
        "e SQLite sceglie di leggerle tutte, che è la scelta giusta: "
        "aprire un indice costa più di leggere venti righe."),
    "non_importati": (1,
        "I file che l'importazione non è riuscita a leggere, gli ultimi "
        "duecento. Questa ordina davvero — il piano chiede la tavola "
        "d'appoggio — ma la tabella tiene solo i guasti, e un archivio con "
        "tanti guasti da farla pesare ha un problema più grosso di questo."),
}

SENZA_DOMANDE = {
    "/blocco": "Quando il forziere non è acceso questa rimanda alle "
               "impostazioni prima di guardare qualunque cosa. È il "
               "comportamento giusto: non c'è niente da chiedere.",
}


def test_nessuna_lettura_larga_nuova(archivio_pieno):
    larghe = guarda(archivio_pieno)
    nuove = {tabella: domande for tabella, domande in larghe.items()
             if tabella not in PERDONATE}
    assert not nuove, (
        "una schermata legge una tabella grande da capo a fondo: "
        + "; ".join(f"{t}: {d[0][:120]}" for t, d in nuove.items()))


def test_nessuna_lettura_larga_si_fa_piu_volte_del_dovuto(archivio_pieno):
    larghe = guarda(archivio_pieno)
    for tabella, domande in larghe.items():
        tetto = PERDONATE[tabella][0]
        assert len(domande) <= tetto, (
            f"{tabella} si legge tutta {len(domande)} volte invece di "
            f"{tetto}: {domande}")


def test_ogni_pagina_e_ogni_comando_risponde_davvero(archivio_pieno):
    muti = []
    for metodo, dove, codice, quante in come_e_andata(archivio_pieno):
        if quante == 0 and dove in SENZA_DOMANDE:
            continue
        if codice not in (200, 303) or quante == 0:
            muti.append(f"{metodo} {dove}: risposta {codice}, "
                        f"{quante} domande")
    assert not muti, (
        "queste pagine o comandi non arrivano al database, e quindi non "
        "controllano niente:\n  " + "\n  ".join(muti))


RACCOLTE = {
    "SELECT p.percorso, f.impronta FROM percorsi AS p JOIN file_media AS f ON f.id = p.file_id "
    "WHERE p.presente = 1 ORDER BY p.id":
        "la copia di sicurezza su un altro disco: deve passare ogni originale, una volta per copia.",
    "UPDATE file_media SET miniatura = NULL WHERE genere = 'video'":
        "una volta sola, nella migrazione 32: ripara le foto live e le copertine dei video già nell'archivio.",
    "SELECT * FROM scatti": "il pacchetto per il telefono: è l'archivio.",
    "SELECT * FROM impronte": "idem, le impronte dentro il pacchetto.",
    "SELECT impronta FROM file_media WHERE miniatura IS NOT NULL":
        "la fusione di un pacchetto di sincronia, una volta prima di copiare: "
        "sapere quali miniature ci sono già evita di scriverne di inutili.",
    "SELECT scatto_id, impronta, ruolo FROM file_media WHERE scatto_id IS NOT "
    "NULL ORDER BY id": "idem, l'elenco di cosa sta con cosa.",
    "SELECT * FROM etichette ORDER BY id":
        "il giornale dei cambiamenti, rifatto da zero: ogni etichetta, per "
        "definizione.",
    "SELECT impronta, scatto_id FROM file_media WHERE scatto_id IS NOT NULL":
        "l'archivio finto che si costruisce da solo: non gira mai a casa di "
        "nessuno.",
    "SELECT id, impronta_occhio, dimensione FROM file_media WHERE "
    "impronta_occhio IS NOT NULL AND impronta_occhio != ''":
        "la passata dei doppioni confronta tutti con tutti: leggere tutto è "
        "il lavoro, e si fa una volta per passata.",
    "SELECT scatto_id, nodo_id, stato FROM etichette":
        "«da cosa impara ogni nodo», per tutti i nodi insieme "
        "(`esempi.nodi_con_esempi`). Legge tutte le etichette una volta, ed è "
        "il punto: prima chiedeva chi sta sotto, i «si» del ramo, i «no» e i "
        "fratelli **per ogni nodo** — quasi mille domande su un albero di "
        "centottanta, 250 millesimi. Adesso sono due letture e il resto si fa "
        "in memoria: 163.\n"
        "L'indice per chiuderla è stato provato: mettendo `scatto_id` in coda "
        "a `etichette_per_nodo` la lettura diventa coprente e passa da 58,8 a "
        "56,6 millesimi, per tre megabyte. Il conto non è nel leggere la "
        "tabella, è nel costruire sessantaduemila righe in Python — e quello "
        "l'indice non lo tocca. Rifiutato.",
    "SELECT p.id, p.file_id, p.percorso, p.presente, f.dimensione FROM "
    "percorsi p JOIN file_media f ON f.id = p.file_id":
        "«ci sono ancora?» (regola 96) chiede di ogni percorso: è proprio la "
        "domanda, e si fa solo quando la premi. La dimensione arriva dal "
        "file_media per la seconda domanda che si fa qui: un file messo da "
        "parte perché non si apriva è stato ricopiato? Se il peso sul disco "
        "non è più quello scritto, torna in coda da solo.",
    "SELECT g.firma, count(*) AS quante, min(g.distanza) AS distanza FROM "
    "doppioni_gruppi g WHERE NOT EXISTS (SELECT 1 FROM doppioni_decisi d "
    "WHERE d.firma = g.firma) GROUP BY g.firma HAVING quante > 1 ORDER BY "
    "quante DESC, distanza ASC, g.firma LIMIT ? OFFSET ?":
        "la tabella è a chiave (firma, file_id) e senza rowid: è già "
        "ordinata per firma, e cercare i gruppi ancora da decidere vuol dire "
        "guardarli tutti. Già spiegata fra le PERDONATE. Si vedeva solo "
        "adesso: prima il soprannome «g» la nascondeva allo strumento.",
    "SELECT s.giorno, count(*) AS quanti, group_concat(DISTINCT l.nome) AS "
    "luoghi FROM scatti s LEFT JOIN luoghi l ON l.id = s.luogo_id GROUP BY "
    "s.giorno ORDER BY s.giorno DESC":
        "il calendario del Visore, letto dal database del **pacchetto**: di "
        "scatti ne ha quanti se ne sono mandati al telefono, e un calendario "
        "per definizione li conta tutti. Si vedeva solo adesso: prima il "
        "soprannome «s» la nascondeva allo strumento.",
    "UPDATE scatti SET importazione_id = ( SELECT min(coda.importazione_id) "
    "FROM file_media AS file JOIN percorsi AS strada ON strada.file_id = "
    "file.id JOIN coda_importazione AS coda ON coda.percorso = strada.percorso "
    "WHERE file.scatto_id = scatti.id )":
        "il riempimento all'indietro della migrazione 23: deve toccare ogni "
        "scatto esattamente una volta, e succede **una volta nella vita "
        "dell'archivio**, dentro l'aggiornamento. Un indice non servirebbe a "
        "niente — non c'è nessuna riga da saltare, si vogliono tutte — e "
        "costerebbe a ogni scrittura da lì in avanti.",

    "SELECT id AS file_id FROM file_media WHERE miniatura IS NOT NULL ORDER "
    "BY id DESC LIMIT 24":
        "ventiquattro righe: cammina all'indietro sulla chiave e si ferma. "
        "Già spiegata fra le PERDONATE.",
    "SELECT * FROM non_importati ORDER BY tentato_il DESC LIMIT 200":
        "gli ultimi duecento guasti. Già spiegata fra le PERDONATE.",
    "SELECT * FROM scatti ORDER BY giorno DESC, istante_utc "
    "DESC LIMIT ? OFFSET ?":
        "una pagina del Visore, e per giunta letta dal database del "
        "**pacchetto**, che di scatti ne ha quanti se ne sono mandati.",
    "SELECT * FROM scatti WHERE nota LIKE ? ORDER BY giorno DESC":
        "la ricerca a parole nel Visore, sullo stesso database del pacchetto. "
        "Un `LIKE` con il per cento davanti non ha indice che tenga.",

    "SELECT firma FROM doppioni_gruppi GROUP BY firma HAVING count(*) > 1":
        "la tabella è già ordinata per firma. Già spiegata fra le "
        "PERDONATE.",

    "UPDATE file_media SET miniatura = NULL":
        "«svuota le miniature» dalle impostazioni: toglierle tutte è proprio "
        "quello che si è chiesto.",
    "SELECT * FROM file_media WHERE miniatura IS NULL AND genere = 'immagine' "
    "ORDER BY id LIMIT ?":
        "«rifà le miniature che mancano»: **non la chiama nessuno**, né il "
        "programma né una prova. Trovata proprio perché questo strumento "
        "legge i sorgenti invece di far succedere le cose. Misurata a 14,2 "
        "millesimi su duecentomila file, e un indice parziale da 4 kB la "
        "porterebbe a 0,1 — ma non si mette un indice per del codice che non "
        "gira. Prima va deciso se quella riparazione ci deve essere.",
    "UPDATE segnalazioni SET risolta = 1 WHERE tipo = 'non_si_apre' AND risolta = 0 "
    "AND dettaglio = 'senza_file' AND scatto_id IN (SELECT scatto_id FROM file_media "
    "WHERE genere = 'video')":
        "una migrazione che gira una volta sola, per togliere i video da "
        "«Da sistemare».",
    "UPDATE file_media SET latitudine = NULL, longitudine = NULL WHERE "
    "(latitudine IS NOT NULL AND (typeof(latitudine) NOT IN ('real', "
    "'integer') OR latitudine > 90 OR latitudine < -90)) OR (longitudine IS "
    "NOT NULL AND (typeof(longitudine) NOT IN ('real', 'integer') OR "
    "longitudine > 180 OR longitudine < -180))":
        "la migrazione 53, che gira una volta sola nella vita dell'archivio: "
        "toglie da file_media le coordinate che non stanno sul mondo (infinito, "
        "oltre 90 o 180 gradi). Non c'è nessuna riga da saltare, e un indice "
        "sulle coordinate costerebbe a ogni scrittura da lì in avanti.",
    "UPDATE scatti SET latitudine = NULL, longitudine = NULL WHERE "
    "(latitudine IS NOT NULL AND (typeof(latitudine) NOT IN ('real', "
    "'integer') OR latitudine > 90 OR latitudine < -90)) OR (longitudine IS "
    "NOT NULL AND (typeof(longitudine) NOT IN ('real', 'integer') OR "
    "longitudine > 180 OR longitudine < -180))":
        "la migrazione 53, che gira una volta sola nella vita dell'archivio: "
        "toglie da scatti le coordinate che non stanno sul mondo (infinito, "
        "oltre 90 o 180 gradi). Non c'è nessuna riga da saltare, e un indice "
        "sulle coordinate costerebbe a ogni scrittura da lì in avanti.",
}

QUANTE_NON_SI_LEGGONO = 64


def test_nessuna_lettura_larga_nuova_nei_sorgenti():
    from strumenti.letture_larghe import raccogli

    larghe, _ = raccogli()
    nuove = [(dove, domanda) for _, dove, domanda in larghe
             if domanda not in RACCOLTE]
    assert not nuove, (
        "una domanda nuova legge una tabella grande da capo a fondo. Se è "
        "giusto così, va scritto **perché** in RACCOLTE:\n  "
        + "\n  ".join(f"{d}: {s[:120]}" for d, s in nuove))


def test_la_lista_non_tiene_domande_che_non_esistono_piu():
    from strumenti.letture_larghe import raccogli

    larghe, _ = raccogli()
    vive = {domanda for _, _, domanda in larghe}
    morte = sorted(set(RACCOLTE) - vive)
    assert not morte, (
        "RACCOLTE spiega domande che nel programma non ci sono più:\n  "
        + "\n  ".join(d[:120] for d in morte))


def test_il_limite_dello_strumento_resta_quello_dichiarato():
    from strumenti.letture_larghe import raccogli

    _, illeggibili = raccogli()
    assert len(illeggibili) <= QUANTE_NON_SI_LEGGONO, (
        f"le domande che lo strumento non sa leggere sono passate da "
        f"{QUANTE_NON_SI_LEGGONO} a {len(illeggibili)}. Le ultime arrivate:\n  "
        + "\n  ".join(f"{d}: {s[:100]}" for d, _, s in illeggibili[-5:]))


def test_gli_altri_due_strumenti_guardano_le_stesse_stanze():
    from strumenti import giro_con_la_tastiera, guarda_le_schermate, letture_larghe

    assert guarda_le_schermate.PAGINE is letture_larghe.SCHERMATE
    assert giro_con_la_tastiera.PAGINE is letture_larghe.SCHERMATE
    assert set(letture_larghe.SCHERMATE) <= set(letture_larghe.PAGINE), (
        "una schermata che non sta fra le PAGINE non la guarda nessuno degli "
        "altri due strumenti")


def test_un_soprannome_non_nasconde_piu_una_lettura_larga():
    from strumenti.letture_larghe import _chi_legge_tutto, soprannomi

    domanda = ("SELECT s.id FROM scatti s JOIN percorsi AS p "
               "ON p.file_id = s.id WHERE s.nota IS NOT NULL")
    nomi = soprannomi(domanda)

    assert nomi == {"s": "scatti", "p": "percorsi"}
    assert _chi_legge_tutto("SCAN s", frozenset(), nomi) == "scatti"
    assert _chi_legge_tutto("SCAN p", frozenset(), nomi) == "percorsi"
    assert _chi_legge_tutto("SCAN s", frozenset()) == "s"


def test_una_parola_del_sql_non_diventa_un_soprannome():
    from strumenti.letture_larghe import soprannomi

    assert soprannomi("SELECT * FROM scatti WHERE id = 1") == {}
    assert soprannomi("SELECT * FROM scatti ORDER BY id") == {}
    assert soprannomi("SELECT * FROM scatti GROUP BY giorno") == {}
    assert soprannomi("SELECT * FROM scatti s LEFT JOIN luoghi l "
                      "ON l.id = s.luogo_id") == {"s": "scatti", "l": "luoghi"}
